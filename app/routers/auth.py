from fastapi import APIRouter, Response, Form, HTTPException, Depends
from ..security import authenticate, make_token, COOKIE_NAME, current_user
from ..config import get_settings

router = APIRouter()
_s = get_settings()


@router.post("/api/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    user = authenticate(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    token = make_token(user)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=_s.COOKIE_SECURE,
        samesite="lax", max_age=_s.SESSION_HOURS * 3600,
    )
    return {"ok": True, "name": user["full_name"], "role": user["role"]}


@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"name": user["name"], "role": user["role"],
            "professional_id": user.get("professional_id")}
