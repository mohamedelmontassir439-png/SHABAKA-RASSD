"""
SOURCE v1.0 — Application principale FINALE
=========================================
✅ Toutes les routes testées
✅ Filtres Jinja2 complets (tojson, from_json, urlencode)
✅ Gestion d'erreurs robuste
✅ Rate limiting
✅ Auth sécurisée
✅ STX10 sémantique
✅ Notifications TG + Email + WA
✅ Admin panel
✅ Scraper marchespublics.gov.ma UNIQUEMENT
"""
import asyncio, json, logging, os, re, urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from app.core.config   import cfg
from app.core.database import get_db, init_db
from app.core.security import (
    hash_pw, verify_pw, make_session_token, make_token,
    get_member, is_admin, validate_email, validate_password,
    days_left, is_plan_ok
)
from app.core.stx10 import classify, STX10, STX10_AR, top3
from app.services.notifications import tg_admin, test_notif, dispatch, wa_link

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("source")

# ── Rate Limiter ──────────────────────────────────────────
_rl: dict = defaultdict(list)
def rate_ok(ip: str, limit: int = 60, win: int = 60) -> bool:
    now = datetime.now().timestamp()
    _rl[ip] = [t for t in _rl[ip] if now - t < win]
    if len(_rl[ip]) >= limit: return False
    _rl[ip].append(now); return True

def get_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (req.client.host or "?")

# ── App State ─────────────────────────────────────────────
class State:
    scraping  = False
    last_scan = "—"
    max_id    = 0

# ── Scheduler ─────────────────────────────────────────────
async def _scheduler():
    await asyncio.sleep(20)
    while True:
        try:
            State.scraping = True
            from app.services.scraper import scrape_new
            db = get_db()
            new = scrape_new(db, State.max_id)
            if new:
                State.max_id = max(State.max_id,
                    max((int(t["id"].replace("bdc_","")) for t in new if t.get("id","").startswith("bdc_")), default=State.max_id))
                dispatch(new, db)
            db.close()
            State.last_scan = datetime.now().strftime("%H:%M")
        except Exception as e:
            logger.error(f"[Scheduler] {e}", exc_info=True)
        finally:
            State.scraping = False
        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN * 60)

# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("=" * 55)
    logger.info(f"  SOURCE v{cfg.APP_VERSION}")
    logger.info(f"  URL:     {cfg.SITE_URL}")
    logger.info(f"  DB:      {cfg.DB_PATH}")
    logger.info(f"  Scan:    toutes les {cfg.SCAN_INTERVAL_MIN} min")
    logger.info(f"  TG:      {'✅' if cfg.TELEGRAM_BOT else '❌ non configuré'}")
    logger.info(f"  Email:   {'✅ Brevo' if cfg.BREVO_KEY else ('✅ Gmail' if cfg.GMAIL_USER else '❌')}")
    logger.info(f"  Groq AI: {'✅' if cfg.GROQ_API_KEY else '❌ fallback hybride'}")
    logger.info(f"  Key:     {'✅' if cfg.SECRET_KEY else '⚠️  DÉFINIR SECRET_KEY!'}")
    logger.info("=" * 55)
    try:
        tg_admin(f"🚀 SOURCE v{cfg.APP_VERSION} démarré\n🌐 {cfg.SITE_URL}")
    except: pass
    asyncio.create_task(_scheduler())
    yield
    logger.info("SOURCE arrêté proprement")

