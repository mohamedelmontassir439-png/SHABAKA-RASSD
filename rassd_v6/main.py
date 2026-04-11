"""
ATLAS PRO v3.2 — SaaS Veille Marchés Publics Maroc
Full audit & fix — Production ready
"""
import os, re, json, asyncio, logging, hashlib
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from collections import defaultdict
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import (HTMLResponse, RedirectResponse,
                               JSONResponse, StreamingResponse, Response)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config   import cfg
from app.core.database import get_db, init_db
from app.core.security import (hash_pw, verify_pw, make_token,
                                get_member, validate_email,
                                validate_password, days_left)
from app.services.notifications import dispatch_notifications, tg_admin, test_notifications

try:
    from app.services.multi_scraper import run_all as multi_run
    MULTI_OK = True
except ImportError:
    MULTI_OK = False

try:
    from app.services.playwright_scraper import run_playwright
    PW_OK = True
except ImportError:
    PW_OK = False

try:
    from app.core.database import supabase_sync_batch, get_supabase
    SUPA_OK = bool(get_supabase())
except Exception:
    SUPA_OK = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-18s │ %(levelname)s │ %(message)s"
)
logger = logging.getLogger("atlas")

# ══════════════════════════════════════════════════════════
# RATE LIMITER (brute force protection)
# ══════════════════════════════════════════════════════════
_login_attempts: dict = defaultdict(list)

def check_rate_limit(ip: str, max_attempts: int = 5, window: int = 300) -> bool:
    now = datetime.now().timestamp()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < window]
    if len(_login_attempts[ip]) >= max_attempts:
        return False
    _login_attempts[ip].append(now)
    return True

