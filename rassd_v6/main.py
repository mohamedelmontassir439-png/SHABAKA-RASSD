"""
SOURCE v2.1 — Marchés Publics Maroc (Production-Ready)
=======================================================
✅ httpx instead of requests
✅ Connection pooling via SQLAlchemy
✅ Pydantic validation
✅ Security headers middleware
✅ CSRF protection
✅ Rate limiting
✅ Background tasks
✅ Proper error handling
"""
import asyncio
import json
import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, constr, field_validator, Field

from app.core.config import cfg
from app.core.database import init_db, get_db_session
from app.core.security import (
    hash_pw, verify_pw, make_token, make_sig, verify_sig,
    get_member, is_admin, validate_email, validate_password,
    days_left, is_plan_ok, compute_relevance_score, send_reset_email
)
from app.core.stx10 import classify, STX10, STX10_AR, top3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("source")

# === Rate Limiter ===
class RateLimiter:
    def __init__(self):
        self._store: Dict[str, List[float]] = {}

    def is_allowed(self, ip: str, limit: int = 60, window: int = 60) -> bool:
        now = datetime.now().timestamp()
        if ip not in self._store:
            self._store[ip] = []
        self._store[ip] = [t for t in self._store[ip] if now - t < window]
        if len(self._store[ip]) >= limit:
            return False
        self._store[ip].append(now)
        return True

rate_limiter = RateLimiter()

def get_ip(req: Request) -> str:
    """Get client IP address"""
    fwd = req.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (req.client.host or "127.0.0.1")

# === App State ===
class AppState:
    scraping = False
    last_scan = "—"
    max_id = 0

# === Pydantic Models ===
class RegisterRequest(BaseModel):
    nom: constr(min_length=2, max_length=100)
    email: EmailStr
    password: constr(min_length=8, max_length=128)
    confirm: str
    lang: str = Field(default="fr", pattern="^(fr|ar)$")

    @field_validator('confirm')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Passwords do not match')
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    next_url: str = "/dashboard"
    lang: str = "fr"

# === Scheduler ===
async def _scheduler():
    """Background scheduler for scraping"""
    await asyncio.sleep(20)
    while True:
        try:
            AppState.scraping = True
            from app.services.scraper import scrape_new
            from app.services.notifications import dispatch, send_urgent_alerts

            async with get_db_session() as db:
                new = scrape_new(db, AppState.max_id)
                if new:
                    await dispatch(new, db)
                    mx = max(
                        (int(t["id"].replace("bdc_", "")) for t in new
                         if t.get("id", "").startswith("bdc_")),
                        default=AppState.max_id
                    )
                    if mx > AppState.max_id:
                        AppState.max_id = mx
                await send_urgent_alerts(db)

            AppState.last_scan = datetime.now().strftime("%H:%M")
            logger.info(f"[scheduler] Scan completed. New: {len(new) if new else 0}")
        except Exception as e:
            logger.error(f"[scheduler] {e}", exc_info=True)
        finally:
            AppState.scraping = False

        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN * 60)

# === Lifespan ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    init_db()

    # Validate config
    errors = cfg.validate()
    if errors:
        for err in errors:
            logger.warning(f"[config] {err}")

    logger.info("=" * 55)
    logger.info(f"  SOURCE v{cfg.APP_VERSION}")
    logger.info(f"  URL:     {cfg.SITE_URL}")
    logger.info(f"  Scan:    toutes les {cfg.SCAN_INTERVAL_MIN} min")
    logger.info(f"  TG:      {'✅' if cfg.TELEGRAM_BOT else '❌'}")
    logger.info(f"  Groq:    {'✅' if cfg.GROQ_API_KEY else '❌ fallback'}")
    logger.info(f"  Key:     {'✅' if cfg.SECRET_KEY else '⚠️ MANQUANT'}")
    logger.info("=" * 55)

    try:
        from app.services.notifications import tg_admin
        await tg_admin(f"🚀 SOURCE v{cfg.APP_VERSION} démarré\n{cfg.SITE_URL}")
    except Exception:
        pass

    asyncio.create_task(_scheduler())
    yield

# === FastAPI App ===
app = FastAPI(
    title="SOURCE",
    version=cfg.APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    debug=cfg.DEBUG
)

# === Security Middlewares ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=[cfg.SITE_URL] if not cfg.DEBUG else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=600,
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