# ── App Init ──────────────────────────────────────────────
app = FastAPI(
    title="SOURCE",
    version=cfg.APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

templates = Jinja2Templates(directory="templates")
os.makedirs("static", exist_ok=True)
os.makedirs("data", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Jinja2 Filters ────────────────────────────────────────
def _from_json(s):
    try: return json.loads(s or "[]")
    except: return []

def _to_json(v):
    try: return json.dumps(v, ensure_ascii=False)
    except: return "[]"

templates.env.filters["from_json"] = _from_json
templates.env.filters["tojson"]    = _to_json
templates.env.filters["urlencode"] = urllib.parse.quote

# ── Helpers ───────────────────────────────────────────────
def render(req: Request, tpl: str, ctx: dict = None, status_code: int = 200) -> HTMLResponse:
    ctx = ctx or {}
    ctx.setdefault("request",   req)
    ctx.setdefault("member",    get_member(req))
    ctx.setdefault("cfg",       cfg)
    ctx.setdefault("now",       datetime.now())
    ctx.setdefault("days_left", days_left)
    ctx.setdefault("STX10",     STX10)
    ctx.setdefault("STX10_AR",  STX10_AR)
    return templates.TemplateResponse(tpl, ctx, status_code=status_code)

def get_stats() -> dict:
    db = get_db()
    try:
        total   = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        today   = db.execute("SELECT COUNT(*) FROM tenders WHERE DATE(scraped_at)=DATE('now')").fetchone()[0]
        members = db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0]
        return {"tenders": total, "today": today, "members": members}
    except Exception as e:
        logger.error(f"[get_stats] {e}")
        return {"tenders": 0, "today": 0, "members": 0}
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# LANDING
# ══════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def landing(req: Request):
    if get_member(req):
        return RedirectResponse("/dashboard", 302)
    stats = get_stats()
    return render(req, "landing.html", {"stats": stats})

# ══════════════════════════════════════════════════════════
# AUTH — Register
# ══════════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def register_page(req: Request):
    if get_member(req): return RedirectResponse("/dashboard", 302)
    return render(req, "register.html", {"error": "", "success": ""})

@app.post("/register", response_class=HTMLResponse)
async def register_post(
    req: Request,
    nom: str      = Form(""),
    email: str    = Form(""),
    password: str = Form(""),
    confirm: str  = Form(""),
    lang: str     = Form("fr"),
):
    nom   = nom.strip()
    email = email.strip().lower()
    error = ""

    if len(nom) < 2:
        error = "Nom trop court." if lang=="fr" else "الاسم قصير جداً."
    elif not validate_email(email):
        error = "Email invalide." if lang=="fr" else "البريد غير صالح."
    elif password != confirm:
        error = "Mots de passe différents." if lang=="fr" else "كلمات المرور غير متطابقة."
    else:
        ok, msg = validate_password(password)
        if not ok: error = msg

    if error:
        return render(req, "register.html", {"error": error, "success": ""})

    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
            return render(req, "register.html", {
                "error": "Email déjà utilisé." if lang=="fr" else "البريد مستخدم بالفعل.",
                "success": ""
            })
        token = make_session_token()
        db.execute(
            "INSERT INTO members (nom,email,password_hash,plan,actif,session_token,created_at,lang,onboarded) "
            "VALUES (?,?,?,'free',1,?,?,?,0)",
            (nom, email, hash_pw(password), token, datetime.now().isoformat(), lang)
        )
        db.commit()
        try: tg_admin(f"👤 Nouveau membre: <b>{nom}</b>\n📧 {email}")
        except: pass
        resp = RedirectResponse("/onboarding", 302)
        resp.set_cookie("_session", token, max_age=60*60*24*30, httponly=True, samesite="lax")
        return resp
    except Exception as e:
        logger.error(f"[register] {e}")
        return render(req, "register.html", {"error": "Erreur serveur.", "success": ""})
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# AUTH — Login
# ══════════════════════════════════════════════════════════
@app.get("/login", response_class=HTMLResponse)
async def login_page(req: Request, next: str = "/dashboard"):
    if get_member(req): return RedirectResponse(next or "/dashboard", 302)
    return render(req, "login.html", {"error": "", "next": next})

@app.post("/login", response_class=HTMLResponse)
async def login_post(
    req: Request,
    email: str    = Form(""),
    password: str = Form(""),
    next_url: str = Form("/dashboard"),
    lang: str     = Form("fr"),
):
    ip = get_ip(req)
    if not rate_ok(ip, limit=10, win=60):
        return render(req, "login.html", {
            "error": "Trop de tentatives. Attendez 1 minute." if lang=="fr" else "محاولات كثيرة جداً.",
            "next": next_url
        })
    email = email.strip().lower()
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM members WHERE email=? AND actif=1", (email,)
        ).fetchone()
        if not row or not verify_pw(password, row["password_hash"]):
            return render(req, "login.html", {
                "error": "Email ou mot de passe incorrect." if lang=="fr" else "بيانات الدخول خاطئة.",
                "next": next_url
            })
        token = make_session_token()
        db.execute("UPDATE members SET session_token=? WHERE id=?", (token, row["id"]))
        db.commit()
        resp = RedirectResponse(next_url or "/dashboard", 302)
        resp.set_cookie("_session", token, max_age=60*60*24*30, httponly=True, samesite="lax")
        return resp
    finally:
        db.close()

