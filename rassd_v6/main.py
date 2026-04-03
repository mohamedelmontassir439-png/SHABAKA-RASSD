"""
RASSD — Veille Marchés Publics Maroc
Source unique: marchespublics.gov.ma
Notifications temps réel par secteur
"""
import os, re, json, asyncio, secrets, logging, smtplib, hashlib, requests
from datetime import datetime, date
from typing import Optional
from contextlib import asynccontextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3, bcrypt, schedule, time as _time

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("rassd")

# ══ CONFIG ══════════════════════════════════════════════════
SITE_URL      = os.getenv("SITE_URL",     "https://web-production-b4ae4.up.railway.app")
ADMIN_PASS    = os.getenv("ADMIN_PASS",   "rassd2026")
SECRET_KEY    = os.getenv("SECRET_KEY",   secrets.token_hex(32))
DB_PATH       = os.getenv("DB_PATH",      "data/rassd.db")
TELEGRAM_BOT  = os.getenv("TELEGRAM_BOT", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID","")
BREVO_KEY     = os.getenv("BREVO_API_KEY","")
GMAIL_USER    = os.getenv("GMAIL_USER",   "")
GMAIL_PASS    = os.getenv("GMAIL_PASS",   "")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_MIN", "60"))  # minutes

SECTEURS = [
    "Travaux BTP","IT & Télécoms","Santé & Médical","Transport & Véhicules",
    "Services Généraux","Études & Conseil","Formation","Restauration",
    "Communication","Énergie","Hydraulique","Fournitures Bureau","Mobilier","Autres Fournitures"
]

# ══ DB ══════════════════════════════════════════════════════
def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id TEXT PRIMARY KEY,
        objet TEXT NOT NULL DEFAULT '',
        acheteur TEXT DEFAULT '',
        secteur TEXT DEFAULT '',
        montant TEXT DEFAULT '',
        date_publication TEXT DEFAULT '',
        date_limite TEXT DEFAULT '',
        description TEXT DEFAULT '',
        url TEXT DEFAULT '',
        statut TEXT DEFAULT 'actif',
        scraped_at TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT DEFAULT '',
        email TEXT UNIQUE NOT NULL,
        phone TEXT DEFAULT '',
        pw_hash TEXT DEFAULT '',
        secteurs TEXT DEFAULT '[]',
        telegram TEXT DEFAULT '',
        notif_email INTEGER DEFAULT 1,
        notif_tg INTEGER DEFAULT 1,
        plan TEXT DEFAULT 'free',
        actif INTEGER DEFAULT 1,
        created_at TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS notif_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        tender_id TEXT,
        channel TEXT,
        sent_at TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_scraped ON tenders(scraped_at DESC);
    CREATE INDEX IF NOT EXISTS idx_t_secteur ON tenders(secteur);
    """)
    c.commit(); c.close()

# ══ AUTH ════════════════════════════════════════════════════
def hash_pw(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def check_pw(pw, h): return bcrypt.checkpw(pw.encode(), h.encode())
def make_token(v): return hashlib.sha256(f"{v}{SECRET_KEY}".encode()).hexdigest()[:32]

def get_member(req: Request):
    token = req.cookies.get("auth","")
    if not token: return None
    c = db()
    try:
        m = c.execute("SELECT * FROM members WHERE actif=1").fetchall()
        for row in m:
            if make_token(row["email"]) == token:
                return dict(row)
    finally: c.close()
    return None

def render(req, tpl, ctx={}):
    m = get_member(req)
    return templates.TemplateResponse(tpl, {"request":req,"member":m,"site":SITE_URL,**ctx})

# ══ NOTIFICATIONS ════════════════════════════════════════════
def tg_send(chat_id, text):
    if not TELEGRAM_BOT or not chat_id: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
            json={"chat_id":chat_id,"text":text,"parse_mode":"HTML"}, timeout=8)
        return r.status_code == 200
    except: return False

def email_send(to, subject, html):
    if BREVO_KEY:
        try:
            r = requests.post("https://api.brevo.com/v3/smtp/email",
                headers={"api-key":BREVO_KEY,"Content-Type":"application/json"},
                json={"sender":{"name":"RASSD","email":"no-reply@rassd.ma"},
                      "to":[{"email":to}],"subject":subject,"htmlContent":html}, timeout=10)
            return r.status_code in (200,201)
        except: pass
    if GMAIL_USER and GMAIL_PASS:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject; msg["From"] = GMAIL_USER; msg["To"] = to
            msg.attach(MIMEText(html,"html"))
            with smtplib.SMTP_SSL("smtp.gmail.com",465) as srv:
                srv.login(GMAIL_USER,GMAIL_PASS); srv.send_message(msg)
            return True
        except: pass
    return False

def days_left(dl):
    if not dl: return ""
    m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(dl))
    if not m: return ""
    try:
        fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
        d = datetime.strptime(m.group(1),fmt).date()
        delta = (d - date.today()).days
        if delta < 0: return "Expiré"
        if delta == 0: return "Aujourd'hui!"
        if delta <= 3: return f"🔥 {delta}j"
        if delta <= 7: return f"⏳ {delta}j"
        return f"{delta} jours"
    except: return ""

def notify_tender(tender: dict):
    """Envoie le tender aux membres du même secteur"""
    c = db()
    try:
        members = c.execute(
            "SELECT * FROM members WHERE actif=1 AND (notif_email=1 OR notif_tg=1)"
        ).fetchall()
        for m in members:
            member_secteurs = json.loads(m["secteurs"] or "[]")
            if member_secteurs and tender["secteur"] not in member_secteurs: continue
            already = c.execute(
                "SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                (m["id"], tender["id"])
            ).fetchone()
            if already: continue
            dl = tender.get("date_limite","")
            days = days_left(dl)
            if m["notif_tg"] and m["telegram"]:
                msg = (f"🏛 <b>Nouveau marché</b>\n{'━'*28}\n\n"
                       f"📋 <b>{tender['objet'][:80]}</b>\n\n"
                       f"🏢 {tender.get('acheteur','')[:50]}\n"
                       f"🏷 {tender['secteur']}\n"
                       f"⏰ <b>{dl}{f' — {days}' if days else ''}</b>\n"
                       f"{'💰 '+tender['montant'] if tender.get('montant') else ''}\n\n"
                       f"🔗 {tender['url']}\n\n"
                       f"🌐 {SITE_URL}")
                if tg_send(m["telegram"], msg):
                    c.execute("INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                              (m["id"],tender["id"],"telegram",datetime.now().isoformat()))
            if m["notif_email"] and m["email"]:
                html = _build_email(tender, m["nom"])
                if email_send(m["email"], f"📋 Nouveau marché: {tender['objet'][:60]}", html):
                    c.execute("INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                              (m["id"],tender["id"],"email",datetime.now().isoformat()))
        c.commit()
    finally: c.close()

def _build_email(t, nom):
    dl = t.get("date_limite","—")
    days = days_left(dl)
    return f"""<!DOCTYPE html><html><body style="margin:0;background:#0a0a0a;font-family:'Georgia',serif">
<div style="max-width:600px;margin:0 auto;padding:24px">
  <div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:24px">
    <span style="font-size:20px;font-weight:700;color:#c9a84c;letter-spacing:2px">RASSD</span>
    <span style="font-size:11px;color:#555;margin-left:12px">Veille Marchés Publics</span>
  </div>
  <p style="color:#888;font-size:13px">Bonjour {nom or 'Madame/Monsieur'},</p>
  <p style="color:#ccc;font-size:13px">Un nouveau marché correspondant à votre secteur vient d'être publié:</p>
  <div style="background:#141414;border:1px solid #2a2a2a;border-radius:8px;padding:20px;margin:20px 0">
    <div style="font-size:16px;font-weight:700;color:#f0ede6;margin-bottom:16px;line-height:1.4">{t['objet'][:150]}</div>
    <table style="width:100%;border-collapse:collapse">
      <tr><td style="color:#666;font-size:11px;padding:4px 0;width:120px">🏢 Acheteur</td><td style="color:#aaa;font-size:11px">{t.get('acheteur','—')[:70]}</td></tr>
      <tr><td style="color:#666;font-size:11px;padding:4px 0">🏷 Secteur</td><td style="color:#c9a84c;font-size:11px;font-weight:700">{t['secteur']}</td></tr>
      {'<tr><td style="color:#666;font-size:11px;padding:4px 0">💰 Montant</td><td style="color:#aaa;font-size:11px">'+t['montant']+'</td></tr>' if t.get('montant') else ''}
      <tr><td style="color:#666;font-size:11px;padding:4px 0">⏰ Date limite</td><td style="color:#e87070;font-size:11px;font-weight:700">{dl}{f' <span style="color:#c9a84c">({days})</span>' if days else ''}</td></tr>
    </table>
    <a href="{t['url']}" style="display:inline-block;margin-top:16px;padding:10px 20px;background:#c9a84c;color:#000;border-radius:4px;font-weight:700;text-decoration:none;font-size:13px">Voir le marché →</a>
    <a href="{SITE_URL}/tenders/{t['id']}" style="display:inline-block;margin-top:16px;margin-left:10px;padding:10px 20px;border:1px solid #c9a84c;color:#c9a84c;border-radius:4px;font-weight:700;text-decoration:none;font-size:13px">Détails complets</a>
  </div>
  <p style="color:#444;font-size:10px;text-align:center;margin-top:24px">
    RASSD · <a href="{SITE_URL}" style="color:#666">rassd.ma</a> · 
    <a href="{SITE_URL}/settings" style="color:#666">Gérer mes alertes</a>
  </p>
</div></body></html>"""

# ══ SCRAPER STATE ════════════════════════════════════════════
class State:
    running = False
    found = saved = errors = 0
    started = ""
    logs = []

    @classmethod
    def log(cls, msg):
        e = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.logs.append(e); logger.info(e)
        if len(cls.logs) > 500: cls.logs = cls.logs[-400:]

# ══ SCRAPER RUNNER ════════════════════════════════════════════
async def do_scrape():
    if State.running: return
    State.running = True
    State.found = State.saved = State.errors = 0
    State.started = datetime.now().strftime("%H:%M:%S")
    State.log("═══ Scan marchespublics.gov.ma ═══")
    try:
        try:
            from realtime_scraper import run
        except ImportError:
            from scraper import run
        c = db()
        known = {r[0] for r in c.execute("SELECT id FROM tenders").fetchall()}
        c.close()
        loop = asyncio.get_event_loop()
        tenders = await loop.run_in_executor(None, lambda: run(known, State.log))
        State.found = len(tenders)
        c = db()
        new_ones = []
        for t in tenders:
            try:
                c.execute("""INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,secteur,montant,date_publication,
                     date_limite,description,url,statut,scraped_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (t["id"],t["objet"],t["acheteur"],t["secteur"],t["montant"],
                     t["date_publication"],t["date_limite"],t["description"],
                     t["url"],t["statut"],t["scraped_at"]))
                if c.execute("SELECT changes()").fetchone()[0]:
                    State.saved += 1
                    new_ones.append(t)
            except Exception as e: State.errors += 1
        c.commit(); c.close()
        State.log(f"═══ {State.saved} nouveaux marchés sauvegardés ═══")
        # Notify pour chaque nouveau tender
        for t in new_ones:
            try: notify_tender(t)
            except: pass
        # Admin summary
        if new_ones and ADMIN_CHAT_ID:
            tg_send(ADMIN_CHAT_ID,
                f"✅ <b>Scan terminé</b>\n{State.saved} nouveaux marchés sur marchespublics")
    except Exception as e:
        State.log(f"❌ Erreur: {e}")
        logger.error(f"[scrape] {e}")
    finally:
        State.running = False