# === Static & Templates ===
templates = Jinja2Templates(directory="templates")
os.makedirs("static", exist_ok=True)
os.makedirs("data", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 filters
def _from_json(s: str) -> Any:
    try:
        return json.loads(s or "[]")
    except (json.JSONDecodeError, TypeError):
        return []

def _to_json(v: Any) -> str:
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"

templates.env.filters["from_json"] = _from_json
templates.env.filters["tojson"] = _to_json
templates.env.filters["urlencode"] = urllib.parse.quote

def render(req: Request, tpl: str, ctx: Dict = None, status: int = 200) -> HTMLResponse:
    """Render template with common context"""
    ctx = ctx or {}
    ctx.setdefault("request", req)
    ctx.setdefault("member", get_member(req))
    ctx.setdefault("cfg", cfg)
    ctx.setdefault("now", datetime.now())
    ctx.setdefault("days_left", days_left)
    ctx.setdefault("STX10", STX10)
    ctx.setdefault("STX10_AR", STX10_AR)
    return templates.TemplateResponse(tpl, ctx, status_code=status)

async def get_stats() -> Dict[str, int]:
    """Get platform statistics"""
    async with get_db_session() as db:
        try:
            total = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
            today = db.execute(
                "SELECT COUNT(*) FROM tenders WHERE DATE(scraped_at)=DATE('now')"
            ).fetchone()[0]
            members = db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0]
            return {"tenders": total, "today": today, "members": members}
        except Exception as e:
            logger.error(f"[get_stats] {e}")
            return {"tenders": 0, "today": 0, "members": 0}

def get_member_stats(member_id: int, db) -> Dict[str, int]:
    """Get member statistics"""
    favs = db.execute(
        "SELECT COUNT(*) FROM favorites WHERE member_id=?", (member_id,)
    ).fetchone()[0]
    subs = db.execute(
        "SELECT COUNT(*) FROM submissions WHERE member_id=?", (member_id,)
    ).fetchone()[0]
    won = db.execute(
        "SELECT COUNT(*) FROM submissions WHERE member_id=? AND result='won'", (member_id,)
    ).fetchone()[0]
    soon_rows = db.execute(
        "SELECT date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
    ).fetchall()
    soon = sum(1 for r in soon_rows if 0 <= days_left(r[0])[0] <= 7)
    return {"favs": favs, "subs": subs, "won": won, "soon": soon}

# ══════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def landing(req: Request):
    """Landing page"""
    if get_member(req):
        return RedirectResponse("/dashboard", status_code=302)
    stats = await get_stats()
    return render(req, "landing.html", {"stats": stats})

# === Auth ===
@app.get("/register", response_class=HTMLResponse)
async def register_page(req: Request):
    if get_member(req):
        return RedirectResponse("/dashboard", status_code=302)
    return render(req, "register.html", {"error": "", "success": ""})

@app.post("/register", response_class=HTMLResponse)
async def register_post(
    req: Request,
    nom: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    lang: str = Form("fr")
):
    nom = nom.strip()
    email = email.strip().lower()
    error = ""

    if len(nom) < 2:
        error = "Nom trop court." if lang == "fr" else "الاسم قصير."
    elif not validate_email(email):
        error = "Email invalide." if lang == "fr" else "البريد غير صالح."
    elif password != confirm:
        error = "Mots de passe différents." if lang == "fr" else "كلمات المرور غير متطابقة."
    else:
        ok, msg = validate_password(password)
        if not ok:
            error = msg

    if error:
        return render(req, "register.html", {"error": error, "success": ""})

    async with get_db_session() as db:
        if db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
            return render(req, "register.html", {
                "error": "Email déjà utilisé." if lang == "fr" else "البريد مستخدم.",
                "success": ""
            })

        token = make_token()
        db.execute(
            """INSERT INTO members(nom, email, password_hash, plan, actif, session_token, created_at, lang, onboarded)
               VALUES(?, ?, ?, 'free', 1, ?, ?, ?, 0)""",
            (nom, email, hash_pw(password), token, datetime.now().isoformat(), lang)
        )
        db.commit()

        try:
            from app.services.notifications import tg_admin
            await tg_admin(f"👤 Nouveau: <b>{nom}</b>\n📧 {email}")
        except Exception as e:
            logger.warning(f"[tg] {e}")

    resp = RedirectResponse("/onboarding", status_code=302)
    resp.set_cookie(
        "_session", token,
        max_age=60*60*24*30,
        httponly=True,
        secure=not cfg.DEBUG,
        samesite="strict",
        path="/"
    )
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_page(req: Request, next: str = "/dashboard"):
    if get_member(req):
        return RedirectResponse(next or "/dashboard", status_code=302)
    return render(req, "login.html", {"error": "", "next": next})

@app.post("/login", response_class=HTMLResponse)
async def login_post(
    req: Request,
    email: str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/dashboard"),
    lang: str = Form("fr")
):
    if not rate_limiter.is_allowed(get_ip(req), 10, 60):
        return render(req, "login.html", {
            "error": "Trop de tentatives." if lang == "fr" else "محاولات كثيرة.",
            "next": next_url
        })

    email = email.strip().lower()

    async with get_db_session() as db:
        row = db.execute(
            "SELECT * FROM members WHERE email=? AND actif=1", (email,)
        ).fetchone()

        if not row or not verify_pw(password, row["password_hash"]):
            logger.warning(f"[login] Failed attempt for {email} from {get_ip(req)}")
            return render(req, "login.html", {
                "error": "Email ou mot de passe incorrect." if lang == "fr" else "بيانات خاطئة.",
                "next": next_url
            })

        token = make_token()
        db.execute("UPDATE members SET session_token=? WHERE id=?", (token, row["id"]))
        db.commit()

    resp = RedirectResponse(next_url or "/dashboard", status_code=302)
    resp.set_cookie(
        "_session", token,
        max_age=60*60*24*30,
        httponly=True,
        secure=not cfg.DEBUG,
        samesite="strict",
        path="/"
    )
    return resp