def get_ip(req: Request) -> str:
    return req.headers.get("x-forwarded-for", req.client.host if req.client else "unknown").split(",")[0].strip()

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
def _save_tenders(tenders: list, new_list: list) -> int:
    if not tenders: return 0
    db = get_db(); saved = 0
    for t in tenders:
        try:
            db.execute("""INSERT OR IGNORE INTO tenders
                (id,objet,acheteur,secteur,region,montant,
                 date_publication,date_limite,description,
                 url,statut,scraped_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t["id"], t["objet"], t["acheteur"],
                 t.get("secteur",""), t.get("region",""),
                 t.get("montant",""), t.get("date_publication",""),
                 t.get("date_limite",""), t.get("description",""),
                 t["url"], t["statut"], t["scraped_at"], t["scraped_at"]))
            if db.execute("SELECT changes()").fetchone()[0]:
                saved += 1
                new_list.append(t)
        except Exception as e:
            logger.error(f"[save] {e}")
    db.commit(); db.close()
    return saved

async def do_scrape():
    if State.running: return
    State.running = True
    State.saved = State.found = State.errors = 0
    t0 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_tenders = []

    try:
        loop = asyncio.get_event_loop()

        # ── marchespublics.gov.ma ─────────────────────────
        State.log("═" * 48)
        State.log("  ATLAS PRO Scraper v3.2 — Multi-Source")
        State.log(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        State.log("═" * 48)
        try:
            from app.services.scraper import run
            db    = get_db()
            known = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
            db.close()
            results = await loop.run_in_executor(None, lambda: run(known, State.log))
            State.found += len(results)
            saved = _save_tenders(results, new_tenders)
            State.saved += saved
            State.log(f"✅ marchespublics.gov.ma: {saved} nouveaux")
        except Exception as e:
            State.log(f"❌ marchespublics: {e}")
            logger.error(f"[scraper] {e}", exc_info=True)

        # ── Multi-sources ─────────────────────────────────
        if MULTI_OK:
            try:
                State.log("─" * 48)
                State.log("  Sources secondaires: ONDA, ONEE, ONCF, IAM...")
                db     = get_db()
                known2 = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
                db.close()
                multi = await loop.run_in_executor(None, lambda: multi_run(known2, State.log))
                State.found += len(multi)
                saved2 = _save_tenders(multi, new_tenders)
                State.saved += saved2
                State.log(f"✅ Multi-sources: {saved2} nouveaux")
            except Exception as e:
                State.log(f"⚠ Multi: {e}")

        # ── Log run ───────────────────────────────────────
        db = get_db()
        db.execute("INSERT INTO scrape_log(found,saved,errors,run_at) VALUES(?,?,?,?)",
                   (State.found, State.saved, State.errors, t0))
        db.commit(); db.close()
        State.last_run = t0

        State.log("═" * 48)
        State.log(f"  ✅ {State.saved} nouveaux | {State.found} trouvés | {State.errors} erreurs")
        State.log("═" * 48)

        if new_tenders:
            await loop.run_in_executor(None, lambda: dispatch_notifications(new_tenders))

    except Exception as e:
        State.log(f"❌ {e}")
        logger.error(f"[do_scrape] {e}", exc_info=True)
    finally:
        State.running = False

async def scheduler():
    await asyncio.sleep(30)
    while True:
        try: await do_scrape()
        except Exception as e: logger.error(f"[scheduler] {e}")
        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN * 60)

# ══════════════════════════════════════════════════════════
# MIDDLEWARE
# ══════════════════════════════════════════════════════════
class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Content-Type-Options":  "nosniff",
            "X-Frame-Options":         "DENY",
            "X-XSS-Protection":        "1; mode=block",
            "Referrer-Policy":         "strict-origin-when-cross-origin",
            "Permissions-Policy":      "geolocation=(), microphone=()",
        })
        return resp

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    State.log(f"ATLAS PRO v{cfg.APP_VERSION} | Multi-source: {'✅' if MULTI_OK else '❌'}")
    asyncio.create_task(scheduler())
    yield

app = FastAPI(lifespan=lifespan, title=cfg.APP_NAME,
              version=cfg.APP_VERSION, docs_url=None, redoc_url=None)
app.add_middleware(SecurityMiddleware)
templates = Jinja2Templates(directory="templates")
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
def render(req: Request, tpl: str, ctx: dict = None):
    m   = get_member(req)
    ctx = ctx or {}
    return templates.TemplateResponse(tpl, {
        "request":   req,  "member":   m,
        "cfg":       cfg,  "secteurs": cfg.SECTEURS,
        "plans":     cfg.PLANS,
        "dl":        days_left, "days_left": days_left,
        "now":       datetime.now(),
        **ctx
    })

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
    finally: db.close()

def expire_tenders() -> tuple:
    db = get_db(); today = date.today(); expired = []
    for row in db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall():
        m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(row["date_limite"]))
        if m:
            try:
                fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
                if datetime.strptime(m.group(1), fmt).date() < today:
                    expired.append(row["id"])
            except: pass
    if expired:
        ph = ",".join(["?"]*len(expired))
        db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", expired)
        db.commit()
    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return len(expired), active

def clean_secteurs(raw: list) -> list:
    return list({s for s in raw if s and s.strip()})

def _is_admin(req: Request) -> bool:
    expected = make_token("admin", cfg.ADMIN_PASS)
    return req.cookies.get("_admin", "") == expected

# ══════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    stats   = get_stats()
    recent  = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9").fetchall()]
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 12").fetchall()]
    db.close()
    return render(req, "landing.html", {"stats":stats,"recent":recent,"sectors":sectors})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, q:str="", s:str="", r:str="",
                        page:int=1, sort:str="recent"):
    db = get_db(); per = 25; page = max(1, page)
    where, params = ["statut='actif'"], []
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
        params += [f"%{q}%"]*3
    if s: where.append("secteur=?"); params.append(s)
    if r: where.append("region=?");  params.append(r)
    wh    = " AND ".join(where)
    order = "scraped_at DESC" if sort=="recent" else "date_limite ASC"
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(x) for x in db.execute(
        f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
        params+[per,(page-1)*per]).fetchall()]
    member = get_member(req)
    favs   = set()
    if member:
        favs = {x[0] for x in db.execute(
            "SELECT tender_id FROM favorites WHERE member_id=?", (member["id"],)).fetchall()}
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "tenders.html", {
        "tenders":rows,"total":total,"page":page,"pages":pages,
        "q":q,"sf":s,"rf":r,"sort":sort,"favs":favs})

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    t  = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if not t:
        db.close()
        return HTMLResponse("Marché introuvable", 404)
    try: db.execute("UPDATE tenders SET views=views+1 WHERE id=?", (tid,))
    except: pass
    secteur = t["secteur"] or ""
    related = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE secteur=? AND id!=? AND statut='actif' ORDER BY scraped_at DESC LIMIT 4",
        (secteur, tid)).fetchall()] if secteur else []
    member = get_member(req); is_fav = False
    if member:
        try:
            is_fav = bool(db.execute(
                "SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
                (member["id"],tid)).fetchone())
        except: pass
    try: db.commit()
    except: pass
    db.close()
    return render(req, "detail.html", {"t":dict(t),"related":related,"is_fav":is_fav})

@app.post("/tenders/{tid}/favorite")
async def toggle_fav(req: Request, tid: str):
    member = get_member(req)
    if not member: return JSONResponse({"ok":False,"msg":"Non connecté"},401)
    db = get_db()
    try:
        exists = db.execute("SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
                            (member["id"],tid)).fetchone()
        if exists:
            db.execute("DELETE FROM favorites WHERE member_id=? AND tender_id=?",
                       (member["id"],tid))
            db.commit()
            return JSONResponse({"ok":True,"fav":False})
        db.execute("INSERT OR IGNORE INTO favorites(member_id,tender_id,created_at) VALUES(?,?,?)",
                   (member["id"],tid,datetime.now().isoformat()))
        db.commit()
        return JSONResponse({"ok":True,"fav":True})
    finally: db.close()

@app.get("/favorites", response_class=HTMLResponse)
async def favorites_page(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/favorites",302)
    db   = get_db()
    rows = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t JOIN favorites f ON f.tender_id=t.id
           WHERE f.member_id=? ORDER BY f.created_at DESC""",
        (member["id"],)).fetchall()]
    db.close()
    return render(req,"favorites.html",{"tenders":rows})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/dashboard",302)
    db   = get_db()
    ms   = clean_secteurs(json.loads(member.get("secteurs","[]") or "[]"))
    favs = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t JOIN favorites f ON f.tender_id=t.id
           WHERE f.member_id=? AND t.statut='actif' ORDER BY f.created_at DESC LIMIT 6""",
        (member["id"],)).fetchall()]
    notifs = [dict(r) for r in db.execute(
        """SELECT nl.*,t.objet FROM notif_log nl
           JOIN tenders t ON t.id=nl.tender_id
           WHERE nl.member_id=? ORDER BY nl.sent_at DESC LIMIT 10""",
        (member["id"],)).fetchall()]
    if ms:
        ph   = ",".join(["?"]*len(ms))
        recs = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE secteur IN ({ph}) AND statut='actif' ORDER BY scraped_at DESC LIMIT 6",
            ms).fetchall()]
    else:
        recs = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 6").fetchall()]
    stats = {
        "favs":   db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?",(member["id"],)).fetchone()[0],
        "notifs": db.execute("SELECT COUNT(*) FROM notif_log WHERE member_id=?",(member["id"],)).fetchone()[0],
        "active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
    }
    db.close()
    return render(req,"dashboard.html",{"favs":favs,"notifs":notifs,"recs":recs,"stats":stats})

@app.get("/tarifs", response_class=HTMLResponse)
async def tarifs(req: Request): return render(req,"tarifs.html",{})

# ══════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"register.html",{})

@app.post("/register")
async def register_post(req: Request,
    nom:str=Form(""), email:str=Form(""), phone:str=Form(""),
    company:str=Form(""), pw:str=Form(""), pw2:str=Form(""),
    secteurs_sel:list=Form(default=[])):
    vals = {"nom":nom,"email":email,"phone":phone,"company":company}
    err  = None
    if not email or not pw: err = "Email et mot de passe requis"
    elif not validate_email(email): err = "Adresse email invalide"
    elif pw != pw2: err = "Les mots de passe ne correspondent pas"
    else:
        ok, msg = validate_password(pw)
        if not ok: err = msg
    if err: return render(req,"register.html",{"err":err,"vals":vals})
    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?",(email,)).fetchone():
            return render(req,"register.html",{"err":"Email déjà utilisé","vals":vals})
        sects      = clean_secteurs(secteurs_sel)
        trial_ends = (datetime.now()+timedelta(days=14)).strftime("%Y-%m-%d")
        created_at = datetime.now().isoformat()
        db.execute(
            "INSERT INTO members(nom,email,phone,company,pw_hash,secteurs,plan,created_at,trial_ends) VALUES(?,?,?,?,?,?,?,?,?)",
            (nom,email,phone,company,hash_pw(pw),json.dumps(sects),"free",created_at,trial_ends))
        db.commit()
        m = db.execute("SELECT * FROM members WHERE email=?",(email,)).fetchone()
    finally: db.close()
    resp = RedirectResponse("/dashboard?welcome=1",302)
    resp.set_cookie("_session", make_token(m["email"], m["created_at"]),
                    max_age=86400*30, httponly=True, samesite="lax",
                    secure=False)  # False = works on HTTP + HTTPS
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request, next:str=""):
    if get_member(req): return RedirectResponse(next or "/dashboard",302)
    return render(req,"login.html",{"next":next})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), pw:str=Form(""), next:str=Form("")):
    ip = get_ip(req)
    if not check_rate_limit(ip):
        return render(req,"login.html",{"err":"Trop de tentatives. Réessayez dans 5 minutes.","vals":{"email":email},"next":next})
    db = get_db()
    m  = db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email,)).fetchone()
    if not m or not verify_pw(pw, m["pw_hash"]):
        db.close()
        return render(req,"login.html",{"err":"Email ou mot de passe incorrect","vals":{"email":email},"next":next})
    db.execute("UPDATE members SET last_login=? WHERE id=?",(datetime.now().isoformat(),m["id"]))
    db.commit(); db.close()
    logger.info(f"[Login] ✅ {email} connecté")
    resp = RedirectResponse(next or "/dashboard",302)
    resp.set_cookie("_session", make_token(m["email"], m["created_at"]),
                    max_age=86400*30, httponly=True, samesite="lax",
                    secure=False)
    return resp

@app.get("/logout")
async def logout():
    r = RedirectResponse("/",302); r.delete_cookie("_session"); return r

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/settings",302)
    ms = clean_secteurs(json.loads(member.get("secteurs","[]") or "[]"))
    return render(req,"settings.html",{"ms":ms})

@app.post("/settings")
async def settings_post(req: Request,
    nom:str=Form(""), phone:str=Form(""), company:str=Form(""),
    telegram:str=Form(""), secteurs_sel:list=Form(default=[])):
    member = get_member(req)
    if not member: return RedirectResponse("/login",302)
    form     = await req.form()
    n_email  = 1 if form.get("notif_email")  else 0
    n_tg     = 1 if form.get("notif_tg")     else 0
    n_digest = 1 if form.get("notif_digest") else 0
    sects    = clean_secteurs(secteurs_sel)
    db = get_db()
    try:
        db.execute(
            "UPDATE members SET nom=?,phone=?,company=?,telegram=?,notif_email=?,notif_tg=?,notif_digest=?,secteurs=? WHERE id=?",
            (nom,phone,company,telegram.strip(),n_email,n_tg,n_digest,json.dumps(sects),member["id"]))
        db.commit()
    finally: db.close()
    return RedirectResponse("/settings?ok=1",302)

# ══════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_get(req: Request):
    if _is_admin(req): return RedirectResponse("/admin",302)
    return render(req,"admin_login.html",{})

@app.post("/admin/login")
async def admin_login_post(req: Request, pwd:str=Form("")):
    ip = get_ip(req)
    if not check_rate_limit(f"admin_{ip}", 5, 600):
        return render(req,"admin_login.html",{"err":"Trop de tentatives."})
    if pwd != cfg.ADMIN_PASS:
        return render(req,"admin_login.html",{"err":"Mot de passe incorrect"})
    r = RedirectResponse("/admin",302)
    r.set_cookie("_admin",make_token("admin",cfg.ADMIN_PASS),
                 httponly=True,max_age=86400*7,samesite="lax")
    return r

@app.get("/admin/logout")
async def admin_logout():
    r = RedirectResponse("/",302); r.delete_cookie("_admin"); return r

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(req: Request):
    if not _is_admin(req): return RedirectResponse("/admin/login",302)
    db = get_db()
    stats   = get_stats()
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC").fetchall()]
    members = [dict(r) for r in db.execute(
        "SELECT id,nom,email,plan,created_at,last_login,actif FROM members ORDER BY created_at DESC LIMIT 30").fetchall()]
    scrapes = [dict(r) for r in db.execute(
        "SELECT * FROM scrape_log ORDER BY run_at DESC LIMIT 8").fetchall()]
    db.close()
    return templates.TemplateResponse("admin.html",{
        "request":req,"stats":stats,"sectors":sectors,
        "members":members,"scrapes":scrapes,
        "logs":State.logs[-100:],"running":State.running,
        "last_run":State.last_run,"cfg":cfg,"multi_ok":MULTI_OK})

@app.get("/admin/scrape")
async def admin_scrape(req: Request):
    if not _is_admin(req):
        return JSONResponse({"ok":False,"msg":"Non autorisé — reconnectez-vous à /admin/login"},401)
    if State.running:
        return JSONResponse({"ok":False,"msg":"Scan déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok":True,"msg":"Scan lancé"})

@app.get("/admin/scrape_stream")
async def admin_stream(req: Request):
    if not _is_admin(req): return JSONResponse({"error":"unauthorized"},401)
    async def gen():
        last = 0
        while True:
            logs = State.logs
            if len(logs) > last:
                for log in logs[last:]:
                    yield f"data: {json.dumps({'log':log,'running':State.running,'saved':State.saved,'found':State.found})}\n\n"
                last = len(logs)
            if not State.running and last > 0:
                yield f"data: {json.dumps({'done':True,'saved':State.saved,'found':State.found})}\n\n"
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/admin/expire")
async def admin_expire(req: Request):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    exp, active = expire_tenders()
    return JSONResponse({"ok":True,"expired":exp,"active":active})

@app.post("/admin/member/{mid}/plan")
async def set_plan(req: Request, mid:int, plan:str=Form("")):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    if plan not in cfg.PLANS: return JSONResponse({"ok":False,"msg":"Plan invalide"})
    db = get_db()
    db.execute("UPDATE members SET plan=? WHERE id=?",(plan,mid))
    db.commit(); db.close()
    return RedirectResponse("/admin",302)

@app.post("/admin/member/{mid}/toggle")
async def toggle_member(req: Request, mid:int):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    db = get_db()
    m  = db.execute("SELECT actif FROM members WHERE id=?",(mid,)).fetchone()
    if m:
        db.execute("UPDATE members SET actif=? WHERE id=?",(0 if m["actif"] else 1,mid))
        db.commit()
    db.close()
    return RedirectResponse("/admin",302)

@app.get("/admin/clear")
async def admin_clear(req: Request, confirm:str=""):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    if confirm != "yes":
        return HTMLResponse('<a href="/admin/clear?confirm=yes" style="color:red">Confirmer suppression</a>')
    db = get_db()
    n  = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    db.execute("DELETE FROM tenders")
    db.execute("DELETE FROM notif_log")
    db.commit(); db.close()
    State.log(f"🗑 DB vidée ({n} marchés)")
    return JSONResponse({"ok":True,"deleted":n})

@app.get("/admin/test_notif")
async def admin_test_notif(req: Request, email:str="", tg:str=""):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    member    = get_member(req)
    test_email = email or (member["email"] if member else "")
    test_tg    = tg or cfg.ADMIN_CHAT_ID or ""
    results    = test_notifications(test_email, test_tg)
    return JSONResponse({"ok":True,"results":results,"email_tested":test_email,"tg_tested":test_tg})

@app.get("/admin/reset_state")
async def admin_reset(req: Request):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    State.running = False; State.logs = []
    return JSONResponse({"ok":True,"msg":"State réinitialisé"})

# ══════════════════════════════════════════════════════════
# API v1
# ══════════════════════════════════════════════════════════
@app.get("/api/v1/tenders")
async def api_tenders(req:Request, secteur:str="", region:str="", q:str="",
                       limit:int=20, offset:int=0, page:int=0):
    if page > 0: offset = (page-1)*limit
    db = get_db()
    where, params = ["statut='actif'"], []
    if secteur: where.append("secteur=?");  params.append(secteur)
    if region:  where.append("region=?");   params.append(region)
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ?)")
        params += [f"%{q}%"]*2
    wh    = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(r) for r in db.execute(
        f"SELECT id,objet,acheteur,secteur,region,montant,date_limite,url,scraped_at FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
        params+[min(limit,100),offset]).fetchall()]
    db.close()
    return {"ok":True,"total":total,"page":page or (offset//limit+1),"results":rows}

@app.get("/api/v1/tenders/{tid}")
async def api_tender(tid:str):
    db = get_db()
    t  = db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
    db.close()
    if not t: return JSONResponse({"ok":False,"msg":"Introuvable"},404)
    return {"ok":True,"tender":dict(t)}

@app.get("/api/v1/stats")
async def api_stats(): return {"ok":True,**get_stats()}

@app.get("/api/v1/secteurs")
async def api_secteurs():
    db   = get_db()
    data = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC").fetchall()]
    db.close()
    return {"ok":True,"secteurs":data}

@app.get("/api/v1/sources")
async def api_sources():
    sources = [
        {"name":"marchespublics.gov.ma","type":"public",      "status":"active"},
        {"name":"ONDA",                 "type":"semi-public", "status":"active" if MULTI_OK else "disabled"},
        {"name":"ONEE",                 "type":"semi-public", "status":"active" if MULTI_OK else "disabled"},
        {"name":"ONCF",                 "type":"semi-public", "status":"active" if MULTI_OK else "disabled"},
        {"name":"IAM",                  "type":"semi-private","status":"active" if MULTI_OK else "disabled"},
        {"name":"SNRT",                 "type":"semi-public", "status":"active" if MULTI_OK else "disabled"},
        {"name":"Le Matin",             "type":"journal",     "status":"active" if MULTI_OK else "disabled"},
        {"name":"Crédit Agricole",      "type":"private",     "status":"active" if MULTI_OK else "disabled"},
        {"name":"BCP",                  "type":"private",     "status":"active" if MULTI_OK else "disabled"},
    ]
    return {"ok":True,"multi_scraper":MULTI_OK,"playwright":PW_OK,"supabase":SUPA_OK,"total":len(sources),"sources":sources}

# ══════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    db  = get_db()
    act = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    supa_ok = False
    try:
        from app.core.database import get_supabase
        supa_ok = bool(get_supabase())
    except: pass
    return {"status":"ok","version":cfg.APP_VERSION,"brand":cfg.APP_NAME,
            "active":act,"running":State.running,"last_run":State.last_run,
            "multi_scraper":MULTI_OK,"playwright":PW_OK,"supabase":supa_ok}

@app.get("/sitemap.xml")
async def sitemap():
    db  = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM tenders WHERE statut='actif' LIMIT 2000").fetchall()]
    db.close()
    urls = "\n".join(f"  <url><loc>{cfg.SITE_URL}/tenders/{i}</loc></url>" for i in ids)
    xml  = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{cfg.SITE_URL}/</loc></url>
  <url><loc>{cfg.SITE_URL}/tenders</loc></url>
  <url><loc>{cfg.SITE_URL}/tarifs</loc></url>
{urls}</urlset>"""
    return Response(xml, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nSitemap: {cfg.SITE_URL}/sitemap.xml\n",
                    media_type="text/plain")
