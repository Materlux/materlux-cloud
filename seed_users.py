"""Define/atualiza as senhas dos usuários da equipe (hash bcrypt).

Uso:
    python seed_users.py murilo   NovaSenhaForte
    python seed_users.py isadora  NovaSenhaForte
    python seed_users.py recepcao NovaSenhaForte

As senhas nunca são gravadas em texto — só o hash vai para o banco.
Requer DATABASE_URL no ambiente (ou .env).
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from app import db
from app.security import hash_password  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    username, password = sys.argv[1].strip().lower(), sys.argv[2]
    if len(password) < 8:
        print("Senha deve ter ao menos 8 caracteres.")
        sys.exit(1)
    db.open_pool()
    updated = db.query(
        "UPDATE auth_app.users SET password_hash = %s WHERE username = %s RETURNING id",
        (hash_password(password), username), one=True, commit=True,
    )
    if updated:
        print(f"Senha atualizada para '{username}'.")
    else:
        print(f"Usuário '{username}' não encontrado. Rode a migração 001 primeiro.")
    db.close_pool()


if __name__ == "__main__":
    main()