# ══ BACKGROUND SCHEDULER ══════════════════════════════════════
async def scheduler_loop():
    await asyncio.sleep(10)
    while True:
        try: await do_scrape()
        except: pass
        await asyncio.sleep(SCAN_INTERVAL * 60)

# ══ APP ══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app):
    init_db()
    State.log("RASSD démarré")
    asyncio.create_task(scheduler_loop())
    yield

app = FastAPI(lifespan=lifespan, title="RASSD", docs_url=None)
templates = Jinja2Templates(directory="templates")
try: app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

# ══ ROUTES ════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    c = db()
    try:
        stats = {
            "total":   c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "today":   c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND scraped_at >= date('now')").fetchone()[0],
            "members": c.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
        }
        recent = [dict(r) for r in c.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 6").fetchall()]
        sectors = [dict(r) for r in c.execute(
            "SELECT secteur, COUNT(*) as cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC").fetchall()]
    finally: c.close()
    return render(req,"landing.html",{"stats":stats,"recent":recent,"sectors":sectors,"secteurs":SECTEURS})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_list(req: Request, q="", secteur="", page:int=1):
    m = get_member(req)
    c = db(); per_page = 20
    where, params = ["statut='actif'"], []
    if q: where.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%",f"%{q}%"]
    if secteur: where.append("secteur=?"); params.append(secteur)
    w = " AND ".join(where)
    total = c.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}", params).fetchone()[0]
    tenders = [dict(r) for r in c.execute(
        f"SELECT * FROM tenders WHERE {w} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
        params + [per_page, (page-1)*per_page]).fetchall()]
    c.close()
    pages = (total + per_page - 1) // per_page
    return render(req,"tenders.html",{
        "tenders":tenders,"total":total,"page":page,"pages":pages,
        "q":q,"secteur_f":secteur,"secteurs":SECTEURS,"days_left":days_left
    })

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    c = db()
    t = c.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    c.close()
    if not t: return HTMLResponse("Marché introuvable", 404)
    return render(req,"detail.html",{"t":dict(t),"days_left":days_left})