@app.get("/logout")
async def logout(req: Request):
    m = get_member(req)
    if m:
        db = get_db()
        db.execute("UPDATE members SET session_token='' WHERE id=?", (m["id"],))
        db.commit(); db.close()
    resp = RedirectResponse("/", 302)
    resp.delete_cookie("_session")
    return resp

# ══════════════════════════════════════════════════════════
# ONBOARDING
# ══════════════════════════════════════════════════════════
@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login", 302)
    if m.get("onboarded"): return RedirectResponse("/dashboard", 302)
    return render(req, "onboarding.html", {"lang": m.get("lang","fr")})

@app.post("/onboarding")
async def onboarding_post(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login", 302)
    form = await req.form()
    codes   = list(set(c for c in form.getlist("stx10_codes") if c in STX10))
    regions = list(set(r for r in form.getlist("regions") if r))
    lang    = form.get("lang", m.get("lang","fr"))
    db = get_db()
    try:
        db.execute(
            "UPDATE members SET stx10_codes=?,regions=?,onboarded=1,lang=? WHERE id=?",
            (json.dumps(codes), json.dumps(regions), lang, m["id"])
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/dashboard", 302)

# ══════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login?next=/dashboard", 302)
    if not m.get("onboarded"): return RedirectResponse("/onboarding", 302)

    db = get_db()
    try:
        stats = get_stats()
        codes = json.loads(m.get("stx10_codes","[]") or "[]")

        # Alertes pour ce membre
        alerts_count = 0
        matched = []
        if codes:
            phs = ",".join("?"*len(codes))
            alerts_count = db.execute(
                f"SELECT COUNT(*) FROM tenders WHERE statut='actif' AND stx10_code IN ({phs})",
                codes
            ).fetchone()[0]
            matched = [dict(r) for r in db.execute(
                f"SELECT * FROM tenders WHERE statut='actif' AND stx10_code IN ({phs}) "
                f"ORDER BY scraped_at DESC LIMIT 8", codes
            ).fetchall()]

        # Favoris
        favs = db.execute(
            "SELECT COUNT(*) FROM favorites WHERE member_id=?", (m["id"],)
        ).fetchone()[0]

        # Échéances < 7j
        all_dl = db.execute(
            "SELECT date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
        ).fetchall()
        soon = sum(1 for r in all_dl
                   if 0 <= days_left(r["date_limite"])[0] <= 7)

        # Top STX10
        top_stx10 = [dict(r) for r in db.execute(
            "SELECT stx10_code, stx10_label, COUNT(*) cnt FROM tenders "
            "WHERE statut='actif' AND stx10_code!='' "
            "GROUP BY stx10_code ORDER BY cnt DESC LIMIT 7"
        ).fetchall()]

        # Derniers marchés
        recent = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' "
            "ORDER BY scraped_at DESC LIMIT 15"
        ).fetchall()]

        return render(req, "dashboard.html", {
            "stats":        stats,
            "alerts_count": alerts_count,
            "favs":         favs,
            "soon":         soon,
            "top_stx10":    top_stx10,
            "recent":       recent,
            "matched":      matched,
            "scraping":     State.scraping,
            "last_scan":    State.last_scan,
        })
    except Exception as e:
        logger.error(f"[dashboard] {e}", exc_info=True)
        return render(req, "dashboard.html", {
            "stats": get_stats(), "alerts_count": 0, "favs": 0,
            "soon": 0, "top_stx10": [], "recent": [], "matched": [],
            "scraping": False, "last_scan": "—",
        })
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# TENDERS
# ══════════════════════════════════════════════════════════
@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(
    req: Request, q: str = "", stx10: str = "",
    region: str = "", page: int = 1,
):
    m = get_member(req)
    if not m: return RedirectResponse("/login?next=/tenders", 302)

    PER = 20 if is_plan_ok(m,"unlimited") else 10
    if page > 1 and not is_plan_ok(m,"unlimited"):
        return RedirectResponse("/tarifs?upgrade=1", 302)
    offset = (page - 1) * PER

    db = get_db()
    try:
        where, params = ["statut='actif'"], []
        if q:
            where.append("(objet LIKE ? OR acheteur LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if stx10:
            where.append("stx10_code=?"); params.append(stx10)
        if region:
            where.append("region LIKE ?"); params.append(f"%{region}%")

        wh    = " AND ".join(where)
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
        rows  = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
            params + [PER, offset]
        ).fetchall()]

        regions = [r[0] for r in db.execute(
            "SELECT DISTINCT region FROM tenders WHERE statut='actif' AND region!='' ORDER BY region"
        ).fetchall()]
        stx10s = [r[0] for r in db.execute(
            "SELECT DISTINCT stx10_code FROM tenders WHERE statut='actif' AND stx10_code!=''"
        ).fetchall()]

        return render(req, "tenders.html", {
            "tenders": rows, "total": total,
            "page": page, "pages": max(1, (total+PER-1)//PER),
            "q": q, "stx10": stx10, "region": region,
            "regions": regions, "stx10_db": stx10s,
        })
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# TENDER DETAIL
# ══════════════════════════════════════════════════════════
@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    m = get_member(req)
    if not m: return RedirectResponse(f"/login?next=/tenders/{tid}", 302)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not row: return render(req, "404.html", {}, 404)
        t = dict(row)
        n, dl_label = days_left(t.get("date_limite",""))
        similar = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE stx10_code=? AND id!=? AND statut='actif' "
            "ORDER BY scraped_at DESC LIMIT 4",
            (t.get("stx10_code",""), tid)
        ).fetchall()]
        is_fav = bool(db.execute(
            "SELECT id FROM favorites WHERE member_id=? AND tender_id=?", (m["id"],tid)
        ).fetchone())
        wa = ""
        if m.get("whatsapp"):
            try: wa = wa_link(m["whatsapp"], t, m.get("lang","fr"))
            except: pass
        return render(req, "detail.html", {
            "t": t, "dl": n, "dl_label": dl_label,
            "similar": similar, "is_fav": is_fav, "wa": wa,
        })
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# FAVORITES
# ══════════════════════════════════════════════════════════
@app.post("/favorites/{tid}")
async def toggle_fav(req: Request, tid: str):
    m = get_member(req)
    if not m: return JSONResponse({"ok": False, "msg": "Auth requise"}, 401)
    db = get_db()
    try:
        ex = db.execute(
            "SELECT id FROM favorites WHERE member_id=? AND tender_id=?", (m["id"],tid)
        ).fetchone()
        if ex:
            db.execute("DELETE FROM favorites WHERE member_id=? AND tender_id=?", (m["id"],tid))
            db.commit()
            return {"ok": True, "action": "removed"}
        db.execute(
            "INSERT OR IGNORE INTO favorites(member_id,tender_id,added_at) VALUES(?,?,?)",
            (m["id"], tid, datetime.now().isoformat())
        )
        db.commit()
        return {"ok": True, "action": "added"}
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login?next=/settings", 302)
    codes   = json.loads(m.get("stx10_codes","[]") or "[]")
    regions = json.loads(m.get("regions","[]") or "[]")
    saved   = req.query_params.get("saved","")
    return render(req, "settings.html", {
        "member_codes": codes, "member_regions": regions, "saved": saved
    })

