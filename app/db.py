"""Pool de conexões Postgres com TLS. Uma função simples de query."""
import contextlib
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from .config import get_settings

_settings = get_settings()

# Conexão TLS/segurança vêm da própria DATABASE_URL:
#  - IP público:  ...@IP:5432/materlux?sslmode=require
#  - Cloud Run (socket Cloud SQL):  ...@/materlux?host=/cloudsql/CONNECTION_NAME
# Por isso NÃO forçamos sslmode aqui (quebraria a conexão via socket unix).
_pool = ConnectionPool(
    conninfo=_settings.DATABASE_URL,
    kwargs={"row_factory": dict_row},
    min_size=1,
    max_size=8,
    # Cloud Run fica ocioso e o Cloud SQL fecha conexões paradas; sem isso, a
    # primeira query depois da ociosidade pegava uma conexão morta e estourava
    # ("server closed the connection unexpectedly"). check= valida e descarta a
    # conexão morta ANTES de entregar; max_lifetime recicla antes de ela morrer.
    check=ConnectionPool.check_connection,
    max_lifetime=1800,   # recicla cada conexão a cada 30 min
    max_idle=300,        # fecha conexões ociosas após 5 min (até min_size)
    open=False,
)


def open_pool():
    if _pool.closed:
        _pool.open()


def close_pool():
    _pool.close()


@contextlib.contextmanager
def get_conn():
    with _pool.connection() as conn:
        yield conn


def query(sql: str, params: tuple = (), *, one: bool = False, commit: bool = False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = None
            if cur.description is not None:
                result = cur.fetchone() if one else cur.fetchall()
            if commit:
                conn.commit()
            return result
