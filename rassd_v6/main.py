"""RASSD v3.0 — Production SaaS"""
import os, re, json, asyncio, logging
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config   import cfg
from app.core.database import get_db, init_db
from app.core.security import (hash_pw, verify_pw, make_token, make_random_token,
                                get_member, validate_email, validate_password,
                                is_plan_allowed, days_left)
from app.services.notifications import dispatch_notifications, tg_admin, email_send, build_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("rassd")

# ═══════════════════════════════════════════════════════
# SCRAPER STATE
# ═══════════════════════════════════════════════════════
class State:
    running = False
    saved   = 0
    found   = 0
    errors  = 0
    last_run = ""
    logs    = []

    @classmethod
    def log(cls, msg: str):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.logs.append(entry)
        logger.info(msg)
        if len(cls.logs) > 600: cls.logs = cls.logs[-500:]


# ═══════════════════════════════════════════════════════
# SCRAPER RUNNER
# ═══════════════════════════════════════════════════════
async def do_scrape():
    if State.running: return
    State.running = True
    State.saved = State.found = State.errors = 0
    State.log("Scan lancé")
    try:
        from app.services.scraper import run
        db = get_db()
        known = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
        db.close()
        loop = asyncio.get_event_loop()
        tenders = await loop.run_in_executor(None, lambda: run(known, State.log))
        State.found = len(tenders)
        db = get_db(); new = []
        t0 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in tenders:
            try:
                db.execute("""INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,secteur,region,montant,date_publication,
                     date_limite,description,url,statut,scraped_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (t["id"],t["objet"],t["acheteur"],t["secteur"],t.get("region",""),
                     t.get("montant",""),t.get("date_publication",""),t.get("date_limite",""),
                     t.get("description",""),t["url"],t["statut"],t["scraped_at"],t["updated_at"]))
                if db.execute("SELECT changes()").fetchone()[0]:
                    State.saved += 1; new.append(t)
            except Exception as e:
                State.errors += 1; logger.error(f"[save] {e}")
        db.execute("INSERT INTO scrape_log(found,saved,errors,run_at) VALUES(?,?,?,?)",
                   (State.found, State.saved, State.errors, t0))
        db.commit(); db.close()
        State.last_run = t0
        State.log(f"✅ {State.saved} nouveaux marchés sauvegardés")
        if new:
            await loop.run_in_executor(None, lambda: dispatch_notifications(new))
    except Exception as e:
        State.log(f"❌ {e}"); logger.error(f"[scrape] {e}")
    finally:
        State.running = False

async def scheduler():
    await asyncio.sleep(20)
    while True:
        try: await do_scrape()
        except: pass
        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN * 60)

# ═══════════════════════════════════════════════════════
# MIDDLEWARE
# ═══════════════════════════════════════════════════════
class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        })
        return resp

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    State.log(f"RASSD v{cfg.APP_VERSION} démarré")
    asyncio.create_task(scheduler())
    yield

app = FastAPI(lifespan=lifespan, title=cfg.APP_NAME, version=cfg.APP_VERSION, docs_url=None, redoc_url=None)
app.add_middleware(SecurityHeaders)
templates = Jinja2Templates(directory="templates")

try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

# ── Helpers ──
def render(req, tpl, ctx={}):
    m = get_member(req)
    return templates.TemplateResponse(tpl, {
        "request": req, "member": m, "cfg": cfg,
        "secteurs": cfg.SECTEURS, "days_left": days_left,
        "now": datetime.now(), **ctx
    })

def _get_stats():
    db = get_db()
    try:
        return {
            "tenders": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "today":   db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND scraped_at>=date('now')").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "notifs":  db.execute("SELECT COUNT(*) FROM notif_log WHERE sent_at>=date('now','-7 days')").fetchone()[0],
        }
    finally: db.close()

def _expire_tenders():
    db = get_db()
    today = date.today(); expired = []
    rows = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
    for r in rows:
        m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(r["date_limite"]))
        if m:
            try:
                fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
                if datetime.strptime(m.group(1), fmt).date() < today:
                    expired.append(r["id"])
            except: pass
    if expired:
        db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join(['?']*len(expired))})", expired)
        db.commit()
    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return len(expired), active

# ═══════════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    stats = _get_stats()
    recent = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9").fetchall()]
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 10").fetchall()]
    db.close()
    return render(req, "landing.html", {"stats": stats, "recent": recent, "sectors": sectors})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, q:str="", s:str="", r:str="", page:int=1, sort:str="recent"):
    member = get_member(req)
    db = get_db(); per = 25
    where, params = ["statut='actif'"], []
    if q: where.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)"); params += [f"%{q}%"]*3
    if s: where.append("secteur=?"); params.append(s)
    if r: where.append("region=?"); params.append(r)
    wh = " AND ".join(where)
    order = "scraped_at DESC" if sort == "recent" else "date_limite ASC"
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(r2) for r2 in db.execute(
        f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per, (page-1)*per]).fetchall()]
    # Favoris de l'utilisateur
    favs = set()
    if member:
        favs = {r2[0] for r2 in db.execute("SELECT tender_id FROM favorites WHERE member_id=?", (member["id"],)).fetchall()}
    db.close()
    pages = max(1, (total + per - 1) // per)
    return render(req, "tenders.html", {
        "tenders": rows, "total": total, "page": page, "pages": pages,
        "q": q, "sf": s, "rf": r, "sort": sort, "favs": favs,
    })

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if t:
        db.execute("UPDATE tenders SET views=views+1 WHERE id=?", (tid,))
        db.commit()
    related = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE secteur=? AND id!=? AND statut='actif' ORDER BY scraped_at DESC LIMIT 4",
        (t["secteur"] if t else "", tid)).fetchall()] if t else []
    member = get_member(req)
    is_fav = False
    if member and t:
        is_fav = bool(db.execute("SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
                                  (member["id"], tid)).fetchone())
    db.close()
    if not t: return HTMLResponse("Marché introuvable", 404)
    return render(req, "detail.html", {"t": dict(t), "related": related, "is_fav": is_fav})

@app.post("/tenders/{tid}/favorite")
async def toggle_favorite(req: Request, tid: str):
    member = get_member(req)
    if not member: return JSONResponse({"ok": False, "msg": "Non connecté"}, 401)
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
                              (member["id"], tid)).fetchone()
        if existing:
            db.execute("DELETE FROM favorites WHERE member_id=? AND tender_id=?", (member["id"], tid))
            db.commit(); return JSONResponse({"ok": True, "fav": False})
        else:
            db.execute("INSERT OR IGNORE INTO favorites(member_id,tender_id,created_at) VALUES(?,?,?)",
                       (member["id"], tid, datetime.now().isoformat()))
            db.commit(); return JSONResponse({"ok": True, "fav": True})
    finally: db.close()

@app.get("/favorites", response_class=HTMLResponse)
async def favorites_page(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login", 302)
    db = get_db()
    rows = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t 
           JOIN favorites f ON f.tender_id=t.id 
           WHERE f.member_id=? ORDER BY f.created_at DESC""",
        (member["id"],)).fetchall()]
    db.close()
    return render(req, "favorites.html", {"tenders": rows})