@app.post("/settings")
async def settings_post(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login", 302)
    form = await req.form()
    codes   = list(set(c for c in form.getlist("stx10_codes") if c in STX10))
    regions = list(set(r for r in form.getlist("regions") if r))
    tg      = form.get("telegram","").strip()
    wa      = form.get("whatsapp","").strip()
    notif_tg    = 1 if form.get("notif_tg") else 0
    notif_email = 1 if form.get("notif_email") else 0
    notif_wa    = 1 if form.get("notif_wa") else 0
    lang        = form.get("lang", m.get("lang","fr"))
    db = get_db()
    try:
        db.execute(
            "UPDATE members SET stx10_codes=?,regions=?,telegram=?,whatsapp=?,"
            "notif_tg=?,notif_email=?,notif_wa=?,lang=? WHERE id=?",
            (json.dumps(codes), json.dumps(regions), tg, wa,
             notif_tg, notif_email, notif_wa, lang, m["id"])
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/settings?saved=1", 302)

# ══════════════════════════════════════════════════════════
# TARIFS
# ══════════════════════════════════════════════════════════
@app.get("/tarifs", response_class=HTMLResponse)
async def tarifs_page(req: Request):
    return render(req, "tarifs.html", {})

@app.post("/tarifs/request")
async def tarifs_request(
    req: Request,
    plan: str = Form("essentiel"),
    nom: str  = Form(""),
    email: str= Form(""),
):
    m    = get_member(req)
    name = m.get("nom","") if m else nom.strip()
    mail = m.get("email","") if m else email.strip()
    db = get_db()
    try:
        if m:
            db.execute(
                "INSERT INTO payments(member_id,plan,status,amount,created_at) VALUES(?,?,?,?,?)",
                (m["id"], plan, "pending", cfg.PLANS.get(plan,{}).get("price",0), datetime.now().isoformat())
            )
            db.commit()
        try:
            tg_admin(f"💳 <b>Demande {plan.upper()}</b>\n👤 {name}\n📧 {mail}")
        except: pass
    finally:
        db.close()
    msg = f"Bonjour, je veux activer le plan {plan.upper()} sur SOURCE. Nom: {name}"
    url = f"https://wa.me/{cfg.PAYMENT_PHONE}?text={urllib.parse.quote(msg)}"
    return RedirectResponse(url, 302)

# ══════════════════════════════════════════════════════════
# AI CHAT
# ══════════════════════════════════════════════════════════
@app.get("/ai/chat", response_class=HTMLResponse)
async def ai_chat_page(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login?next=/ai/chat", 302)
    return render(req, "ai_chat.html", {"ai_ok": bool(cfg.GROQ_API_KEY)})

@app.get("/api/ai/chat")
async def api_ai_chat(req: Request, q: str = ""):
    m = get_member(req)
    if not m: return JSONResponse({"ok": False, "msg": "Auth requise"}, 401)
    if not q.strip(): return JSONResponse({"ok": False, "msg": "Question vide"})
    if not cfg.GROQ_API_KEY: return JSONResponse({"ok": False, "msg": "IA non configurée"})
    try:
        import requests as rq
        stats = get_stats()
        lang  = m.get("lang","fr")
        system = (
            f"Tu es l'assistant SOURCE, expert marchés publics marocains. "
            f"Marchés actifs: {stats['tenders']} | Plan: {m.get('plan','free')}. "
            f"{'Réponds en arabe professionnel.' if lang=='ar' else 'Réponds en français, concis et pratique.'} "
            f"Max 3 paragraphes."
        )
        r = rq.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
            json={"model": cfg.AI_MODEL, "max_tokens": 400,
                  "messages": [{"role":"system","content":system},
                                {"role":"user","content":q}],
                  "temperature": 0.5},
            timeout=15
        )
        if r.status_code == 200:
            return {"ok": True, "answer": r.json()["choices"][0]["message"]["content"]}
        return JSONResponse({"ok": False, "msg": f"IA erreur {r.status_code}"})
    except Exception as e:
        return JSONResponse({"ok": False, "msg": str(e)[:80]})

@app.get("/api/ai/summarize/{tid}")
async def api_ai_summarize(req: Request, tid: str):
    m = get_member(req)
    if not m: return JSONResponse({"ok": False}, 401)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not row: return JSONResponse({"ok": False, "msg": "Introuvable"})
        t = dict(row)
        if t.get("ai_summary"):
            return {"ok": True, "summary": t["ai_summary"]}
        if not cfg.GROQ_API_KEY:
            return JSONResponse({"ok": False, "msg": "IA non configurée"})
        import requests as rq
        lang = m.get("lang","fr")
        prompt = (
            f"Résume ce marché public marocain en 3 points clés "
            f"{'en arabe' if lang=='ar' else 'en français'} (max 80 mots):\n"
            f"1. Ce que demande exactement ce marché\n"
            f"2. Profil entreprise idéal\n"
            f"3. Points d'attention (délai, budget)\n\n"
            f"Marché: {t['objet'][:400]}\n"
            f"Acheteur: {t.get('acheteur','')}\n"
            f"Délai: {t.get('date_limite','')}"
        )
        r = rq.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
            json={"model": cfg.AI_MODEL, "max_tokens": 200,
                  "messages": [{"role":"user","content":prompt}]},
            timeout=12
        )
        if r.status_code == 200:
            summary = r.json()["choices"][0]["message"]["content"]
            try:
                db.execute("UPDATE tenders SET ai_summary=? WHERE id=?", (summary, tid))
                db.commit()
            except: pass
            return {"ok": True, "summary": summary}
        return JSONResponse({"ok": False, "msg": "IA indisponible"})
    finally:
        db.close()

# ══════════════════════════════════════════════════════════
# STX10 CLASSIFY API
# ══════════════════════════════════════════════════════════
@app.get("/api/stx10/classify")
async def api_classify(req: Request, text: str = ""):
    m = get_member(req)
    if not m: return JSONResponse({"ok": False}, 401)
    if not text.strip(): return JSONResponse({"ok": False, "msg": "Texte vide"})
    result = classify(text)
    t3     = top3(text)
    return {"ok": True, "primary": result, "top3": t3}

# ══════════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════════
@app.get("/api/v1/tenders")
async def api_tenders(
    req: Request,
    q: str = "", stx10: str = "",
    limit: int = 20, page: int = 1,
):
    if not rate_ok(get_ip(req)):
        return JSONResponse({"ok": False, "msg": "Rate limit (60/min)"}, 429)
    m = get_member(req)
    if not m: return JSONResponse({"ok": False, "msg": "Auth requise"}, 401)
    if not is_plan_ok(m,"api"):
        return JSONResponse({"ok": False, "msg": "API réservée au plan Pro"}, 403)
    offset = (page-1)*limit
    db = get_db()
    try:
        where, params = ["statut='actif'"], []
        if q: where.append("objet LIKE ?"); params.append(f"%{q}%")
        if stx10: where.append("stx10_code=?"); params.append(stx10)
        wh    = " AND ".join(where)
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
        rows  = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
            params + [min(limit,100), offset]
        ).fetchall()]
        return {"ok": True, "total": total, "page": page, "tenders": rows}
    finally:
        db.close()

