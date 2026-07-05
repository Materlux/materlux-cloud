"""Autenticação: hash de senha (bcrypt) e sessão via JWT em cookie httpOnly."""
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from fastapi import Request, HTTPException, Depends
from .config import get_settings
from . import db

_s = get_settings()
COOKIE_NAME = "materlux_session"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def authenticate(username: str, password: str):
    row = db.query(
        "SELECT id, username, full_name, password_hash, role, professional_id, is_active "
        "FROM auth_app.users WHERE username = %s",
        (username.strip().lower(),),
        one=True,
    )
    if not row or not row["is_active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return row


def make_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "professional_id": user["professional_id"],
        "name": user["full_name"],
        "iat": now,
        "exp": now + timedelta(hours=_s.SESSION_HOURS),
    }
    return jwt.encode(payload, _s.JWT_SECRET, algorithm=_s.JWT_ALG)


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        return jwt.decode(token, _s.JWT_SECRET, algorithms=[_s.JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sessão expirada")


def require_role(*roles):
    def _dep(user: dict = Depends(current_user)):
        if roles and user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Sem permissão")
        return user
    return _dep