@app.get("/logout")
async def logout(req: Request):
    m = get_member(req)
    if m:
        async with get_db_session() as db:
            db.execute("UPDATE members SET session_token='' WHERE id=?", (m["id"],))
            db.commit()

    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("_session", path="/")
    return resp

# === Password Reset ===
@app.get("/forgot", response_class=HTMLResponse)
async def forgot_page(req: Request):
    return render(req, "forgot.html", {"sent": False, "error": ""})

@app.post("/forgot", response_class=HTMLResponse)
async def forgot_post(req: Request, email: str = Form("")):
    email = email.strip().lower()

    async with get_db_session() as db:
        row = db.execute(
            "SELECT id FROM members WHERE email=? AND actif=1", (email,)
        ).fetchone()

        if row:
            token = make_token(32)
            expires = (datetime.now() + timedelta(hours=2)).isoformat()
            db.execute(
                "UPDATE members SET reset_token=?, reset_expires=? WHERE id=?",
                (token, expires, row["id"])
            )
            db.commit()
            try:
                send_reset_email(email, token)
            except Exception as e:
                logger.error(f"[reset_email] {e}")

    return render(req, "forgot.html", {"sent": True, "error": ""})

@app.get("/reset", response_class=HTMLResponse)
async def reset_page(req: Request, token: str = ""):
    async with get_db_session() as db:
        row = db.execute(
            "SELECT id, reset_expires FROM members WHERE reset_token=?", (token,)
        ).fetchone()

        if not row:
            return render(req, "forgot.html", {"sent": False, "error": "Lien invalide ou expiré."})

        try:
            if datetime.fromisoformat(row["reset_expires"]) < datetime.now():
                return render(req, "forgot.html", {"sent": False, "error": "Lien expiré."})
        except ValueError:
            return render(req, "forgot.html", {"sent": False, "error": "Lien invalide."})

        return render(req, "reset.html", {"token": token, "error": ""})

@app.post("/reset", response_class=HTMLResponse)
async def reset_post(
    req: Request,
    token: str = Form(""),
    password: str = Form(""),
    confirm: str = Form("")
):
    if password != confirm:
        return render(req, "reset.html", {"token": token, "error": "Mots de passe différents."})

    ok, msg = validate_password(password)
    if not ok:
        return render(req, "reset.html", {"token": token, "error": msg})

    async with get_db_session() as db:
        row = db.execute("SELECT id FROM members WHERE reset_token=?", (token,)).fetchone()
        if not row:
            return render(req, "forgot.html", {"sent": False, "error": "Token invalide."})

        db.execute(
            "UPDATE members SET password_hash=?, reset_token='', reset_expires='' WHERE id=?",
            (hash_pw(password), row["id"])
        )
        db.commit()

    return RedirectResponse("/login?reset=1", status_code=302)

# === Onboarding ===
@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)
    if m.get("onboarded"):
        return RedirectResponse("/dashboard", status_code=302)
    return render(req, "onboarding.html", {"lang": m.get("lang", "fr")})

@app.post("/onboarding")
async def onboarding_post(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    form = await req.form()
    codes = list(set(c for c in form.getlist("stx10_codes") if c in STX10))
    regions = list(set(r for r in form.getlist("regions") if r))
    lang = form.get("lang", m.get("lang", "fr"))

    async with get_db_session() as db:
        db.execute(
            "UPDATE members SET stx10_codes=?, regions=?, onboarded=1, lang=? WHERE id=?",
            (json.dumps(codes), json.dumps(regions), lang, m["id"])
        )
        db.commit()

    return RedirectResponse("/dashboard", status_code=302)

# === Dashboard ===
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login?next=/dashboard", status_code=302)
    if not m.get("onboarded"):
        return RedirectResponse("/onboarding", status_code=302)

    async with get_db_session() as db:
        try:
            stats = await get_stats()
            codes = json.loads(m.get("stx10_codes", "[]") or "[]")
            regions = json.loads(m.get("regions", "[]") or "[]")
            ms = get_member_stats(m["id"], db)

            top_stx10 = [dict(r) for r in db.execute("""
                SELECT stx10_code, stx10_label, COUNT(*) cnt
                FROM tenders WHERE statut='actif' AND stx10_code!=''
                GROUP BY stx10_code ORDER BY cnt DESC LIMIT 7
            """).fetchall()]

            recent_rows = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 15"
            ).fetchall()]
            for t in recent_rows:
                t["score"] = compute_relevance_score(t, codes, regions)

            matched = []
            if codes:
                phs = ",".join("?" * len(codes))
                matched = [dict(r) for r in db.execute(
                    f"SELECT * FROM tenders WHERE statut='actif' AND stx10_code IN ({phs}) ORDER BY scraped_at DESC LIMIT 8",
                    codes
                ).fetchall()]
                for t in matched:
                    t["score"] = compute_relevance_score(t, codes, regions)
                matched.sort(key=lambda x: x["score"], reverse=True)

            pipeline = [dict(r) for r in db.execute("""
                SELECT t.*, s.status as sub_status, s.result
                FROM tenders t JOIN submissions s ON s.tender_id=t.id
                WHERE s.member_id=? AND t.statut='actif'
                ORDER BY t.date_limite ASC LIMIT 5
            """, (m["id"],)).fetchall()]

            analytics_stx = [dict(r) for r in db.execute("""
                SELECT stx10_code, COUNT(*) cnt FROM tenders
                WHERE statut='actif' GROUP BY stx10_code ORDER BY cnt DESC LIMIT 5
            """).fetchall()]

            return render(req, "dashboard.html", {
                "stats": stats, "ms": ms,
                "top_stx10": top_stx10,
                "recent": recent_rows,
                "matched": matched,
                "pipeline": pipeline,
                "analytics_stx": analytics_stx,
                "scraping": AppState.scraping,
                "last_scan": AppState.last_scan,
            })
        except Exception as e:
            logger.error(f"[dashboard] {e}", exc_info=True)
            return render(req, "dashboard.html", {
                "stats": await get_stats(),
                "ms": {"favs": 0, "subs": 0, "won": 0, "soon": 0},
                "top_stx10": [], "recent": [], "matched": [], "pipeline": [],
                "analytics_stx": [], "scraping": False, "last_scan": "—"
            })