@app.get("/api/v1/stats")
async def api_stats(req: Request):
    m = get_member(req)
    if not m: return JSONResponse({"ok": False}, 401)
    return {"ok": True, **get_stats(),
            "scraping": State.scraping, "last_scan": State.last_scan}

# ══════════════════════════════════════════════════════════
# EXPORT CSV
# ══════════════════════════════════════════════════════════
@app.get("/export/csv")
async def export_csv(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login", 302)
    if not is_plan_ok(m,"api"): return RedirectResponse("/tarifs?upgrade=1", 302)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT objet,acheteur,stx10_code,stx10_label,region,montant,"
            "date_publication,date_limite,url FROM tenders "
            "WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 2000"
        ).fetchall()
    finally:
        db.close()
    import csv, io
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Objet","Acheteur","Code STX10","Libellé STX10","Région","Montant",
                "Date Publication","Date Limite","URL"])
    for r in rows: w.writerow(list(r))
    fn = f"source_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fn}"}
    )

# ══════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(req: Request):
    if is_admin(req): return RedirectResponse("/admin", 302)
    return render(req, "admin_login.html", {"error": ""})

@app.post("/admin/login")
async def admin_login_post(req: Request, password: str = Form("")):
    if password == cfg.ADMIN_PASS:
        token = make_token("admin", cfg.ADMIN_PASS)
        resp  = RedirectResponse("/admin", 302)
        resp.set_cookie("_admin", token, max_age=60*60*8, httponly=True)
        return resp
    return render(req, "admin_login.html", {"error": "Mot de passe incorrect"})

