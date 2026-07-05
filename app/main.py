from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .config import get_settings
from . import db, security
from .routers import auth, appointments, patients, evolutions, whatsapp

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


@app.get("/health")
def health():
    try:
        db.query("SELECT 1", one=True)
        return {"status": "ok", "db": "up"}
    except Exception as e:  # noqa
        return {"status": "degraded", "db": str(e)}


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