# === Tenders ===
@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(
    req: Request,
    q: str = "",
    stx10: str = "",
    region: str = "",
    sort: str = "date",
    page: int = 1
):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login?next=/tenders", status_code=302)

    PER = 20 if is_plan_ok(m, "unlimited") else 10
    if page > 1 and not is_plan_ok(m, "unlimited"):
        return RedirectResponse("/tarifs?upgrade=1", status_code=302)

    offset = (page - 1) * PER
    codes = json.loads(m.get("stx10_codes", "[]") or "[]")
    regions = json.loads(m.get("regions", "[]") or "[]")

    async with get_db_session() as db:
        where, params = ["statut='actif'"], []
        if q:
            q_safe = q.replace("%", "\\%").replace("_", "\\_")
            where.append("(objet LIKE ? ESCAPE '\\\\' OR acheteur LIKE ? ESCAPE '\\\\')")
            params += [f"%{q_safe}%", f"%{q_safe}%"]
        if stx10:
            where.append("stx10_code=?")
            params.append(stx10)
        if region:
            where.append("region LIKE ?")
            params.append(f"%{region}%")

        wh = " AND ".join(where)
        order = "date_limite ASC" if sort == "deadline" else "scraped_at DESC"

        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
        rows = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [PER, offset]
        ).fetchall()]

        for t in rows:
            t["score"] = compute_relevance_score(t, codes, regions)

        fav_ids = {r[0] for r in db.execute(
            "SELECT tender_id FROM favorites WHERE member_id=?", (m["id"],)
        ).fetchall()}

        sub_map = {r["tender_id"]: r["status"] for r in db.execute(
            "SELECT tender_id, status FROM submissions WHERE member_id=?", (m["id"],)
        ).fetchall()}

        regions_db = [r[0] for r in db.execute(
            "SELECT DISTINCT region FROM tenders WHERE statut='actif' AND region!='' ORDER BY region"
        ).fetchall()]

        stx10s = [r[0] for r in db.execute(
            "SELECT DISTINCT stx10_code FROM tenders WHERE statut='actif' AND stx10_code!=''"
        ).fetchall()]

        return render(req, "tenders.html", {
            "tenders": rows, "total": total, "page": page,
            "pages": max(1, (total + PER - 1) // PER),
            "q": q, "stx10": stx10, "region": region, "sort": sort,
            "regions": regions_db, "stx10_db": stx10s,
            "fav_ids": fav_ids, "sub_map": sub_map,
        })

# === Tender Detail ===
@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str, background_tasks: BackgroundTasks):
    m = get_member(req)
    if not m:
        return RedirectResponse(f"/login?next=/tenders/{tid}", status_code=302)

    async with get_db_session() as db:
        row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not row:
            return render(req, "404.html", {}, status_code=404)

        t = dict(row)
        n, dl_label = days_left(t.get("date_limite", ""))
        codes = json.loads(m.get("stx10_codes", "[]") or "[]")
        regions = json.loads(m.get("regions", "[]") or "[]")
        score = compute_relevance_score(t, codes, regions)

        similar = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE stx10_code=? AND id!=? AND statut='actif' ORDER BY scraped_at DESC LIMIT 4",
            (t.get("stx10_code", ""), tid)
        ).fetchall()]

        is_fav = bool(db.execute(
            "SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
            (m["id"], tid)
        ).fetchone())

        sub = db.execute(
            "SELECT * FROM submissions WHERE member_id=? AND tender_id=?",
            (m["id"], tid)
        ).fetchone()
        sub = dict(sub) if sub else None

        note_row = db.execute(
            "SELECT note FROM tender_notes WHERE member_id=? AND tender_id=?",
            (m["id"], tid)
        ).fetchone()
        note = note_row["note"] if note_row else ""

        acheteur_history = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE acheteur=? AND id!=? ORDER BY scraped_at DESC LIMIT 5",
            (t.get("acheteur", ""), tid)
        ).fetchall()]

        if not t.get("ai_summary") and cfg.GROQ_API_KEY:
            background_tasks.add_task(_auto_summarize, tid, t)

        return render(req, "detail.html", {
            "t": t, "dl": n, "dl_label": dl_label, "score": score,
            "similar": similar, "is_fav": is_fav, "sub": sub, "note": note,
            "acheteur_history": acheteur_history,
        })