@app.get("/admin", response_class=HTMLResponse)
async def admin_dash(req: Request):
    if not is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    try:
        members  = [dict(m) for m in db.execute("SELECT * FROM members ORDER BY created_at DESC").fetchall()]
        logs     = [dict(l) for l in db.execute("SELECT * FROM scrape_log ORDER BY ts DESC LIMIT 20").fetchall()]
        stats    = get_stats()
        top      = [dict(r) for r in db.execute(
            "SELECT stx10_code,stx10_label,COUNT(*) cnt FROM tenders "
            "WHERE statut='actif' GROUP BY stx10_code ORDER BY cnt DESC LIMIT 10"
        ).fetchall()]
        payments = [dict(p) for p in db.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT 30"
        ).fetchall()]
        return render(req, "admin.html", {
            "members": members, "logs": logs, "stats": stats,
            "top_stx10": top, "payments": payments,
            "scraping": State.scraping, "last_scan": State.last_scan,
        })
    finally:
        db.close()

@app.get("/admin/scan")
async def admin_scan(req: Request):
    if not is_admin(req): return JSONResponse({"ok": False}, 401)
    if State.scraping: return JSONResponse({"ok": False, "msg": "Scan déjà en cours"})
    async def _do():
        State.scraping = True
        try:
            from app.services.scraper import scrape_new
            db = get_db()
            new = scrape_new(db, State.max_id)
            if new: dispatch(new, db)
            db.close()
            State.last_scan = datetime.now().strftime("%H:%M")
        finally:
            State.scraping = False
    asyncio.create_task(_do())
    return JSONResponse({"ok": True, "msg": "Scan lancé en arrière-plan"})

