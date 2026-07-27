"""
ATLAS PRO v3.2 — SaaS Veille Marchés Publics Maroc
Full audit & fix — Production ready
"""
import os, re, json, secrets, asyncio, logging, hashlib
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
from app.core.security import (hash_pw, verify_pw, make_token, make_session_token,
                                get_member, validate_email,
                                validate_password, days_left)
from app.core.sectors import get_label
from app.services.notifications import dispatch_notifications, tg_admin, test_notifications

MULTI_OK = False

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
                 url,statut,scraped_at,updated_at,type_offre,source)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t["id"], t["objet"], t["acheteur"],
                 t.get("secteur",""), t.get("region",""),
                 t.get("montant",""), t.get("date_publication",""),
                 t.get("date_limite",""), t.get("description",""),
                 t["url"], t["statut"], t["scraped_at"], t["scraped_at"],
                 t.get("type_offre","Public"), t.get("source","marchespublics")))
            if db.execute("SELECT changes()").fetchone()[0]:
                saved += 1
                new_list.append(t)
        except Exception as e:
            logger.error(f"[save] {e}")
    db.commit(); db.close()
    return saved

def _save_results(results: list) -> int:
    if not results: return 0
    db = get_db(); saved = 0
    for r in results:
        try:
            db.execute("""INSERT OR IGNORE INTO tender_results
                (id,reference,objet,acheteur,adjudicataire,region,budget,montant,
                 secteur,date_adjudication,date_ouverture,date_affichage,
                 dao_url,pv_url,scraped_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], r.get("reference",""), r["objet"], r.get("acheteur",""),
                 r.get("adjudicataire",""), r.get("region",""), r.get("budget",""),
                 r.get("montant",""), r.get("secteur",""),
                 r.get("date_adjudication",""), r.get("date_ouverture",""),
                 r.get("date_affichage",""), r.get("dao_url",""), r.get("pv_url",""),
                 r["scraped_at"]))
            if db.execute("SELECT changes()").fetchone()[0]:
                saved += 1
        except Exception as e:
            logger.error(f"[save_results] {e}")
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
        State.log("  ATLAS PRO — Veille v3.2")
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
                from app.services.multi_scraper import run_all
                db     = get_db()
                known2 = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
                db.close()
                multi = await loop.run_in_executor(None, lambda: run_all(known2, State.log))
                State.found += len(multi)
                saved2 = _save_tenders(multi, new_tenders)
                State.saved += saved2
                State.log(f"✅ Multi-sources: {saved2} nouveaux")
            except Exception as e:
                State.log(f"⚠ Multi: {e}")

        # ── Marchés privés ─────────────────────────────────
        try:
            State.log("─" * 48)
            from app.services.private_scraper import run as gm_run
            db    = get_db()
            known3 = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
            db.close()
            gm_results = await loop.run_in_executor(None, lambda: gm_run(known3, State.log))
            State.found += len(gm_results)
            saved3 = _save_tenders(gm_results, new_tenders)
            State.saved += saved3
            State.log(f"✅ Marchés privés: {saved3} nouveaux")
        except Exception as e:
            State.log(f"❌ Marchés privés: {e}")
            logger.error(f"[gm scraper] {e}", exc_info=True)

        # ── Résultats des marchés (adjudications) ──────────
        try:
            State.log("─" * 48)
            from app.services.private_scraper import run_results as gm_run_results
            db      = get_db()
            known4  = {r[0] for r in db.execute("SELECT id FROM tender_results").fetchall()}
            db.close()
            gm_res  = await loop.run_in_executor(None, lambda: gm_run_results(known4, State.log))
            saved4  = _save_results(gm_res)
            State.log(f"✅ Résultats des marchés: {saved4} nouveaux")
        except Exception as e:
            State.log(f"❌ Résultats des marchés: {e}")
            logger.error(f"[gm results scraper] {e}", exc_info=True)

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
    """Ajoute les en-têtes de sécurité HTTP à chaque réponse.

    Protège contre:
    - Clickjacking (X-Frame-Options)
    - MIME sniffing (X-Content-Type-Options)
    - XSS réfléchi (X-XSS-Protection)
    - Fuite de referrer (Referrer-Policy)
    - HTTP downgrade (Strict-Transport-Security)
    """
    async def dispatch(self, req, call_next):
        resp = await call_next(req)
        resp.headers.update({
            "X-Content-Type-Options":    "nosniff",
            "X-Frame-Options":           "DENY",
            "X-XSS-Protection":          "1; mode=block",
            "Referrer-Policy":           "strict-origin-when-cross-origin",
            "Permissions-Policy":        "geolocation=(), microphone=(), camera=()",
            # Force HTTPS pour 1 an sur ce domaine et ses sous-domaines
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
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

@app.exception_handler(404)
async def not_found(req: Request, exc):
    return render(req, "404.html", {}, status_code=404)

@app.exception_handler(500)
async def server_error(req: Request, exc):
    logger.error(f"[500] {req.url}: {exc}")
    return HTMLResponse("""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Erreur serveur — Atlas Pro</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f6f7fb;color:#3b4457;font-family:'Inter',system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px}
.num{font-weight:800;font-size:96px;color:#f2a93b;line-height:.85}
h1{font-weight:800;font-size:28px;color:#101828;margin:16px 0}
p{font-size:16px;color:#6b7488;margin-bottom:32px}
a{display:inline-flex;align-items:center;justify-content:center;padding:13px 26px;background:#142850;color:#fff;font-weight:600;font-size:14px;border-radius:10px;text-decoration:none}
</style></head><body><div>
<div class="num">500</div>
<h1>Une erreur est survenue</h1>
<p>Notre équipe a été notifiée. Merci de réessayer dans un instant.</p>
<a href="/">Retour à l'accueil →</a>
</div></body></html>""", 500)
def source_label(source: str) -> str:
    """Libellé affichable pour la source d'un marché.

    N'expose jamais le nom du fournisseur de données des marchés privés —
    seul le nom du portail public officiel est communiqué.
    """
    if source == "marchespublics":
        return "marchespublics.gov.ma"
    return ""

templates = Jinja2Templates(directory="templates")
templates.env.globals["get_label"] = get_label
templates.env.globals["source_label"] = source_label
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except OSError as e:
    logger.warning(f"[static] Impossible de monter /static: {e}")

# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
def render(req: Request, tpl: str, ctx: dict = None, status_code: int = 200):
    m   = get_member(req)
    ctx = ctx or {}
    return templates.TemplateResponse(tpl, {
        "request":   req,  "member":   m,
        "cfg":          cfg,
        "secteurs":     cfg.SECTEURS,
        "sector_groups": cfg.SECTOR_GROUPS,
        "plans":        cfg.PLANS,
        "dl":           days_left,
        "days_left":    days_left,
        "now":          datetime.now(),
        **ctx
    }, status_code=status_code)

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
            except ValueError:
                # Date mal formée, on skip sans crasher
                pass
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
    # Le détail des marchés (objet, acheteur...) est réservé aux membres —
    # les visiteurs anonymes ne voient qu'un aperçu générique (voir landing.html).
    member  = get_member(req)
    recent  = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9").fetchall()] if member else []
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 12").fetchall()]
    db.close()
    return render(req, "landing.html", {"stats":stats,"recent":recent,"sectors":sectors})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, q:str="", s:str="", r:str="", t:str="",
                        page:int=1, sort:str="recent"):
    if not get_member(req):
        return RedirectResponse("/login?next=/tenders", 302)
    db = get_db(); per = 25; page = max(1, page)
    where, params = ["statut='actif'"], []
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
        params += [f"%{q}%"]*3
    if s: where.append("secteur=?");    params.append(s)
    if r: where.append("region=?");     params.append(r)
    if t: where.append("type_offre=?"); params.append(t)
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
        "q":q,"sf":s,"rf":r,"tf":t,"sort":sort,"favs":favs})

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    if not get_member(req):
        return RedirectResponse("/login?next=/tenders/" + tid, 302)
    db = get_db()
    t  = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if not t:
        db.close()
        return HTMLResponse("Marché introuvable", 404)
    try:
        db.execute("UPDATE tenders SET views=views+1 WHERE id=?", (tid,))
    except Exception as e:
        logger.warning(f"[views] {e}")
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
        except Exception as e:
            logger.warning(f"[is_fav] {e}")
    try:
        db.commit()
    except Exception as e:
        logger.warning(f"[commit] {e}")
    db.close()
    return render(req, "detail.html", {"t":dict(t),"related":related,"is_fav":is_fav})

@app.get("/tenders/{tid}/source")
async def tender_source_redirect(req: Request, tid: str):
    """Redirige vers la source d'origine sans jamais exposer son nom/domaine
    dans le HTML de la page (uniquement dans l'en-tête Location de la 302)."""
    if not get_member(req):
        return RedirectResponse("/login?next=/tenders/" + tid, 302)
    db = get_db()
    t  = db.execute("SELECT url FROM tenders WHERE id=?", (tid,)).fetchone()
    db.close()
    if not t or not t["url"]:
        return RedirectResponse("/tenders/" + tid, 302)
    return RedirectResponse(t["url"], 302)

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

@app.get("/resultats", response_class=HTMLResponse)
async def resultats_page(req: Request, q:str="", page:int=1):
    if not get_member(req):
        return RedirectResponse("/login?next=/resultats", 302)
    db = get_db(); per = 25; page = max(1, page)
    where, params = ["1=1"], []
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR adjudicataire LIKE ?)")
        params += [f"%{q}%"]*3
    wh    = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tender_results WHERE {wh}", params).fetchone()[0]
    rows  = [dict(x) for x in db.execute(
        f"SELECT * FROM tender_results WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
        params+[per,(page-1)*per]).fetchall()]
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "resultats.html", {
        "resultats":rows,"total":total,"page":page,"pages":pages,"q":q})

@app.get("/resultats/{rid}/{doc}")
async def resultat_doc_redirect(req: Request, rid: str, doc: str):
    """Redirige vers le document (D.A.O/PV) sans exposer sa source dans le HTML."""
    if not get_member(req):
        return RedirectResponse("/login?next=/resultats", 302)
    if doc not in ("dao", "pv"):
        return RedirectResponse("/resultats", 302)
    db = get_db()
    r  = db.execute("SELECT dao_url, pv_url FROM tender_results WHERE id=?", (rid,)).fetchone()
    db.close()
    url = (r["dao_url"] if doc == "dao" else r["pv_url"]) if r else ""
    if not url:
        return RedirectResponse("/resultats", 302)
    return RedirectResponse(url, 302)

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
        sects       = clean_secteurs(secteurs_sel)
        trial_ends  = (datetime.now()+timedelta(days=14)).strftime("%Y-%m-%d")
        created_at  = datetime.now().isoformat()
        session_tok = make_session_token()
        db.execute(
            "INSERT INTO members(nom,email,phone,company,pw_hash,secteurs,plan,created_at,trial_ends,session_token) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (nom,email,phone,company,hash_pw(pw),json.dumps(sects),"free",created_at,trial_ends,session_tok))
        db.commit()
    finally: db.close()
    resp = RedirectResponse("/dashboard?welcome=1",302)
    resp.set_cookie("_session", session_tok,
                    max_age=86400*30, httponly=True, samesite="lax")
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
    session_tok = make_session_token()
    db.execute("UPDATE members SET last_login=?, session_token=? WHERE id=?",
               (datetime.now().isoformat(), session_tok, m["id"]))
    db.commit(); db.close()
    onboarded = m["onboarded"] if "onboarded" in m.keys() else 1
    logger.info(f"[Login] ✅ {email} connecté")
    dest = next or ("/dashboard?welcome=1" if not onboarded else "/dashboard")
    resp = RedirectResponse(dest, 302)
    resp.set_cookie("_session", session_tok,
                    max_age=86400*30, httponly=True, samesite="lax")
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
    n_wa     = 1 if form.get("notif_wa")     else 0
    whatsapp = form.get("whatsapp","").strip()
    sects    = clean_secteurs(secteurs_sel)
    db = get_db()
    try:
        db.execute(
            "UPDATE members SET nom=?,phone=?,company=?,telegram=?,whatsapp=?,notif_email=?,notif_tg=?,notif_wa=?,notif_digest=?,secteurs=? WHERE id=?",
            (nom,phone,company,telegram.strip(),whatsapp,n_email,n_tg,n_wa,n_digest,json.dumps(sects),member["id"]))
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
        return JSONResponse({"ok":False,"msg":"Veille déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok":True,"msg":"Veille lancée"})

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
async def admin_test_notif(req: Request, email:str="", tg:str="", wa:str=""):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    member    = get_member(req)
    test_email = email or (member["email"] if member else "")
    test_tg    = tg or cfg.ADMIN_CHAT_ID or ""
    test_wa    = wa or (member["whatsapp"] if member else "")
    results    = test_notifications(test_email, test_tg, test_wa)
    return JSONResponse({"ok":True,"results":results,"email_tested":test_email,"tg_tested":test_tg,"wa_tested":test_wa})

@app.get("/admin/reset_state")
async def admin_reset(req: Request):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    State.running = False; State.logs = []
    return JSONResponse({"ok":True,"msg":"State réinitialisé"})

# ══════════════════════════════════════════════════════════
# API v1
# ══════════════════════════════════════════════════════════
@app.get("/api/v1/tenders")
async def api_tenders(req:Request, secteur:str="", region:str="", q:str="", type_offre:str="",
                       limit:int=20, offset:int=0, page:int=0):
    if not get_member(req):
        return JSONResponse({"ok":False,"msg":"Réservé aux membres — connectez-vous"},401)
    if page > 0: offset = (page-1)*limit
    db = get_db()
    where, params = ["statut='actif'"], []
    if secteur:    where.append("secteur=?");    params.append(secteur)
    if region:     where.append("region=?");     params.append(region)
    if type_offre: where.append("type_offre=?"); params.append(type_offre)
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ?)")
        params += [f"%{q}%"]*2
    wh    = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(r) for r in db.execute(
        f"SELECT id,objet,acheteur,secteur,region,montant,date_limite,url,scraped_at,type_offre,source FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
        params+[min(limit,100),offset]).fetchall()]
    db.close()
    return {"ok":True,"total":total,"page":page or (offset//limit+1),"results":rows}

@app.get("/api/v1/tenders/{tid}")
async def api_tender(req:Request, tid:str):
    if not get_member(req):
        return JSONResponse({"ok":False,"msg":"Réservé aux membres — connectez-vous"},401)
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
    return {"ok":True,"total":len(sources),"sources":sources}

# ══════════════════════════════════════════════════════════
# PASSWORD RESET
# ══════════════════════════════════════════════════════════
@app.get("/forgot", response_class=HTMLResponse)
async def forgot_get(req: Request):
    return render(req, "forgot.html", {})

@app.post("/forgot")
async def forgot_post(req: Request, email: str = Form("")):
    db = get_db()
    m  = db.execute("SELECT * FROM members WHERE email=? AND actif=1", (email,)).fetchone()
    if m:
        token      = secrets.token_urlsafe(32)
        expires    = (datetime.now() + timedelta(hours=2)).isoformat()
        db.execute("UPDATE members SET reset_token=?, reset_expires=? WHERE id=?",
                   (token, expires, m["id"]))
        db.commit()
        reset_url = f"{cfg.SITE_URL}/reset?token={token}"
        # Send reset email — hors du thread de la requête pour ne jamais
        # bloquer le serveur si un provider (ex: SMTP filtré par l'hébergeur) est lent.
        try:
            from app.services.notifications import email_send
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, lambda: email_send(
                email, "Réinitialisation de votre mot de passe — ATLAS PRO",
                f"""<h2>Réinitialisation de mot de passe</h2>
                <p>Cliquez sur le lien ci-dessous pour réinitialiser votre mot de passe:</p>
                <a href="{reset_url}" style="display:inline-block;padding:12px 24px;background:#f2a93b;color:#142850;border-radius:8px;text-decoration:none;font-weight:600">
                  Réinitialiser mon mot de passe →
                </a>
                <p style="color:#666;font-size:12px;margin-top:16px">Ce lien expire dans 2 heures.</p>"""))
        except Exception as e:
            logger.error(f"[reset email] {e}")
        db.close()
    return render(req, "forgot.html", {"sent": True})

@app.get("/reset", response_class=HTMLResponse)
async def reset_get(req: Request, token: str = ""):
    db  = get_db()
    m   = db.execute("SELECT * FROM members WHERE reset_token=?", (token,)).fetchone()
    db.close()
    if not m or not m["reset_token"]:
        return render(req, "reset.html", {"err": "Lien invalide ou expiré"})
    if datetime.fromisoformat(m["reset_expires"] or "2000-01-01") < datetime.now():
        return render(req, "reset.html", {"err": "Ce lien a expiré. Faites une nouvelle demande."})
    return render(req, "reset.html", {"token": token})

@app.post("/reset")
async def reset_post(req: Request, token: str = Form(""),
                     pw: str = Form(""), pw2: str = Form("")):
    if pw != pw2:
        return render(req, "reset.html", {"token": token, "err": "Les mots de passe ne correspondent pas"})
    if len(pw) < 8:
        return render(req, "reset.html", {"token": token, "err": "Minimum 8 caractères"})
    db = get_db()
    m  = db.execute("SELECT * FROM members WHERE reset_token=?", (token,)).fetchone()
    if not m or not m["reset_token"]:
        db.close()
        return render(req, "reset.html", {"err": "Lien invalide"})
    if datetime.fromisoformat(m["reset_expires"] or "2000-01-01") < datetime.now():
        db.close()
        return render(req, "reset.html", {"err": "Ce lien a expiré. Faites une nouvelle demande."})
    db.execute("UPDATE members SET pw_hash=?, reset_token='', reset_expires='', session_token='' WHERE id=?",
               (hash_pw(pw), m["id"]))
    db.commit(); db.close()
    return RedirectResponse("/login?reset=1", 302)

# ══════════════════════════════════════════════════════════
# FEEDBACK
# ══════════════════════════════════════════════════════════
@app.get("/feedback", response_class=HTMLResponse)
async def feedback_get(req: Request):
    return render(req, "feedback.html", {})

@app.post("/feedback")
async def feedback_post(req: Request,
    message:  str  = Form(""),
    rating:   int  = Form(0),
    features: list = Form(default=[])):
    member = get_member(req)
    db = get_db()
    db.execute(
        "INSERT INTO feedback(member_id,email,message,features,rating,created_at) VALUES(?,?,?,?,?,?)",
        (member["id"] if member else None,
         member["email"] if member else "",
         message, json.dumps(features), rating,
         datetime.now().isoformat()))
    db.commit(); db.close()
    # Notify admin
    try:
        from app.services.notifications import tg_admin
        stars = "⭐" * rating
        tg_admin(f"📝 Nouveau feedback {stars}\n\n{message[:300]}\n\nFonctionnalités: {', '.join(features)}")
    except Exception as e:
        logger.warning(f"[feedback] Notification admin échouée: {e}")
    return RedirectResponse("/feedback?ok=1", 302)

# ══════════════════════════════════════════════════════════
# WHATSAPP STATUS (admin)
# ══════════════════════════════════════════════════════════
@app.get("/admin/wa_status")
async def wa_status(req: Request):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    try:
        from app.services.whatsapp import wa_connected
        return JSONResponse({"ok": True, "connected": wa_connected()})
    except ImportError:
        # Service WhatsApp pas installé
        return JSONResponse({"ok": True, "connected": False})
    except Exception as e:
        logger.warning(f"[wa_status] {e}")
        return JSONResponse({"ok": True, "connected": False})


# ══════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    db  = get_db()
    act = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return {"status":"ok","version":cfg.APP_VERSION,"brand":cfg.APP_NAME,
            "active":act,"running":State.running,"last_run":State.last_run,
            "multi_scraper":False}

@app.get("/sitemap.xml")
async def sitemap():
    # Les marchés sont réservés aux membres — on ne référence ici que les
    # pages publiques, pas les fiches individuelles (inutile pour le SEO
    # puisqu'elles redirigent vers /login, et ça évite d'exposer les IDs).
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{cfg.SITE_URL}/</loc></url>
  <url><loc>{cfg.SITE_URL}/tarifs</loc></url>
  <url><loc>{cfg.SITE_URL}/login</loc></url>
  <url><loc>{cfg.SITE_URL}/register</loc></url>
</urlset>"""
    return Response(xml, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nSitemap: {cfg.SITE_URL}/sitemap.xml\n",
                    media_type="text/plain")