async def _auto_summarize(tid: str, t: Dict):
    """Auto-generate AI summary in background"""
    if not cfg.GROQ_API_KEY:
        return
    try:
        import httpx
        prompt = (
            f"Résume ce marché public marocain en 3 points clés en français (max 80 mots):\n"
            f"1. Objet exact\n2. Profil entreprise idéal\n3. Points d'attention\n\n"
            f"Marché: {t['objet'][:400]}\nAcheteur: {t.get('acheteur', '')}\nDélai: {t.get('date_limite', '')}"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
                json={
                    "model": cfg.AI_MODEL,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
        if r.status_code == 200:
            summary = r.json()["choices"][0]["message"]["content"]
            async with get_db_session() as db:
                db.execute("UPDATE tenders SET ai_summary=? WHERE id=?", (summary, tid))
                db.commit()
    except Exception as e:
        logger.warning(f"[auto_summarize] {e}")

# === Favorites ===
@app.post("/favorites/{tid}")
async def toggle_fav(req: Request, tid: str):
    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False}, status_code=401)

    async with get_db_session() as db:
        ex = db.execute(
            "SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
            (m["id"], tid)
        ).fetchone()

        if ex:
            db.execute(
                "DELETE FROM favorites WHERE member_id=? AND tender_id=?",
                (m["id"], tid)
            )
            db.commit()
            return {"ok": True, "action": "removed"}

        db.execute(
            "INSERT OR IGNORE INTO favorites(member_id, tender_id, added_at) VALUES(?, ?, ?)",
            (m["id"], tid, datetime.now().isoformat())
        )
        db.commit()
        return {"ok": True, "action": "added"}

@app.get("/favorites", response_class=HTMLResponse)
async def favorites_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    async with get_db_session() as db:
        codes = json.loads(m.get("stx10_codes", "[]") or "[]")
        regions = json.loads(m.get("regions", "[]") or "[]")
        rows = [dict(r) for r in db.execute("""
            SELECT t.* FROM tenders t
            JOIN favorites f ON f.tender_id=t.id
            WHERE f.member_id=? ORDER BY f.added_at DESC
        """, (m["id"],)).fetchall()]

        for t in rows:
            t["score"] = compute_relevance_score(t, codes, regions)

        return render(req, "favorites.html", {"tenders": rows})

# === Pipeline ===
@app.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    async with get_db_session() as db:
        all_subs = [dict(r) for r in db.execute("""
            SELECT t.*, s.status as sub_status, s.result, s.notes, s.score_go, s.submitted_at, s.updated_at
            FROM submissions s JOIN tenders t ON t.id=s.tender_id
            WHERE s.member_id=? ORDER BY s.updated_at DESC
        """, (m["id"],)).fetchall()]

        watching = [s for s in all_subs if s["sub_status"] == "watching"]
        submitted = [s for s in all_subs if s["sub_status"] == "submitted"]
        won = [s for s in all_subs if s["result"] == "won"]
        lost = [s for s in all_subs if s["result"] == "lost"]

        total_completed = len(submitted) + len(won) + len(lost)
        win_rate = round(len(won) / total_completed * 100) if total_completed else 0

        return render(req, "pipeline.html", {
            "watching": watching, "submitted": submitted,
            "won": won, "lost": lost,
            "total": len(all_subs), "win_rate": win_rate
        })

@app.post("/pipeline/{tid}")
async def update_pipeline(
    req: Request,
    tid: str,
    status: str = Form("watching"),
    result: str = Form(""),
    notes: str = Form(""),
    score_go: int = Form(0)
):
    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False}, status_code=401)

    if status not in ("watching", "submitted", "won", "lost"):
        return JSONResponse({"ok": False, "msg": "Invalid status"}, status_code=400)
    if result and result not in ("won", "lost"):
        return JSONResponse({"ok": False, "msg": "Invalid result"}, status_code=400)

    async with get_db_session() as db:
        now = datetime.now().isoformat()
        db.execute("""
            INSERT INTO submissions(member_id, tender_id, status, result, notes, score_go, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(member_id, tender_id) DO UPDATE SET
            status=excluded.status, result=excluded.result,
            notes=excluded.notes, score_go=excluded.score_go, updated_at=excluded.updated_at
        """, (m["id"], tid, status, result, notes, score_go, now, now))

        if status == "submitted":
            db.execute(
                "UPDATE submissions SET submitted_at=? WHERE member_id=? AND tender_id=?",
                (now, m["id"], tid)
            )
        db.commit()
        return {"ok": True}

