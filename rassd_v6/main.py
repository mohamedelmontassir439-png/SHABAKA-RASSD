"""RASSD — Veille Marchés Publics Maroc"""
import os, re, json, asyncio, secrets, logging, hashlib, smtplib, requests
from datetime import datetime, date
from contextlib import asynccontextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3, bcrypt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rassd")

SITE_URL      = os.getenv("SITE_URL",     "https://web-production-b4ae4.up.railway.app")
ADMIN_PASS    = os.getenv("ADMIN_PASS",   "rassd2026")
SECRET_KEY    = os.getenv("SECRET_KEY",   secrets.token_hex(32))
DB_PATH       = os.getenv("DB_PATH",      "data/rassd.db")
TELEGRAM_BOT  = os.getenv("TELEGRAM_BOT", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID","")
BREVO_KEY     = os.getenv("BREVO_API_KEY","")
GMAIL_USER    = os.getenv("GMAIL_USER",   "")
GMAIL_PASS    = os.getenv("GMAIL_PASS",   "")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_MIN","60"))

SECTEURS = ["Travaux BTP","IT & Télécoms","Santé & Médical","Transport & Véhicules",
            "Services Généraux","Études & Conseil","Formation","Restauration",
            "Communication","Énergie","Hydraulique","Fournitures Bureau","Mobilier","Autres Fournitures"]

# ── DB ──────────────────────────────────────────────────
def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id TEXT PRIMARY KEY, objet TEXT NOT NULL DEFAULT '',
        acheteur TEXT DEFAULT '', secteur TEXT DEFAULT '',
        montant TEXT DEFAULT '', date_publication TEXT DEFAULT '',
        date_limite TEXT DEFAULT '', description TEXT DEFAULT '',
        url TEXT DEFAULT '', statut TEXT DEFAULT 'actif',
        scraped_at TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT DEFAULT '', email TEXT UNIQUE NOT NULL,
        phone TEXT DEFAULT '', pw_hash TEXT DEFAULT '',
        secteurs TEXT DEFAULT '[]', telegram TEXT DEFAULT '',
        notif_email INTEGER DEFAULT 1, notif_tg INTEGER DEFAULT 1,
        actif INTEGER DEFAULT 1, created_at TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS notif_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER, tender_id TEXT, channel TEXT, sent_at TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
    CREATE INDEX IF NOT EXISTS idx_t_scraped ON tenders(scraped_at DESC);
    CREATE INDEX IF NOT EXISTS idx_t_secteur ON tenders(secteur);
    """)
    c.commit(); c.close()

# ── AUTH ─────────────────────────────────────────────────
def hash_pw(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def check_pw(pw,h): return bcrypt.checkpw(pw.encode(), h.encode())
def make_token(v): return hashlib.sha256(f"{v}{SECRET_KEY}".encode()).hexdigest()[:32]

def get_member(req):
    t = req.cookies.get("auth","")
    if not t: return None
    c = db()
    try:
        for m in c.execute("SELECT * FROM members WHERE actif=1").fetchall():
            if make_token(m["email"]) == t: return dict(m)
    finally: c.close()
    return None

def render(req, tpl, ctx={}):
    m = get_member(req)
    return templates.TemplateResponse(tpl, {"request":req,"member":m,"site":SITE_URL,"secteurs":SECTEURS,**ctx})

# ── NOTIFICATIONS ────────────────────────────────────────
def tg(chat_id, text):
    if not TELEGRAM_BOT or not chat_id: return
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
        json={"chat_id":chat_id,"text":text,"parse_mode":"HTML"}, timeout=8)
    except: pass

def days_left(dl):
    if not dl: return ""
    m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(dl))
    if not m: return ""
    try:
        fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
        delta = (datetime.strptime(m.group(1),fmt).date() - date.today()).days
        if delta < 0: return "Expiré"
        if delta == 0: return "⚡ Aujourd'hui!"
        if delta == 1: return "⚡ Demain!"
        if delta <= 3: return f"🔥 {delta}j"
        if delta <= 7: return f"⏳ {delta}j"
        return f"{delta}j"
    except: return ""

def notify_new(tender):
    c = db()
    try:
        members = c.execute("SELECT * FROM members WHERE actif=1").fetchall()
        for m in members:
            secs = json.loads(m["secteurs"] or "[]")
            if secs and tender["secteur"] not in secs: continue
            dup = c.execute("SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                           (m["id"],tender["id"])).fetchone()
            if dup: continue
            dl = tender.get("date_limite",""); days = days_left(dl)
            if m["notif_tg"] and m["telegram"]:
                msg = (f"🏛 <b>Nouveau Marché</b>\n{'━'*30}\n\n"
                       f"📋 <b>{tender['objet'][:80]}</b>\n\n"
                       f"🏢 {tender.get('acheteur','')[:60]}\n"
                       f"🏷 {tender['secteur']}\n"
                       f"⏰ <b>{dl}{f' — {days}' if days else ''}</b>\n"
                       f"{'💰 '+tender['montant'] if tender.get('montant') else ''}\n\n"
                       f"🔗 {tender['url']}\n🌐 {SITE_URL}/tenders/{tender['id']}")
                tg(m["telegram"], msg)
                c.execute("INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                          (m["id"],tender["id"],"tg",datetime.now().isoformat()))
            if m["notif_email"] and m["email"]:
                html = _email_html(tender, m["nom"])
                if _send_email(m["email"], f"📋 {tender['objet'][:60]}", html):
                    c.execute("INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                              (m["id"],tender["id"],"email",datetime.now().isoformat()))
        c.commit()
    finally: c.close()

def _send_email(to, subject, html):
    if BREVO_KEY:
        try:
            r = requests.post("https://api.brevo.com/v3/smtp/email",
                headers={"api-key":BREVO_KEY,"Content-Type":"application/json"},
                json={"sender":{"name":"RASSD","email":"no-reply@rassd.ma"},
                      "to":[{"email":to}],"subject":subject,"htmlContent":html}, timeout=10)
            return r.status_code in (200,201)
        except: pass
    if GMAIL_USER:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"]=subject; msg["From"]=GMAIL_USER; msg["To"]=to
            msg.attach(MIMEText(html,"html"))
            with smtplib.SMTP_SSL("smtp.gmail.com",465) as srv:
                srv.login(GMAIL_USER,GMAIL_PASS); srv.send_message(msg)
            return True
        except: pass
    return False

def _email_html(t, nom):
    dl=t.get("date_limite","—"); days=days_left(dl)
    return f"""<!DOCTYPE html><html><body style="margin:0;background:#06060a;font-family:'Georgia',serif">
<div style="max-width:600px;margin:0 auto;padding:32px">
<div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:24px;display:flex;align-items:center;gap:12px">
  <span style="font-size:22px;font-weight:900;color:#c9a84c;letter-spacing:3px">RASSD</span>
  <span style="font-size:10px;color:#555;letter-spacing:2px;text-transform:uppercase">Marchés Publics Maroc</span>
</div>
<p style="color:#888;font-size:13px;margin-bottom:20px">Bonjour {nom or 'Madame/Monsieur'},<br>Un nouveau marché correspond à votre secteur :</p>
<div style="background:#0d0d12;border:1px solid #1e1e2e;border-left:3px solid #c9a84c;border-radius:8px;padding:24px;margin-bottom:20px">
  <div style="font-size:15px;font-weight:700;color:#f0ede6;line-height:1.5;margin-bottom:16px">{t['objet'][:150]}</div>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="color:#666;font-size:11px;padding:5px 0;width:120px">🏢 Acheteur</td><td style="color:#aaa;font-size:12px">{t.get('acheteur','—')[:70]}</td></tr>
    <tr><td style="color:#666;font-size:11px;padding:5px 0">🏷 Secteur</td><td style="color:#c9a84c;font-size:12px;font-weight:700">{t['secteur']}</td></tr>
    {'<tr><td style="color:#666;font-size:11px;padding:5px 0">💰 Montant</td><td style="color:#aaa;font-size:12px">'+t['montant']+'</td></tr>' if t.get('montant') else ''}
    <tr><td style="color:#666;font-size:11px;padding:5px 0">⏰ Date limite</td><td style="color:#e86060;font-size:12px;font-weight:700">{dl} {f'<span style="color:#c9a84c">({days})</span>' if days else ''}</td></tr>
  </table>
  <div style="margin-top:20px;display:flex;gap:10px">
    <a href="{t['url']}" style="padding:10px 20px;background:#c9a84c;color:#000;border-radius:4px;font-weight:700;text-decoration:none;font-size:12px">Voir sur marchespublics →</a>
    <a href="{SITE_URL}/tenders/{t['id']}" style="padding:10px 20px;border:1px solid #c9a84c;color:#c9a84c;border-radius:4px;font-weight:700;text-decoration:none;font-size:12px">Détails RASSD</a>
  </div>
</div>
<p style="color:#333;font-size:10px;text-align:center">RASSD · <a href="{SITE_URL}/settings" style="color:#555">Gérer mes alertes</a></p>
</div></body></html>"""

# ── SCRAPER STATE ────────────────────────────────────────
class State:
    running=False; saved=0; errors=0; logs=[]
    @classmethod
    def log(cls,m):
        e=f"[{datetime.now().strftime('%H:%M:%S')}] {m}"
        cls.logs.append(e); logger.info(m)
        if len(cls.logs)>600: cls.logs=cls.logs[-500:]

async def do_scrape():
    if State.running: return
    State.running=True; State.saved=0; State.errors=0
    State.log("═══ Scan marchespublics.gov.ma ═══")
    try:
        from realtime_scraper import run
        c=db(); known={r[0] for r in c.execute("SELECT id FROM tenders").fetchall()}; c.close()
        loop=asyncio.get_event_loop()
        tenders=await loop.run_in_executor(None, lambda: run(known, State.log))
        c=db(); new=[]
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
                    State.saved+=1; new.append(t)
            except: State.errors+=1
        c.commit(); c.close()
        State.log(f"═══ {State.saved} nouveaux marchés ═══")
        for t in new:
            try: notify_new(t)
            except: pass
        if new and ADMIN_CHAT_ID:
            tg(ADMIN_CHAT_ID, f"✅ <b>RASSD</b>\n{State.saved} nouveaux marchés")
    except Exception as e:
        State.log(f"❌ {e}"); logger.error(f"[scrape] {e}")
    finally:
        State.running=False

async def scheduler():
    await asyncio.sleep(15)
    while True:
        try: await do_scrape()
        except: pass
        await asyncio.sleep(SCAN_INTERVAL*60)

# ── APP ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    init_db(); State.log("RASSD démarré")
    asyncio.create_task(scheduler()); yield

app = FastAPI(lifespan=lifespan, title="RASSD", docs_url=None)
templates = Jinja2Templates(directory="templates")
try: app.mount("/static", StaticFiles(directory="static"), name="static")
except: pass

# ── ROUTES ───────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    c=db()
    stats={"total":c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
           "today":c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND scraped_at>=date('now')").fetchone()[0],
           "members":c.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0]}
    recent=[dict(r) for r in c.execute("SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9").fetchall()]
    sectors=[dict(r) for r in c.execute("SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 8").fetchall()]
    c.close()
    return render(req,"landing.html",{"stats":stats,"recent":recent,"sectors":sectors,"dl":days_left})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders(req: Request, q="", s="", page:int=1):
    c=db(); per=25
    w,p=["statut='actif'"],[]
    if q: w.append("(objet LIKE ? OR acheteur LIKE ?)"); p+=[f"%{q}%",f"%{q}%"]
    if s: w.append("secteur=?"); p.append(s)
    wh=" AND ".join(w)
    total=c.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}",p).fetchone()[0]
    rows=[dict(r) for r in c.execute(f"SELECT * FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",p+[per,(page-1)*per]).fetchall()]
    c.close()
    return render(req,"tenders.html",{"tenders":rows,"total":total,"page":page,"pages":(total+per-1)//per,"q":q,"sf":s,"dl":days_left})

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def detail(req: Request, tid: str):
    c=db(); t=c.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone(); c.close()
    if not t: return HTMLResponse("Introuvable",404)
    return render(req,"detail.html",{"t":dict(t),"dl":days_left})

@app.get("/register", response_class=HTMLResponse)
async def reg_get(req: Request): return render(req,"register.html",{})

@app.post("/register")
async def reg_post(req: Request, nom:str=Form(""), email:str=Form(""),
                   phone:str=Form(""), pw:str=Form(""), secteurs_sel:list=Form([])):
    if not email or not pw: return render(req,"register.html",{"err":"Email et mot de passe requis"})
    c=db()
    try:
        if c.execute("SELECT id FROM members WHERE email=?",(email,)).fetchone():
            return render(req,"register.html",{"err":"Email déjà utilisé"})
        c.execute("INSERT INTO members(nom,email,phone,pw_hash,secteurs,created_at) VALUES(?,?,?,?,?,?)",
                  (nom,email,phone,hash_pw(pw),json.dumps(secteurs_sel),datetime.now().isoformat()))
        c.commit()
    finally: c.close()
    resp=RedirectResponse("/tenders",302)
    resp.set_cookie("auth",make_token(email),max_age=86400*30,httponly=True)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request): return render(req,"login.html",{})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), pw:str=Form("")):
    c=db(); m=c.execute("SELECT * FROM members WHERE email=? AND actif=1",(email,)).fetchone(); c.close()
    if not m or not check_pw(pw,m["pw_hash"]): return render(req,"login.html",{"err":"Identifiants incorrects"})
    resp=RedirectResponse("/tenders",302)
    resp.set_cookie("auth",make_token(email),max_age=86400*30,httponly=True)
    return resp

@app.get("/logout")
async def logout():
    r=RedirectResponse("/",302); r.delete_cookie("auth"); return r

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"settings.html",{"ms":json.loads(m.get("secteurs","[]"))})

@app.post("/settings")
async def settings_post(req: Request, nom:str=Form(""), phone:str=Form(""),
                         telegram:str=Form(""), notif_email:int=Form(0),
                         notif_tg:int=Form(0), secteurs_sel:list=Form([])):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    c=db()
    c.execute("UPDATE members SET nom=?,phone=?,telegram=?,notif_email=?,notif_tg=?,secteurs=? WHERE id=?",
              (nom,phone,telegram,notif_email,notif_tg,json.dumps(secteurs_sel),m["id"]))
    c.commit(); c.close()
    return RedirectResponse("/settings?ok=1",302)

@app.get("/admin", response_class=HTMLResponse)
async def admin(req: Request, pwd:str=""):
    ck=req.cookies.get("adm","")
    if pwd!=ADMIN_PASS and ck!=ADMIN_PASS: return render(req,"admin_login.html",{})
    c=db()
    stats={"tenders":c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
           "members":c.execute("SELECT COUNT(*) FROM members").fetchone()[0],
           "notifs":c.execute("SELECT COUNT(*) FROM notif_log").fetchone()[0]}
    sects=[dict(r) for r in c.execute("SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC").fetchall()]
    c.close()
    resp=HTMLResponse(templates.get_template("admin.html").render(
        {"request":req,"stats":stats,"sects":sects,"logs":State.logs[-60:],"running":State.running}))
    resp.set_cookie("adm",ADMIN_PASS,httponly=True,max_age=86400*7)
    return resp

@app.post("/admin/login")
async def admin_login(req: Request, pwd:str=Form("")):
    if pwd!=ADMIN_PASS: return render(req,"admin_login.html",{"err":"Mot de passe incorrect"})
    r=RedirectResponse("/admin",302); r.set_cookie("adm",ADMIN_PASS,httponly=True,max_age=86400*7)
    return r

@app.get("/admin/scrape")
async def admin_scrape(req: Request, pwd:str=""):
    ck=req.cookies.get("adm","")
    if pwd!=ADMIN_PASS and ck!=ADMIN_PASS: return JSONResponse({"ok":False,"msg":"Non autorisé"},401)
    if State.running: return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok":True})

@app.get("/admin/scrape_stream")
async def stream(req: Request, pwd:str=""):
    ck=req.cookies.get("adm","")
    if pwd!=ADMIN_PASS and ck!=ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    import json as _j
    async def gen():
        last=0
        while True:
            logs=State.logs
            if len(logs)>last:
                for log in logs[last:]:
                    yield f"data: {_j.dumps({'log':log,'running':State.running,'saved':State.saved})}\n\n"
                last=len(logs)
            if not State.running and last>0:
                yield f"data: {_j.dumps({'done':True,'saved':State.saved})}\n\n"; break
            await asyncio.sleep(0.6)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/admin/expire_now")
async def expire(req: Request, pwd:str=""):
    ck=req.cookies.get("adm","")
    if pwd!=ADMIN_PASS and ck!=ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    c=db(); today=date.today(); exp=[]
    rows=c.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
    for r in rows:
        m=re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})',str(r["date_limite"]))
        if m:
            try:
                fmt="%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
                if datetime.strptime(m.group(1),fmt).date()<today: exp.append(r["id"])
            except: pass
    if exp:
        c.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join(['?']*len(exp))})",exp)
    c.commit(); active=c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]; c.close()
    return JSONResponse({"ok":True,"expired":len(exp),"active":active})

@app.get("/admin/clear_db")
async def clear(req: Request, pwd:str="", confirm:str=""):
    ck=req.cookies.get("adm","")
    if pwd!=ADMIN_PASS and ck!=ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    if confirm!="yes": return HTMLResponse('<a href="/admin/clear_db?confirm=yes">Confirmer</a>')
    c=db(); n=c.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    c.execute("DELETE FROM tenders"); c.execute("DELETE FROM notif_log"); c.commit(); c.close()
    return JSONResponse({"ok":True,"deleted":n})

@app.get("/health")
async def health():
    c=db(); n=c.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]; c.close()
    return {"status":"ok","brand":"RASSD","version":"2.0","active":n,"running":State.running}
