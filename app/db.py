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