# ═══════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request): return render(req, "register.html", {})

@app.post("/register")
async def register_post(req: Request,
    nom:str=Form(""), email:str=Form(""), phone:str=Form(""), company:str=Form(""),
    pw:str=Form(""), pw2:str=Form(""), secteurs_sel:list=Form([])):
    err = None
    if not email or not pw: err = "Email et mot de passe requis"
    elif not validate_email(email): err = "Email invalide"
    elif pw != pw2: err = "Les mots de passe ne correspondent pas"
    else:
        ok, msg = validate_password(pw)
        if not ok: err = msg
    if err: return render(req, "register.html", {"err": err, "vals": {"nom":nom,"email":email,"phone":phone,"company":company}})
    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
            return render(req, "register.html", {"err": "Cet email est déjà utilisé", "vals": {"nom":nom,"email":email}})
        trial_ends = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        db.execute("""INSERT INTO members(nom,email,phone,company,pw_hash,secteurs,plan,created_at,trial_ends)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                   (nom, email, phone, company, hash_pw(pw),
                    json.dumps(secteurs_sel), "free", datetime.now().isoformat(), trial_ends))
        db.commit()
    finally: db.close()
    resp = RedirectResponse("/tenders?welcome=1", 302)
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()
    db.close()
    if m: resp.set_cookie("_session", make_token(m["email"], m["created_at"]), max_age=86400*30, httponly=True, samesite="lax")
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request, next:str=""):
    return render(req, "login.html", {"next": next})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), pw:str=Form(""), next:str=Form("")):
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE email=? AND actif=1", (email,)).fetchone()
    db.close()
    if not m or not verify_pw(pw, m["pw_hash"]):
        return render(req, "login.html", {"err": "Email ou mot de passe incorrect", "vals": {"email": email}})
    db = get_db()
    db.execute("UPDATE members SET last_login=? WHERE id=?", (datetime.now().isoformat(), m["id"]))
    db.commit(); db.close()
    resp = RedirectResponse(next or "/tenders", 302)
    resp.set_cookie("_session", make_token(m["email"], m["created_at"]), max_age=86400*30, httponly=True, samesite="lax")
    return resp

@app.get("/logout")
async def logout():
    r = RedirectResponse("/", 302)
    r.delete_cookie("_session"); return r

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/dashboard", 302)
    db = get_db()
    favs  = [dict(r) for r in db.execute(
        "SELECT t.* FROM tenders t JOIN favorites f ON f.tender_id=t.id WHERE f.member_id=? AND t.statut='actif' ORDER BY f.created_at DESC LIMIT 5",
        (member["id"],)).fetchall()]
    notifs = [dict(r) for r in db.execute(
        "SELECT nl.*,t.objet FROM notif_log nl JOIN tenders t ON t.id=nl.tender_id WHERE nl.member_id=? ORDER BY nl.sent_at DESC LIMIT 10",
        (member["id"],)).fetchall()]
    member_sects = json.loads(member.get("secteurs","[]") or "[]")
    recs = [dict(r) for r in db.execute(
        f"SELECT * FROM tenders WHERE secteur IN ({','.join(['?']*len(member_sects))}) AND statut='actif' ORDER BY scraped_at DESC LIMIT 6",
        member_sects).fetchall()] if member_sects else []
    stats = {
        "favs":   db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?", (member["id"],)).fetchone()[0],
        "notifs": db.execute("SELECT COUNT(*) FROM notif_log WHERE member_id=?", (member["id"],)).fetchone()[0],
    }
    db.close()
    return render(req, "dashboard.html", {"favs": favs, "notifs": notifs, "recs": recs, "stats": stats})

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/settings", 302)
    ms = json.loads(member.get("secteurs","[]") or "[]")
    return render(req, "settings.html", {"ms": ms})

@app.post("/settings")
async def settings_post(req: Request,
    nom:str=Form(""), phone:str=Form(""), company:str=Form(""),
    telegram:str=Form(""), notif_email:int=Form(0), notif_tg:int=Form(0),
    notif_digest:int=Form(0), secteurs_sel:list=Form([])):
    member = get_member(req)
    if not member: return RedirectResponse("/login", 302)
    db = get_db()
    db.execute("""UPDATE members SET nom=?,phone=?,company=?,telegram=?,
                  notif_email=?,notif_tg=?,notif_digest=?,secteurs=? WHERE id=?""",
               (nom, phone, company, telegram.strip(), notif_email, notif_tg, notif_digest,
                json.dumps(secteurs_sel), member["id"]))
    db.commit(); db.close()
    return RedirectResponse("/settings?ok=1", 302)

# ═══════════════════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════════════════
def _is_admin(req: Request) -> bool:
    return req.cookies.get("_admin","") == make_token("admin", cfg.ADMIN_PASS)

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_get(req: Request):
    return render(req, "admin_login.html", {})

@app.post("/admin/login")
async def admin_login_post(req: Request, pwd: str = Form("")):
    if pwd != cfg.ADMIN_PASS:
        return render(req, "admin_login.html", {"err": "Mot de passe incorrect"})
    r = RedirectResponse("/admin", 302)
    r.set_cookie("_admin", make_token("admin", cfg.ADMIN_PASS), httponly=True, max_age=86400*7, samesite="lax")
    return r

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(req: Request):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    stats = {**_get_stats(),
             "expired": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
             "scrapes": db.execute("SELECT COUNT(*) FROM scrape_log").fetchone()[0]}
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC").fetchall()]
    members = [dict(r) for r in db.execute(
        "SELECT id,nom,email,plan,created_at,last_login FROM members ORDER BY created_at DESC LIMIT 20").fetchall()]
    recent_scrapes = [dict(r) for r in db.execute(
        "SELECT * FROM scrape_log ORDER BY run_at DESC LIMIT 5").fetchall()]
    db.close()
    return templates.TemplateResponse("admin.html", {
        "request": req, "stats": stats, "sectors": sectors,
        "members": members, "scrapes": recent_scrapes,
        "logs": State.logs[-80:], "running": State.running,
        "last_run": State.last_run, "cfg": cfg,
    })

@app.get("/admin/scrape")
async def admin_scrape(req: Request):
    if not _is_admin(req): return JSONResponse({"ok":False}, 401)
    if State.running: return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok":True})

@app.get("/admin/scrape_stream")
async def admin_stream(req: Request):
    if not _is_admin(req): return JSONResponse({"error":"unauthorized"}, 401)
    async def gen():
        last = 0
        while True:
            logs = State.logs
            if len(logs) > last:
                for log in logs[last:]:
                    yield f"data: {json.dumps({'log':log,'running':State.running,'saved':State.saved})}\n\n"
                last = len(logs)
            if not State.running and last > 0:
                yield f"data: {json.dumps({'done':True,'saved':State.saved,'found':State.found})}\n\n"; break
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/admin/expire")
async def admin_expire(req: Request):
    if not _is_admin(req): return JSONResponse({"ok":False}, 401)
    exp, active = _expire_tenders()
    return JSONResponse({"ok":True,"expired":exp,"active":active})

@app.post("/admin/member/{mid}/plan")
async def set_plan(req: Request, mid: int, plan: str = Form("")):
    if not _is_admin(req): return JSONResponse({"ok":False}, 401)
    if plan not in cfg.PLANS: return JSONResponse({"ok":False,"msg":"Plan invalide"})
    db = get_db()
    db.execute("UPDATE members SET plan=? WHERE id=?", (plan, mid))
    db.commit(); db.close()
    return JSONResponse({"ok":True})

@app.get("/admin/clear")
async def admin_clear(req: Request, confirm: str = ""):
    if not _is_admin(req): return JSONResponse({"ok":False}, 401)
    if confirm != "yes": return HTMLResponse('<a href="/admin/clear?confirm=yes">Confirmer la suppression</a>')
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    db.execute("DELETE FROM tenders"); db.execute("DELETE FROM notif_log"); db.commit(); db.close()
    return JSONResponse({"ok":True,"deleted":n})

# ═══════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════
@app.get("/api/v1/tenders")
async def api_tenders(req: Request, secteur:str="", limit:int=20, offset:int=0):
    member = get_member(req)
    db = get_db()
    where, params = ["statut='actif'"], []
    if secteur: where.append("secteur=?"); params.append(secteur)
    rows = [dict(r) for r in db.execute(
        f"SELECT id,objet,acheteur,secteur,region,montant,date_limite,url,scraped_at FROM tenders WHERE {' AND '.join(where)} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
        params + [min(limit,100), offset]).fetchall()]
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {' AND '.join(where)}", params).fetchone()[0]
    db.close()
    return {"ok":True,"total":total,"results":rows}

@app.get("/api/v1/stats")
async def api_stats():
    return {"ok": True, **_get_stats()}

@app.get("/health")
async def health():
    db = get_db()
    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return {"status":"ok","version":cfg.APP_VERSION,"brand":cfg.APP_NAME,
            "active":active,"running":State.running,"last_run":State.last_run}

@app.get("/sitemap.xml")
async def sitemap():
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM tenders WHERE statut='actif' LIMIT 1000").fetchall()]
    db.close()
    urls = [f"<url><loc>{cfg.SITE_URL}/tenders/{tid}</loc></url>" for tid in ids]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{cfg.SITE_URL}/</loc></url>
<url><loc>{cfg.SITE_URL}/tenders</loc></url>
{"".join(urls)}
</urlset>"""
    return Response(xml, media_type="application/xml")