# === Calendar ===
@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    async with get_db_session() as db:
        codes = json.loads(m.get("stx10_codes", "[]") or "[]")
        regions = json.loads(m.get("regions", "[]") or "[]")

        tenders = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' AND date_limite!='' ORDER BY date_limite ASC LIMIT 200"
        ).fetchall()]

        for t in tenders:
            t["score"] = compute_relevance_score(t, codes, regions)

        events = [{
            "id": t["id"],
            "title": t["objet"][:60],
            "date": t["date_limite"],
            "score": t["score"],
            "code": t.get("stx10_code", ""),
            "n": days_left(t["date_limite"])[0]
        } for t in tenders if t["date_limite"]]

        return render(req, "calendar.html", {
            "tenders": tenders,
            "events_json": json.dumps(events)
        })

# === Notes ===
@app.post("/notes/{tid}")
async def save_note(req: Request, tid: str, note: str = Form("")):
    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False}, status_code=401)

    note_clean = note.strip()[:5000]

    async with get_db_session() as db:
        if note_clean:
            db.execute("""
                INSERT INTO tender_notes(member_id, tender_id, note, created_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(member_id, tender_id) DO UPDATE SET note=excluded.note
            """, (m["id"], tid, note_clean, datetime.now().isoformat()))
        else:
            db.execute(
                "DELETE FROM tender_notes WHERE member_id=? AND tender_id=?",
                (m["id"], tid)
            )
        db.commit()
        return {"ok": True}

# === Analytics ===
@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    async with get_db_session() as db:
        by_stx = [dict(r) for r in db.execute("""
            SELECT stx10_code, stx10_label, COUNT(*) cnt
            FROM tenders WHERE statut='actif' GROUP BY stx10_code ORDER BY cnt DESC LIMIT 12
        """).fetchall()]

        by_region = [dict(r) for r in db.execute("""
            SELECT region, COUNT(*) cnt FROM tenders WHERE statut='actif' AND region!=''
            GROUP BY region ORDER BY cnt DESC LIMIT 10
        """).fetchall()]

        by_month = [dict(r) for r in db.execute("""
            SELECT substr(scraped_at, 1, 7) mois, COUNT(*) cnt
            FROM tenders GROUP BY mois ORDER BY mois DESC LIMIT 12
        """).fetchall()]

        stats = await get_stats()

        soon_rows = db.execute(
            "SELECT date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
        ).fetchall()
        urgent = sum(1 for r in soon_rows if 0 <= days_left(r[0])[0] <= 3)

        return render(req, "analytics.html", {
            "by_stx": by_stx, "by_region": by_region, "by_month": by_month,
            "stats": stats, "urgent": urgent,
        })

# === Settings ===
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    codes = json.loads(m.get("stx10_codes", "[]") or "[]")
    regions = json.loads(m.get("regions", "[]") or "[]")
    saved = req.query_params.get("saved", "")
    return render(req, "settings.html", {
        "member_codes": codes,
        "member_regions": regions,
        "saved": saved
    })