@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request):
    return render(req,"register.html",{"secteurs":SECTEURS})

@app.post("/register")
async def register_post(req: Request, nom:str=Form(""), email:str=Form(""),
                         phone:str=Form(""), pw:str=Form(""),
                         secteurs:list=Form([])):
    if not email or not pw: return render(req,"register.html",{"err":"Email et mot de passe requis","secteurs":SECTEURS})
    c = db()
    try:
        if c.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
            return render(req,"register.html",{"err":"Email déjà utilisé","secteurs":SECTEURS})
        c.execute("INSERT INTO members(nom,email,phone,pw_hash,secteurs,created_at) VALUES(?,?,?,?,?,?)",
                  (nom,email,phone,hash_pw(pw),json.dumps(secteurs),datetime.now().isoformat()))
        c.commit()
    finally: c.close()
    resp = RedirectResponse("/tenders",302)
    resp.set_cookie("auth", make_token(email), max_age=86400*30, httponly=True)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    return render(req,"login.html",{})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), pw:str=Form("")):
    c = db()
    try:
        m = c.execute("SELECT * FROM members WHERE email=? AND actif=1", (email,)).fetchone()
    finally: c.close()
    if not m or not check_pw(pw, m["pw_hash"]):
        return render(req,"login.html",{"err":"Email ou mot de passe incorrect"})
    resp = RedirectResponse("/tenders",302)
    resp.set_cookie("auth", make_token(email), max_age=86400*30, httponly=True)
    return resp

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/",302)
    resp.delete_cookie("auth")
    return resp

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    member_secteurs = json.loads(m.get("secteurs","[]"))
    return render(req,"settings.html",{"secteurs":SECTEURS,"member_secteurs":member_secteurs})

