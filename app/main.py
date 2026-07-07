from pathlib import Path
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from .config import get_settings
from . import db, security
from .routers import auth, appointments, patients, evolutions, whatsapp, partos

_s = get_settings()
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="Materlux Cloud", version="1.0.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(appointments.router)
app.include_router(patients.router)
app.include_router(evolutions.router)
app.include_router(whatsapp.router)
app.include_router(partos.router)


@app.get("/health")
def health():
    try:
        db.query("SELECT 1", one=True)
        return {"status": "ok", "db": "up"}
    except Exception as e:  # noqa
        return {"status": "degraded", "db": str(e)}


@app.get("/health/deep")
def health_deep():
    """Checagem profunda para o Uptime Check: banco, WhatsApp (Z-API) e Gemini.

    Devolve 503 quando algo essencial está fora — é o código de status que o
    Cloud Monitoring usa para disparar o alerta.
    """
    checks = {}
    ok = True

    try:
        db.query("SELECT 1", one=True)
        checks["db"] = "ok"
    except Exception as e:  # noqa
        checks["db"] = f"erro: {e}"
        ok = False

    if _s.WA_PROVIDER == "zapi" and _s.ZAPI_INSTANCE:
        try:
            url = (f"https://api.z-api.io/instances/{_s.ZAPI_INSTANCE}"
                   f"/token/{_s.ZAPI_TOKEN}/status")
            headers = ({"Client-Token": _s.ZAPI_CLIENT_TOKEN}
                       if _s.ZAPI_CLIENT_TOKEN else {})
            j = httpx.get(url, headers=headers, timeout=10).json()
            if j.get("connected"):
                checks["whatsapp"] = "ok (conectado)"
            else:
                checks["whatsapp"] = f"desconectado: {j.get('error') or j}"
                ok = False
        except Exception as e:  # noqa
            checks["whatsapp"] = f"erro ao consultar Z-API: {e}"
            ok = False
    else:
        checks["whatsapp"] = f"não verificado (provider={_s.WA_PROVIDER})"

    if _s.GEMINI_API_KEY:
        checks["gemini"] = f"chave configurada (modelo {_s.GEMINI_MODEL})"
    else:
        checks["gemini"] = "GEMINI_API_KEY ausente"
        ok = False

    return JSONResponse({"status": "ok" if ok else "falha", "checks": checks},
                        status_code=200 if ok else 503)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if request.cookies.get(security.COOKIE_NAME):
        return RedirectResponse("/app")
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return TEMPLATES.TemplateResponse("login.html", {"request": request})


@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request):
    if not request.cookies.get(security.COOKIE_NAME):
        return RedirectResponse("/login")
    return TEMPLATES.TemplateResponse("app.html", {"request": request})