@app.get("/admin/test_notif")
async def admin_test(req: Request, email: str = "", telegram_id: str = ""):
    if not is_admin(req): return JSONResponse({"ok": False}, 401)
    results = test_notif(email, telegram_id)
    return JSONResponse({"ok": True, "results": results})

@app.post("/admin/member/{mid}/plan")
async def admin_update_plan(req: Request, mid: int, plan: str = Form("")):
    if not is_admin(req): return JSONResponse({"ok": False}, 401)
    if plan not in cfg.PLANS: return JSONResponse({"ok": False, "msg": "Plan invalide"})
    db = get_db()
    try:
        db.execute("UPDATE members SET plan=? WHERE id=?", (plan, mid))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", 302)

@app.post("/admin/member/{mid}/toggle")
async def admin_toggle(req: Request, mid: int):
    if not is_admin(req): return JSONResponse({"ok": False}, 401)
    db = get_db()
    try:
        row = db.execute("SELECT actif FROM members WHERE id=?", (mid,)).fetchone()
        if row:
            db.execute("UPDATE members SET actif=? WHERE id=?", (0 if row[0] else 1, mid))
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", 302)

# ══════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════
@app.exception_handler(404)
async def not_found(req: Request, exc):
    return render(req, "404.html", {}, 404)

@app.exception_handler(500)
async def server_error(req: Request, exc):
    logger.error(f"[500] {req.url}: {exc}")
    return render(req, "404.html", {}, 500)