@app.post("/settings")
async def settings_post(req: Request, nom:str=Form(""), phone:str=Form(""),
                          telegram:str=Form(""), notif_email:int=Form(1),
                          notif_tg:int=Form(1), secteurs:list=Form([])):
    m = get_member(req)
    if not m: return RedirectResponse("/login",302)
    c = db()
    try:
        c.execute("UPDATE members SET nom=?,phone=?,telegram=?,notif_email=?,notif_tg=?,secteurs=? WHERE id=?",
                  (nom,phone,telegram,notif_email,notif_tg,json.dumps(secteurs),m["id"]))
        c.commit()
    finally: c.close()
    return RedirectResponse("/settings?ok=1",302)

# ── Admin ──
@app.get("/admin", response_class=HTMLResponse)
async def admin_get(req: Request, pwd:str=""):
    cookie = req.cookies.get("admin_sess","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return render(req,"admin_login.html",{})
    c = db()
    stats = {
        "tenders": c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
        "members": c.execute("SELECT COUNT(*) FROM members").fetchone()[0],
        "notifs":  c.execute("SELECT COUNT(*) FROM notif_log").fetchone()[0],
    }
    sectors_count = [dict(r) for r in c.execute(
        "SELECT secteur, COUNT(*) as cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC").fetchall()]
    c.close()
    resp = HTMLResponse(templates.get_template("admin.html").render(
        {"request":req,"stats":stats,"sectors_count":sectors_count,"logs":State.logs[-50:],"running":State.running}))
    resp.set_cookie("admin_sess",ADMIN_PASS,httponly=True,max_age=86400*7)
    return resp

@app.post("/admin/login")
async def admin_login(req: Request, pwd:str=Form("")):
    if pwd != ADMIN_PASS: return render(req,"admin_login.html",{"err":"Mot de passe incorrect"})
    resp = RedirectResponse("/admin",302)
    resp.set_cookie("admin_sess",ADMIN_PASS,httponly=True,max_age=86400*7)
    return resp

@app.get("/admin/scrape")
async def admin_scrape(req: Request, pwd:str=""):
    cookie = req.cookies.get("admin_sess","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return JSONResponse({"ok":False,"msg":"Non autorisé"},401)
    if State.running:
        return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok":True,"msg":"Scan démarré"})

@app.get("/admin/scrape_stream")
async def scrape_stream(req: Request, pwd:str=""):
    cookie = req.cookies.get("admin_sess","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return JSONResponse({"error":"unauthorized"},401)
    async def gen():
        last = 0
        while True:
            logs = State.logs
            if len(logs) > last:
                for log in logs[last:]:
                    yield f"data: {json.dumps({'log':log,'running':State.running,'saved':State.saved})}\n\n"
                last = len(logs)
            if not State.running and last >= len(logs) and last > 0:
                yield f"data: {json.dumps({'done':True,'saved':State.saved})}\n\n"
                break
            await asyncio.sleep(0.8)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/admin/clear_db")
async def admin_clear(req: Request, pwd:str="", confirm:str=""):
    cookie = req.cookies.get("admin_sess","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    if confirm != "yes":
        return HTMLResponse('<a href="/admin/clear_db?confirm=yes">Confirmer la suppression de tous les marchés</a>')
    c = db()
    n = c.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    c.execute("DELETE FROM tenders"); c.execute("DELETE FROM notif_log"); c.commit(); c.close()
    return JSONResponse({"ok":True,"deleted":n})

@app.get("/admin/expire_now")
async def admin_expire(req: Request, pwd:str=""):
    cookie = req.cookies.get("admin_sess","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    c = db()
    today = date.today()
    rows = c.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
    exp = []
    for r in rows:
        dl = str(r["date_limite"]).strip()
        m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', dl)
        if m:
            try:
                fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
                if datetime.strptime(m.group(1),fmt).date() < today: exp.append(r["id"])
            except: pass
    if exp:
        ph = ",".join(["?"]*len(exp))
        c.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp)
    c.commit(); active = c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]; c.close()
    return JSONResponse({"ok":True,"expired":len(exp),"active_remaining":active})

@app.get("/health")
async def health():
    c = db()
    actif = c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]; c.close()
    return {"status":"ok","version":"1.0","brand":"RASSD","active":actif,"running":State.running}

@app.get("/api/tenders")
async def api_tenders(req: Request, secteur:str="", limit:int=20):
    # Check API key or auth
    m = get_member(req)
    c = db()
    where, params = ["statut='actif'"], []
    if secteur: where.append("secteur=?"); params.append(secteur)
    rows = [dict(r) for r in c.execute(
        f"SELECT id,objet,acheteur,secteur,montant,date_limite,url,scraped_at FROM tenders WHERE {' AND '.join(where)} ORDER BY scraped_at DESC LIMIT ?",
        params+[min(limit,100)]).fetchall()]
    c.close()
    return {"tenders":rows,"total":len(rows)}
