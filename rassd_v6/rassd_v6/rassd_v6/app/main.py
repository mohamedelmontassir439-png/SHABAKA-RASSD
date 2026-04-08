"""
Modern Business — Point d'entrée FastAPI
Importe et monte tous les routers.
"""
import os, asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config   import cfg
from app.core.database import init_db
from app.services.agents import (
    SLog, SState, MonitorAgent, SelfHealingAgent
)
from app.routes import auth, tenders, user, admin, api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRAND = "Modern Business"


class SecureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    SLog.add("Modern Business démarré")
    asyncio.create_task(MonitorAgent.run())
    asyncio.create_task(SelfHealingAgent.run())
    yield


app = FastAPI(
    lifespan=lifespan,
    title=BRAND,
    version="11.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(SecureMiddleware)

try:
    os.makedirs("app/static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except Exception as e:
    logger.warning(f"Static: {e}")

# ── Monter tous les routers ──
app.include_router(auth.router)
app.include_router(tenders.router)
app.include_router(user.router)
app.include_router(admin.router)
app.include_router(api.router)
