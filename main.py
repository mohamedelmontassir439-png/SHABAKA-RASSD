"""
RASSD v3.1 — SaaS Veille Marchés Publics Maroc
Production-ready · Fully audited
"""
import os, re, json, asyncio, logging
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import (HTMLResponse, RedirectResponse,
                               JSONResponse, StreamingResponse, Response)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config   import cfg
from app.core.database import get_db, init_db
from app.core.security import (hash_pw, verify_pw, make_token,
                                make_random_token, get_member,
                                validate_email, validate_password,
                                days_left)
from app.services.notifications import (
    dispatch_notifications, tg_admin,
    email_send, build_verify_email,
    build_reset_email
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-18s │ %(levelname)s │ %(message)s"
)
logger = logging.getLogger("rassd")

# ══════════════════════════════════════════════════════════
# SCRAPER STATE
# ══════════════════════════════════════════════════════════
class State:
    running  = False
    saved    = 0
    found    = 0
    errors   = 0
    last_run = ""
    logs: list = []

    @classmethod
    def log(cls, msg: str):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.logs.append(entry)
        logger.info(msg)
        if len(cls.logs) > 700:
            cls.logs = cls.logs[-500:]


# ══════════════════════════════════════════════════════════
# SCRAPER ENGINE
# ══════════════════════════════════════════════════════════
async def do_scrape():
    if State.running:
        return
    State.running = True
    State.saved = State.found = State.errors = 0
    t0_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        from app.services.scraper import run
    except ImportError as e:
        State.log(f"❌ Import scraper: {e}")
        State.running = False
        return

    try:
        db = get_db()
        known = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
        db.close()

        loop = asyncio.get_event_loop()
        tenders = await loop.run_in_executor(None, lambda: run(known, State.log))
        State.found = len(tenders)

        db = get_db()
        new_tenders = []
        for t in tenders:
            try:
                db.execute("""
                    INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,secteur,region,montant,
                     date_publication,date_limite,description,
                     url,statut,scraped_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    t["id"], t["objet"], t["acheteur"],
                    t.get("secteur",""), t.get("region",""),
                    t.get("montant",""), t.get("date_publication",""),
                    t.get("date_limite",""), t.get("description",""),
                    t["url"], t["statut"],
                    t["scraped_at"], t["scraped_at"],
                ))
                if db.execute("SELECT changes()").fetchone()[0]:
                    State.saved += 1
                    new_tenders.append(t)
            except Exception as e:
                State.errors += 1
                logger.error(f"[save {t.get('id')}] {e}")

        # Log scrape run
        db.execute(
            "INSERT INTO scrape_log(found,saved,errors,run_at) VALUES(?,?,?,?)",
            (State.found, State.saved, State.errors, t0_str)
        )
        db.commit()
        db.close()

        State.last_run = t0_str
        State.log(f"✅ {State.saved} nouveaux marchés sauvegardés")

        # Send notifications async
        if new_tenders:
            await loop.run_in_executor(
                None, lambda: dispatch_notifications(new_tenders)
            )

    except Exception as e:
        State.log(f"❌ Erreur scraper: {e}")
        logger.error(f"[do_scrape] {e}", exc_info=True)
    finally:
        State.running = False


async def scheduler():
    """Background scheduler: scan toutes les N minutes"""
    await asyncio.sleep(20)   # Attendre que l'app soit prête
    while True:
        try:
            await do_scrape()
        except Exception as e:
            logger.error(f"[scheduler] {e}")
        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN * 60)


# ══════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════
class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "X-Content-Type-Options":  "nosniff",
            "X-Frame-Options":         "DENY",
            "X-XSS-Protection":        "1; mode=block",
            "Referrer-Policy":         "strict-origin-when-cross-origin",
        })
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    State.log(f"RASSD v{cfg.APP_VERSION} démarré ✅")
    asyncio.create_task(scheduler())
    yield


app = FastAPI(
    lifespan=lifespan,
    title=cfg.APP_NAME,
    version=cfg.APP_VERSION,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(SecurityMiddleware)

templates = Jinja2Templates(directory="templates")
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass


# ── Helpers ──────────────────────────────────────────────
def render(req: Request, tpl: str, ctx: dict = {}):
    m = get_member(req)
    return templates.TemplateResponse(tpl, {
        "request":   req,
        "member":    m,
        "cfg":       cfg,
        "secteurs":  cfg.SECTEURS,
        "plans":     cfg.PLANS,
        "days_left": days_left,
        "dl":        days_left,
        "now":       datetime.now(),
        **ctx
    })


def send_verification_email(email: str, token: str, nom: str = "") -> bool:
    subject = "Confirmez votre adresse email RASSD"
    html = build_verify_email(email, token, nom)
    return email_send(email, subject, html)


def send_password_reset_email(email: str, token: str, nom: str = "") -> bool:
    subject = "Réinitialisation de votre mot de passe RASSD"
    html = build_reset_email(email, token, nom)
    return email_send(email, subject, html)


def get_stats() -> dict:
    db = get_db()
    try:
        return {
            "tenders": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "today":   db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND scraped_at>=date('now')").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "notifs":  db.execute("SELECT COUNT(*) FROM notif_log WHERE sent_at>=date('now','-7 days')").fetchone()[0],
            "expired": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
            "scrapes": db.execute("SELECT COUNT(*) FROM scrape_log").fetchone()[0],
        }
    finally:
        db.close()


def expire_tenders() -> tuple:
    db = get_db()
    today = date.today()
    expired_ids = []
    rows = db.execute(
        "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
    ).fetchall()
    for row in rows:
        m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(row["date_limite"]))
        if not m:
            continue
        try:
            fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
            if datetime.strptime(m.group(1), fmt).date() < today:
                expired_ids.append(row["id"])
        except Exception:
            pass
    if expired_ids:
        ph = ",".join(["?"] * len(expired_ids))
        db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", expired_ids)
        db.commit()
    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return len(expired_ids), active


def clean_secteurs(raw_list: list) -> list:
    """Nettoie la liste des secteurs (enlève vides, déduplique)"""
    return list({s for s in raw_list if s and s.strip()})


def get_days_left(date_str: str) -> int:
    if not date_str:
        return 0
    try:
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        return max(0, (d - date.today()).days)
    except Exception:
        return 0


def _is_admin(req: Request) -> bool:
    return req.cookies.get("_admin", "") == make_token("admin", cfg.ADMIN_PASS)


# ══════════════════════════════════════════════════════════

from app.routes import public_router, auth_router, user_router, admin_router, api_router

app.include_router(public_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(admin_router)
app.include_router(api_router)