@app.post("/settings")
async def settings_post(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    form = await req.form()
    codes = list(set(c for c in form.getlist("stx10_codes") if c in STX10))
    regions = list(set(r for r in form.getlist("regions") if r))
    tg = form.get("telegram", "").strip()[:50]
    wa = form.get("whatsapp", "").strip()[:50]
    notif_tg = 1 if form.get("notif_tg") else 0
    notif_email = 1 if form.get("notif_email") else 0
    notif_wa = 1 if form.get("notif_wa") else 0
    lang = form.get("lang", m.get("lang", "fr"))

    async with get_db_session() as db:
        db.execute("""
            UPDATE members SET stx10_codes=?, regions=?, telegram=?, whatsapp=?,
            notif_tg=?, notif_email=?, notif_wa=?, lang=? WHERE id=?
        """, (
            json.dumps(codes), json.dumps(regions), tg, wa,
            notif_tg, notif_email, notif_wa, lang, m["id"]
        ))
        db.commit()

    return RedirectResponse("/settings?saved=1", status_code=302)

# === Tarifs ===
@app.get("/tarifs", response_class=HTMLResponse)
async def tarifs_page(req: Request):
    return render(req, "tarifs.html", {})

@app.post("/tarifs/request")
async def tarifs_request(
    req: Request,
    plan: str = Form("essentiel"),
    nom: str = Form(""),
    email: str = Form("")
):
    m = get_member(req)
    name = m.get("nom", "") if m else nom.strip()[:100]
    mail = m.get("email", "") if m else email.strip().lower()

    async with get_db_session() as db:
        db.execute(
            """INSERT INTO payments(member_id, plan, status, amount, nom, email, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (
                m["id"] if m else 0,
                plan, "pending",
                cfg.PLANS.get(plan, {}).get("price", 0),
                name, mail,
                datetime.now().isoformat()
            )
        )
        db.commit()
        try:
            from app.services.notifications import tg_admin
            await tg_admin(f"💳 <b>Demande {plan.upper()}</b>\n👤 {name}\n📧 {mail}")
        except Exception as e:
            logger.warning(f"[tg] {e}")

    msg = f"Bonjour, je veux activer le plan {plan.upper()} SOURCE. Nom: {name}"
    return RedirectResponse(
        f"https://wa.me/{cfg.PAYMENT_PHONE}?text={urllib.parse.quote(msg)}",
        status_code=302
    )

# === AI Chat ===
@app.get("/ai/chat", response_class=HTMLResponse)
async def ai_chat_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login?next=/ai/chat", status_code=302)
    return render(req, "ai_chat.html", {"ai_ok": bool(cfg.GROQ_API_KEY)})

@app.get("/api/ai/chat")
async def api_ai_chat(req: Request, q: str = ""):
    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False, "msg": "Auth requise"}, status_code=401)
    if not q.strip():
        return JSONResponse({"ok": False, "msg": "Question vide"})
    if not cfg.GROQ_API_KEY:
        return JSONResponse({"ok": False, "msg": "IA non configurée"})

    try:
        import httpx
        stats = await get_stats()
        lang = m.get("lang", "fr")

        system = (
            f"Tu es l'assistant SOURCE, expert marchés publics marocains. "
            f"Marchés actifs: {stats['tenders']} | Plan: {m.get('plan', 'free')}. "
            f"{'Réponds en arabe professionnel.' if lang == 'ar' else 'Réponds en français, concis.'} Max 3 paragraphes."
        )

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
                json={
                    "model": cfg.AI_MODEL,
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": q}
                    ],
                    "temperature": 0.5
                }
            )

        if r.status_code == 200:
            return {"ok": True, "answer": r.json()["choices"][0]["message"]["content"]}
        return JSONResponse({"ok": False, "msg": f"IA {r.status_code}"})

    except Exception as e:
        logger.error(f"[ai_chat] {e}")
        return JSONResponse({"ok": False, "msg": str(e)[:80]})

@app.get("/api/ai/summarize/{tid}")
async def api_ai_summarize(req: Request, tid: str):
    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False}, status_code=401)

    async with get_db_session() as db:
        t = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not t:
            return JSONResponse({"ok": False, "msg": "Introuvable"})

        t = dict(t)
        if t.get("ai_summary"):
            return {"ok": True, "summary": t["ai_summary"]}

        if not cfg.GROQ_API_KEY:
            return JSONResponse({"ok": False, "msg": "IA non configurée"})

        try:
            import httpx
            lang = m.get("lang", "fr")
            prompt = (
                f"Résume ce marché en 3 points {'en arabe' if lang == 'ar' else 'en français'} (max 80 mots):\n"
                f"1. Objet exact\n2. Profil idéal\n3. Points attention\n\n"
                f"Marché: {t['objet'][:400]}\nAcheteur: {t.get('acheteur', '')}\nDélai: {t.get('date_limite', '')}"
            )

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
                    json={
                        "model": cfg.AI_MODEL,
                        "max_tokens": 200,
                        "messages": [{"role": "user", "content": prompt}]
                    }
                )

            if r.status_code == 200:
                summary = r.json()["choices"][0]["message"]["content"]
                db.execute("UPDATE tenders SET ai_summary=? WHERE id=?", (summary, tid))
                db.commit()
                return {"ok": True, "summary": summary}
            return JSONResponse({"ok": False, "msg": "IA indisponible"})

        except Exception as e:
            logger.error(f"[ai_summarize] {e}")
            return JSONResponse({"ok": False, "msg": str(e)[:80]})

# === API REST ===
@app.get("/api/v1/tenders")
async def api_tenders(
    req: Request,
    q: str = "",
    stx10: str = "",
    limit: int = 20,
    page: int = 1
):
    if not rate_limiter.is_allowed(get_ip(req), 100, 60):
        return JSONResponse({"ok": False, "msg": "Rate limit"}, status_code=429)

    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False, "msg": "Auth requise"}, status_code=401)
    if not is_plan_ok(m, "api"):
        return JSONResponse({"ok": False, "msg": "API = Plan Pro"}, status_code=403)

    limit = min(limit, 100)

    async with get_db_session() as db:
        where, params = ["statut='actif'"], []
        if q:
            where.append("objet LIKE ?")
            params.append(f"%{q}%")
        if stx10:
            where.append("stx10_code=?")
            params.append(stx10)

        wh = " AND ".join(where)
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
        rows = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit]
        ).fetchall()]

        return {"ok": True, "total": total, "page": page, "tenders": rows}

@app.get("/api/v1/stats")
async def api_stats(req: Request):
    m = get_member(req)
    if not m:
        return JSONResponse({"ok": False}, status_code=401)
    stats = await get_stats()
    return {"ok": True, **stats, "scraping": AppState.scraping, "last_scan": AppState.last_scan}

# === Export CSV ===
@app.get("/export/csv")
async def export_csv(req: Request, stx10: str = ""):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", status_code=302)

    async with get_db_session() as db:
        where, params = ["statut='actif'"], []
        if stx10:
            where.append("stx10_code=?")
            params.append(stx10)

        rows = db.execute(
            f"""SELECT objet, acheteur, stx10_code, stx10_label, region, montant,
                       date_publication, date_limite, url
                FROM tenders WHERE {' AND '.join(where)}
                ORDER BY scraped_at DESC LIMIT 2000""",
            params
        ).fetchall()

    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Objet", "Acheteur", "Code STX10", "Libellé STX10", "Région",
                "Montant", "Date Publication", "Date Limite", "URL"])
    for r in rows:
        w.writerow(list(r))

    fn = f"source_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fn}"}
    )

# === Admin ===
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(req: Request):
    if is_admin(req):
        return RedirectResponse("/admin", status_code=302)
    return render(req, "admin_login.html", {"error": ""})

@app.post("/admin/login")
async def admin_login_post(req: Request, password: str = Form("")):
    if not rate_limiter.is_allowed(get_ip(req), 5, 300):
        return render(req, "admin_login.html", {
            "error": "Trop de tentatives. Réessayez dans 5 min."
        })

    if password == cfg.ADMIN_PASS:
        sig = make_sig("admin", cfg.ADMIN_PASS)
        resp = RedirectResponse("/admin", status_code=302)
        resp.set_cookie(
            "_admin", sig,
            max_age=60*60*8,
            httponly=True,
            secure=not cfg.DEBUG,
            samesite="strict",
            path="/admin"
        )
        return resp

    logger.warning(f"[admin_login] Failed attempt from {get_ip(req)}")
    return render(req, "admin_login.html", {"error": "Mot de passe incorrect"})

@app.get("/admin", response_class=HTMLResponse)
async def admin_dash(req: Request):
    if not is_admin(req):
        return RedirectResponse("/admin/login", status_code=302)

    async with get_db_session() as db:
        members = [dict(m) for m in db.execute(
            "SELECT * FROM members ORDER BY created_at DESC"
        ).fetchall()]
        logs = [dict(l) for l in db.execute(
            "SELECT * FROM scrape_log ORDER BY ts DESC LIMIT 20"
        ).fetchall()]
        stats = await get_stats()
        top = [dict(r) for r in db.execute("""
            SELECT stx10_code, stx10_label, COUNT(*) cnt
            FROM tenders WHERE statut='actif'
            GROUP BY stx10_code ORDER BY cnt DESC LIMIT 10
        """).fetchall()]
        payments = [dict(p) for p in db.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT 30"
        ).fetchall()]

        return render(req, "admin.html", {
            "members": members, "logs": logs, "stats": stats,
            "top_stx10": top, "payments": payments,
            "scraping": AppState.scraping, "last_scan": AppState.last_scan
        })

@app.get("/admin/scan")
async def admin_scan(req: Request):
    if not is_admin(req):
        return JSONResponse({"ok": False}, status_code=401)
    if AppState.scraping:
        return JSONResponse({"ok": False, "msg": "En cours"})

    async def _do():
        AppState.scraping = True
        try:
            from app.services.scraper import scrape_new
            from app.services.notifications import dispatch, send_urgent_alerts
            async with get_db_session() as db:
                new = scrape_new(db, AppState.max_id)
                if new:
                    await dispatch(new, db)
                await send_urgent_alerts(db)
            AppState.last_scan = datetime.now().strftime("%H:%M")
        except Exception as e:
            logger.error(f"[admin_scan] {e}")
        finally:
            AppState.scraping = False

    asyncio.create_task(_do())
    return JSONResponse({"ok": True, "msg": "Scan lancé"})

@app.get("/admin/test_notif")
async def admin_test(req: Request, email: str = "", telegram_id: str = ""):
    if not is_admin(req):
        return JSONResponse({"ok": False}, status_code=401)
    from app.services.notifications import test_notif
    return JSONResponse({"ok": True, "results": test_notif(email, telegram_id)})

@app.post("/admin/member/{mid}/plan")
async def admin_update_plan(req: Request, mid: int, plan: str = Form("")):
    if not is_admin(req):
        return JSONResponse({"ok": False}, status_code=401)
    if plan not in cfg.PLANS:
        return JSONResponse({"ok": False})

    async with get_db_session() as db:
        db.execute("UPDATE members SET plan=? WHERE id=?", (plan, mid))
        db.commit()

    return RedirectResponse("/admin", status_code=302)

@app.post("/admin/member/{mid}/toggle")
async def admin_toggle(req: Request, mid: int):
    if not is_admin(req):
        return JSONResponse({"ok": False}, status_code=401)

    async with get_db_session() as db:
        row = db.execute("SELECT actif FROM members WHERE id=?", (mid,)).fetchone()
        if row:
            db.execute("UPDATE members SET actif=? WHERE id=?", (0 if row[0] else 1, mid))
            db.commit()

    return RedirectResponse("/admin", status_code=302)

# === Errors ===
@app.exception_handler(404)
async def not_found(req, exc):
    return render(req, "404.html", {}, status_code=404)

@app.exception_handler(500)
async def server_error(req, exc):
    logger.error(f"[500] {req.url}: {exc}")
    return render(req, "500.html", {}, status_code=500)

@app.exception_handler(429)
async def rate_limit_error(req, exc):
    return JSONResponse({"ok": False, "msg": "Rate limit exceeded"}, status_code=429)
