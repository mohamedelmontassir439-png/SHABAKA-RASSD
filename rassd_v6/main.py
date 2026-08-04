"""
MAROC ENTREPRENEURIAT v3.2 — SaaS Veille Marchés Publics Maroc
Full audit & fix — Production ready
"""
import os, re, json, secrets, asyncio, logging, hashlib, csv, io, traceback
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from collections import defaultdict
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import (HTMLResponse, RedirectResponse,
                               JSONResponse, StreamingResponse, Response, FileResponse)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config   import cfg
from app.core.database import get_db, init_db
from app.core.security import (hash_pw, verify_pw, make_token, make_session_token,
                                get_member, has_access, validate_email,
                                validate_password, days_left,
                                get_csrf_token, verify_csrf)
from app.core.sectors import get_label
from app.core.i18n import get_lang, make_t, SUPPORTED_LANGS, tr as tr_
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
    """IP réelle du client pour le rate-limiting.

    X-Forwarded-For est une liste où chaque proxy AJOUTE l'adresse qu'il a
    observée à la fin — le premier élément est donc fourni par le client et
    falsifiable à volonté (contournerait le rate-limit en changeant sa valeur
    à chaque requête). Seul le DERNIER élément (ajouté par le proxy Railway,
    le plus proche de nous) est fiable.
    """
    xff = req.headers.get("x-forwarded-for", "")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return req.client.host if req.client else "unknown"

# Cookies "Secure" en production (HTTPS) — désactivé seulement si SITE_URL
# est en http:// (dev local), sinon un cookie Secure serait simplement
# jamais envoyé et casserait les tests locaux.
COOKIE_SECURE = cfg.SITE_URL.startswith("https")

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
                 url,statut,scraped_at,updated_at,type_offre,source,type_procedure)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t["id"], t["objet"], t["acheteur"],
                 t.get("secteur",""), t.get("region",""),
                 t.get("montant",""), t.get("date_publication",""),
                 t.get("date_limite",""), t.get("description",""),
                 t["url"], t["statut"], t["scraped_at"], t["scraped_at"],
                 t.get("type_offre","Public"), t.get("source","marchespublics"),
                 t.get("type_procedure","marche")))
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
                 dao_url,pv_url,scraped_at,type_procedure)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], r.get("reference",""), r["objet"], r.get("acheteur",""),
                 r.get("adjudicataire",""), r.get("region",""), r.get("budget",""),
                 r.get("montant",""), r.get("secteur",""),
                 r.get("date_adjudication",""), r.get("date_ouverture",""),
                 r.get("date_affichage",""), r.get("dao_url",""), r.get("pv_url",""),
                 r["scraped_at"], r.get("type_procedure","marche")))
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
        State.log("  MAROC ENTREPRENEURIAT — Veille v3.2")
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

        # ── Bons de commande ────────────────────────────────
        try:
            State.log("─" * 48)
            from app.services.private_scraper import run_bc as gm_run_bc
            db      = get_db()
            known5  = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
            db.close()
            bc_results = await loop.run_in_executor(None, lambda: gm_run_bc(known5, State.log))
            State.found += len(bc_results)
            saved5 = _save_tenders(bc_results, new_tenders)
            State.saved += saved5
            State.log(f"✅ Bons de commande: {saved5} nouveaux")
        except Exception as e:
            State.log(f"❌ Bons de commande: {e}")
            logger.error(f"[bc scraper] {e}", exc_info=True)

        # ── Résultats des bons de commande ──────────────────
        try:
            State.log("─" * 48)
            from app.services.private_scraper import run_bc_results as gm_run_bc_results
            db      = get_db()
            known6  = {r[0] for r in db.execute("SELECT id FROM tender_results").fetchall()}
            db.close()
            bc_res  = await loop.run_in_executor(None, lambda: gm_run_bc_results(known6, State.log))
            saved6  = _save_results(bc_res)
            State.log(f"✅ Résultats des bons de commande: {saved6} nouveaux")
        except Exception as e:
            State.log(f"❌ Résultats des bons de commande: {e}")
            logger.error(f"[bc results scraper] {e}", exc_info=True)

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

async def digest_scheduler():
    """Vérifie toutes les heures s'il faut envoyer le récapitulatif hebdomadaire
    (lundi) — send_weekly_digests() est idempotent (last_digest_sent par membre)
    donc plusieurs passages le même lundi ne renvoient rien en double."""
    from app.services.notifications import send_weekly_digests
    await asyncio.sleep(60)
    while True:
        try:
            loop = asyncio.get_event_loop()
            sent = await loop.run_in_executor(None, send_weekly_digests)
            if sent: logger.info(f"[digest] {sent} récapitulatif(s) envoyé(s)")
        except Exception as e:
            logger.error(f"[digest_scheduler] {e}")
        await asyncio.sleep(3600)

BACKUP_DIR  = "data/backups"
BACKUP_KEEP = 14

def make_db_backup():
    """Copie la base SQLite dans data/backups/ (protège contre un bug
    applicatif qui corromprait/effacerait des lignes en base) et purge les
    sauvegardes au-delà de BACKUP_KEEP. Ne protège pas contre la perte du
    volume Railway lui-même — /admin/backups permet un téléchargement
    manuel pour garder une copie hors-site."""
    import shutil
    if not os.path.exists(cfg.DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"atlas_{ts}.db")
    shutil.copy2(cfg.DB_PATH, dest)
    backups = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("atlas_") and f.endswith(".db"))
    while len(backups) > BACKUP_KEEP:
        try: os.remove(os.path.join(BACKUP_DIR, backups.pop(0)))
        except OSError: pass
    return dest

async def backup_scheduler():
    await asyncio.sleep(90)
    while True:
        try:
            loop = asyncio.get_event_loop()
            path = await loop.run_in_executor(None, make_db_backup)
            if path: logger.info(f"[backup] ✅ {path}")
        except Exception as e:
            logger.error(f"[backup_scheduler] {e}")
        await asyncio.sleep(86400)

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
            # unsafe-inline requis: les pages utilisent des <style>/<script>
            # inline plutôt que des fichiers externes — bloque au moins tout
            # chargement de script/style/frame depuis un domaine non listé.
            "Content-Security-Policy": (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "script-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            ),
        })
        return resp

def csrf_guard(req: Request, csrf_token: str = ""):
    """Vérification CSRF appelée en première ligne de chaque route POST.

    Implémentée route-par-route plutôt qu'en middleware: un BaseHTTPMiddleware
    qui lit await req.form() consomme le flux ASGI une seule fois — la
    ré-lecture par les paramètres Form(...) de la route en aval revient alors
    vide (bug constaté en test: connexion/inscription cassées). Vérifier
    directement dans la route, après que FastAPI a déjà parsé le formulaire,
    évite ce piège.
    """
    if not verify_csrf(req, csrf_token):
        raise HTTPException(status_code=403, detail="Session expirée — merci de rafraîchir la page et réessayer.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    State.log(f"MAROC ENTREPRENEURIAT v{cfg.APP_VERSION} | Multi-source: {'✅' if MULTI_OK else '❌'}")
    if cfg.WA_SECRET == "atlas_wa_secret_2024":
        logger.warning("[startup] WA_SECRET utilise sa valeur par défaut — configure-la dans les variables d'environnement Railway.")
    asyncio.create_task(scheduler())
    asyncio.create_task(digest_scheduler())
    asyncio.create_task(backup_scheduler())
    yield

app = FastAPI(lifespan=lifespan, title=cfg.APP_NAME,
              version=cfg.APP_VERSION, docs_url=None, redoc_url=None)
app.add_middleware(SecurityMiddleware)

@app.exception_handler(404)
async def not_found(req: Request, exc):
    return render(req, "404.html", {}, status_code=404)

def _server_error_html() -> str:
    return """<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Erreur serveur — Maroc Entrepreneuriat</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f6f7fb;color:#3b4457;font-family:'Inter',system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px}
.num{font-weight:800;font-size:96px;color:#f2662d;line-height:.85}
h1{font-weight:800;font-size:28px;color:#2b211b;margin:16px 0}
p{font-size:16px;color:#8a7a6a;margin-bottom:32px}
a{display:inline-flex;align-items:center;justify-content:center;padding:13px 26px;background:#1e1611;color:#fff;font-weight:600;font-size:14px;border-radius:10px;text-decoration:none}
</style></head><body><div>
<div class="num">500</div>
<h1>Une erreur est survenue</h1>
<p>Notre équipe a été notifiée. Merci de réessayer dans un instant.</p>
<a href="/">Retour à l'accueil →</a>
</div></body></html>"""

@app.exception_handler(500)
async def server_error(req: Request, exc):
    logger.error(f"[500] {req.url}: {exc}")
    return HTMLResponse(_server_error_html(), 500)

@app.exception_handler(Exception)
async def unhandled_exception_handler(req: Request, exc: Exception):
    """Filet de sécurité pour toute exception Python non gérée explicitement
    (@app.exception_handler(500) ne couvre que les HTTPException(500) levées
    volontairement — sans ce handler, un bug applicatif imprévu remontait
    jusqu'à la page d'erreur générique non brandée de Starlette)."""
    logger.error(f"[unhandled] {req.method} {req.url.path}: {exc}", exc_info=True)
    try:
        db = get_db()
        db.execute(
            "INSERT INTO error_log(path,method,message,traceback,created_at) VALUES (?,?,?,?,?)",
            (str(req.url.path), req.method, str(exc)[:500], traceback.format_exc()[:4000], datetime.now().isoformat()))
        db.commit(); db.close()
    except Exception as log_err:
        logger.error(f"[error_log] échec d'enregistrement: {log_err}")
    return HTMLResponse(_server_error_html(), 500)

def source_label(source: str, lang: str = "fr") -> str:
    """Libellé affichable pour la source d'un marché.

    Le portail public officiel est nommé directement. Pour les marchés
    privés, on n'expose jamais le nom du prestataire de données brut —
    seulement une attribution générique, jamais vide.
    """
    if source == "marchespublics":
        return "marchespublics.gov.ma"
    if source == "global-marches":
        return tr_("source_private_platform", lang)
    return tr_("source_private_platform", lang) if source else ""

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
    m    = get_member(req)
    ctx  = ctx or {}
    lang = get_lang(req)
    dl_bound = lambda val: days_left(val, lang)
    src_bound = lambda val: source_label(val, lang)
    csrf_tok = get_csrf_token(req) or secrets.token_urlsafe(24)
    resp = templates.TemplateResponse(tpl, {
        "request":   req,  "member":   m,
        "cfg":          cfg,
        "secteurs":     cfg.SECTEURS,
        "sector_groups": cfg.SECTOR_GROUPS,
        "plans":        cfg.PLANS,
        "dl":           dl_bound,
        "days_left":    dl_bound,
        "source_label": src_bound,
        "now":          datetime.now(),
        "lang":         lang,
        "dir":          "rtl" if lang == "ar" else "ltr",
        "tr":           make_t(lang),
        "csrf_token":   csrf_tok,
        **ctx
    }, status_code=status_code)
    if req.query_params.get("lang") in SUPPORTED_LANGS:
        resp.set_cookie("lang", lang, max_age=86400*365, samesite="lax", secure=COOKIE_SECURE)
    if not req.cookies.get("_csrf"):
        resp.set_cookie("_csrf", csrf_tok, max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

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
    # Le détail des marchés (objet, acheteur...) est réservé aux membres dont
    # l'abonnement a été activé par l'admin — les visiteurs anonymes ET les
    # membres en attente d'activation ne voient qu'un aperçu générique (landing.html).
    member  = get_member(req)
    recent  = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9").fetchall()] if has_access(member) else []
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 12").fetchall()]
    db.close()
    return render(req, "landing.html", {"stats":stats,"recent":recent,"sectors":sectors})

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, q:str="", s:str="", r:str="", t:str="",
                        page:int=1, sort:str="recent"):
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/tenders", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db(); per = 25; page = max(1, page)
    # Les bons de commande sont une procédure distincte, gérée sur sa propre
    # page (/bons-de-commande) — jamais mélangés ici, quel que soit le filtre.
    regions = [row[0] for row in db.execute(
        "SELECT DISTINCT region FROM tenders WHERE region!='' AND statut='actif' AND type_procedure!='bon_commande' ORDER BY region LIMIT 60").fetchall()]
    where, params = ["statut='actif'", "type_procedure!='bon_commande'"], []
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
    favs = {x[0] for x in db.execute(
        "SELECT tender_id FROM favorites WHERE member_id=?", (m0["id"],)).fetchall()}
    my_secteurs = clean_secteurs(json.loads(m0.get("secteurs","[]") or "[]"))
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "tenders.html", {
        "tenders":rows,"total":total,"page":page,"pages":pages,
        "q":q,"sf":s,"rf":r,"tf":t,"sort":sort,"favs":favs,"regions":regions,
        "my_secteurs":my_secteurs})

@app.get("/bons-de-commande", response_class=HTMLResponse)
async def bons_commande_page(req: Request, q:str="", s:str="", r:str="",
                              page:int=1, sort:str="recent"):
    # Page dédiée et totalement séparée des marchés classiques — les bons de
    # commande sont une procédure d'achat public simplifiée (voir bc_intro),
    # sans équivalent privé, donc pas de filtre Public/Privé ici.
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/bons-de-commande", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db(); per = 25; page = max(1, page)
    regions = [row[0] for row in db.execute(
        "SELECT DISTINCT region FROM tenders WHERE region!='' AND statut='actif' AND type_procedure='bon_commande' ORDER BY region LIMIT 60").fetchall()]
    where, params = ["statut='actif'", "type_procedure='bon_commande'"], []
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
    favs = {x[0] for x in db.execute(
        "SELECT tender_id FROM favorites WHERE member_id=?", (m0["id"],)).fetchall()}
    my_secteurs = clean_secteurs(json.loads(m0.get("secteurs","[]") or "[]"))
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "bons_commande.html", {
        "tenders":rows,"total":total,"page":page,"pages":pages,
        "q":q,"sf":s,"rf":r,"sort":sort,"favs":favs,"regions":regions,
        "my_secteurs":my_secteurs})

@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/tenders/" + tid, 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
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
        "SELECT * FROM tenders WHERE secteur=? AND id!=? AND statut='actif' AND type_procedure=? ORDER BY scraped_at DESC LIMIT 4",
        (secteur, tid, t["type_procedure"] or "marche")).fetchall()] if secteur else []
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
    """Ne redirige jamais vers un prestataire de données tiers (ex. global-
    marches.com) — seul le portail officiel marchespublics.gov.ma peut être
    montré tel quel, puisqu'il est déjà public par nature. Pour toute autre
    source, on revient sur notre propre page de détail plutôt que d'exposer
    le domaine d'origine dans la barre d'adresse du navigateur."""
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/tenders/" + tid, 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db()
    t  = db.execute("SELECT url, source FROM tenders WHERE id=?", (tid,)).fetchone()
    db.close()
    if not t or not t["url"] or t["source"] != "marchespublics":
        return RedirectResponse("/tenders/" + tid, 302)
    return RedirectResponse(t["url"], 302)

@app.post("/tenders/{tid}/favorite")
async def toggle_fav(req: Request, tid: str):
    member = get_member(req)
    if not member: return JSONResponse({"ok":False,"msg":"Non connecté"},401)
    if not verify_csrf(req, ""): return JSONResponse({"ok":False,"msg":"Session expirée"},403)
    if not has_access(member): return JSONResponse({"ok":False,"msg":"Abonnement requis"},403)
    if not check_rate_limit(f"fav_{member['id']}", 60, 300):
        return JSONResponse({"ok":False,"msg":"Trop de requêtes, patientez un instant"},429)
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
    if not has_access(member): return RedirectResponse("/tarifs?locked=1",302)
    db   = get_db()
    rows = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t JOIN favorites f ON f.tender_id=t.id
           WHERE f.member_id=? ORDER BY f.created_at DESC""",
        (member["id"],)).fetchall()]
    db.close()
    return render(req,"favorites.html",{"tenders":rows})

@app.get("/resultats", response_class=HTMLResponse)
async def resultats_page(req: Request, q:str="", page:int=1):
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/resultats", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
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
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/resultats", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    if doc not in ("dao", "pv"):
        return RedirectResponse("/resultats", 302)
    db = get_db()
    r  = db.execute("SELECT dao_url, pv_url FROM tender_results WHERE id=?", (rid,)).fetchone()
    db.close()
    url = (r["dao_url"] if doc == "dao" else r["pv_url"]) if r else ""
    if not url:
        return RedirectResponse("/resultats", 302)
    return RedirectResponse(url, 302)

# ══════════════════════════════════════════════════════════
# SOUS-TRAITANCE — annonces entre membres (demande / offre)
# avec messagerie interne, réservé aux membres actifs (has_access)
# ══════════════════════════════════════════════════════════
@app.get("/sous-traitance", response_class=HTMLResponse)
async def subtraitance_list(req: Request, tp:str="", s:str="", r:str="", mine:str="", page:int=1):
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/sous-traitance", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db(); per = 20; page = max(1, page)
    where, params = ["statut='actif'"], []
    if tp in ("demande","offre"): where.append("type=?"); params.append(tp)
    if s: where.append("secteur=?"); params.append(s)
    if r: where.append("region=?"); params.append(r)
    if mine: where = ["member_id=?"]; params = [m0["id"]]
    wh = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM subcontract_posts WHERE {wh}", params).fetchone()[0]
    rows  = [dict(x) for x in db.execute(
        f"SELECT * FROM subcontract_posts WHERE {wh} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params+[per,(page-1)*per]).fetchall()]
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "subtraitance.html", {
        "posts":rows,"total":total,"page":page,"pages":pages,"tf":tp,"sf":s,"rf":r,"mine":mine})

@app.get("/sous-traitance/nouveau", response_class=HTMLResponse)
async def subtraitance_new_get(req: Request):
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/sous-traitance/nouveau", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    return render(req, "subtraitance_new.html", {})

@app.post("/sous-traitance/nouveau")
async def subtraitance_new_post(req: Request, type:str=Form("demande"), titre:str=Form(""),
                                 secteur:str=Form(""), region:str=Form(""), budget:str=Form(""),
                                 date_limite:str=Form(""), description:str=Form(""), csrf_token:str=Form("")):
    m0 = get_member(req)
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login?next=/sous-traitance/nouveau", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    if not check_rate_limit(f"st_new_{m0['id']}", 10, 3600):
        return render(req, "subtraitance_new.html", {"err": tr_("err_too_many_generic", lang)})
    if not titre.strip() or not description.strip():
        return render(req, "subtraitance_new.html", {"err": tr_("st_err_required", lang)})
    db  = get_db()
    pid = "st_" + secrets.token_urlsafe(8)
    db.execute("""INSERT INTO subcontract_posts
                  (id,member_id,type,titre,secteur,region,budget,date_limite,description,statut,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (pid, m0["id"], type if type in ("demande","offre") else "demande",
                titre.strip()[:200], secteur, region, budget.strip()[:100], date_limite,
                description.strip()[:4000], "actif", datetime.now().isoformat()))
    db.commit(); db.close()
    return RedirectResponse(f"/sous-traitance/{pid}?ok=1", 302)

@app.get("/sous-traitance/{pid}", response_class=HTMLResponse)
async def subtraitance_detail(req: Request, pid: str, with_:str=""):
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/sous-traitance/" + pid, 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    other_id = req.query_params.get("with", "")
    db = get_db()
    post = db.execute("SELECT * FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if not post:
        db.close()
        return HTMLResponse("Annonce introuvable", 404)
    post     = dict(post)
    author   = db.execute("SELECT id,nom,company,email FROM members WHERE id=?", (post["member_id"],)).fetchone()
    is_owner = m0["id"] == post["member_id"]
    threads, thread_messages = [], []
    if is_owner:
        others = db.execute(
            "SELECT DISTINCT sender_id AS oid FROM subcontract_messages WHERE post_id=? AND sender_id!=?",
            (pid, m0["id"])).fetchall()
        other_ids = [o["oid"] for o in others]
        if other_ids:
            ph = ",".join(["?"]*len(other_ids))
            threads = [dict(x) for x in db.execute(
                f"SELECT id,nom,company FROM members WHERE id IN ({ph})", other_ids).fetchall()]
        if other_id:
            thread_messages = [dict(x) for x in db.execute(
                "SELECT * FROM subcontract_messages WHERE post_id=? AND (sender_id=? OR recipient_id=?) ORDER BY created_at ASC",
                (pid, other_id, other_id)).fetchall()]
            db.execute(
                "UPDATE subcontract_messages SET read_at=? WHERE post_id=? AND sender_id=? AND recipient_id=? AND read_at=''",
                (datetime.now().isoformat(), pid, other_id, m0["id"]))
            db.commit()
    else:
        thread_messages = [dict(x) for x in db.execute(
            "SELECT * FROM subcontract_messages WHERE post_id=? AND (sender_id=? OR recipient_id=?) ORDER BY created_at ASC",
            (pid, m0["id"], m0["id"])).fetchall()]
        db.execute(
            "UPDATE subcontract_messages SET read_at=? WHERE post_id=? AND sender_id=? AND recipient_id=? AND read_at=''",
            (datetime.now().isoformat(), pid, post["member_id"], m0["id"]))
        db.commit()
    counterpart_id = int(other_id) if (is_owner and other_id) else (post["member_id"] if not is_owner else 0)
    counterpart_rating, my_rating_given = None, 0
    if counterpart_id:
        rr = db.execute(
            "SELECT AVG(rating) avg_r, COUNT(*) n FROM subcontract_ratings WHERE rated_id=?",
            (counterpart_id,)).fetchone()
        if rr and rr["n"]:
            counterpart_rating = {"avg": round(rr["avg_r"], 1), "n": rr["n"]}
        mine = db.execute(
            "SELECT rating FROM subcontract_ratings WHERE post_id=? AND rater_id=? AND rated_id=?",
            (pid, m0["id"], counterpart_id)).fetchone()
        my_rating_given = mine["rating"] if mine else 0
    db.close()
    return render(req, "subtraitance_detail.html", {
        "post": post, "author": dict(author) if author else {}, "is_owner": is_owner,
        "threads": threads, "thread_messages": thread_messages, "other_id": other_id,
        "counterpart_id": counterpart_id, "counterpart_rating": counterpart_rating,
        "my_rating_given": my_rating_given})

@app.post("/sous-traitance/{pid}/message")
async def subtraitance_send_message(req: Request, pid: str, body:str=Form(""), to:str=Form(""), csrf_token:str=Form("")):
    m0 = get_member(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    if not check_rate_limit(f"st_msg_{m0['id']}", 20, 600):
        return RedirectResponse(f"/sous-traitance/{pid}", 302)
    if not body.strip():
        return RedirectResponse(f"/sous-traitance/{pid}", 302)
    db = get_db()
    post = db.execute("SELECT member_id FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if not post:
        db.close()
        return RedirectResponse("/sous-traitance", 302)
    owner_id = post["member_id"]
    if m0["id"] != owner_id:
        # Un non-propriétaire ne peut écrire qu'au propriétaire de l'annonce —
        # "to" est ignoré pour empêcher de contacter un membre arbitraire.
        recipient_id = owner_id
    else:
        # Le propriétaire ne peut répondre qu'à quelqu'un qui lui a déjà
        # écrit sur CETTE annonce — "to" est validé, jamais utilisé tel quel.
        if not to:
            db.close()
            return RedirectResponse(f"/sous-traitance/{pid}", 302)
        try:
            to_id = int(to)
        except ValueError:
            db.close()
            return RedirectResponse(f"/sous-traitance/{pid}", 302)
        prior = db.execute(
            "SELECT 1 FROM subcontract_messages WHERE post_id=? AND sender_id=? LIMIT 1",
            (pid, to_id)).fetchone()
        if not prior:
            db.close()
            return RedirectResponse(f"/sous-traitance/{pid}", 302)
        recipient_id = to_id
    db.execute("""INSERT INTO subcontract_messages(post_id,sender_id,recipient_id,body,created_at,read_at)
                  VALUES(?,?,?,?,?,?)""",
               (pid, m0["id"], recipient_id, body.strip()[:2000], datetime.now().isoformat(), ""))
    db.commit()
    recipient = db.execute("SELECT email,notif_email FROM members WHERE id=?", (recipient_id,)).fetchone()
    db.close()
    if recipient and recipient["notif_email"] and recipient["email"]:
        try:
            from app.services.notifications import email_send
            loop = asyncio.get_event_loop()
            sender_name = m0.get("nom") or m0["email"]
            loop.run_in_executor(None, lambda: email_send(
                recipient["email"], "📩 Nouveau message — Sous-traitance",
                f"<p><b>{sender_name}</b> vous a envoyé un message au sujet d'une annonce de sous-traitance.</p>"
                f"<p><a href='{cfg.SITE_URL}/sous-traitance/{pid}'>Voir le message →</a></p>"))
        except Exception as e:
            logger.warning(f"[subtraitance email] {e}")
    who = m0["id"] if m0["id"] != owner_id else recipient_id
    return RedirectResponse(f"/sous-traitance/{pid}?with={who}", 302)

@app.post("/sous-traitance/{pid}/cloturer")
async def subtraitance_close(req: Request, pid: str, csrf_token:str=Form("")):
    m0 = get_member(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login", 302)
    db = get_db()
    post = db.execute("SELECT member_id FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if post and post["member_id"] == m0["id"]:
        db.execute("UPDATE subcontract_posts SET statut='clos' WHERE id=?", (pid,))
        db.commit()
    db.close()
    return RedirectResponse(f"/sous-traitance/{pid}", 302)

@app.post("/sous-traitance/{pid}/noter")
async def subtraitance_rate(req: Request, pid: str, rated_id:int=Form(...),
                             rating:int=Form(5), comment:str=Form(""), csrf_token:str=Form("")):
    m0 = get_member(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    if not check_rate_limit(f"st_rate_{m0['id']}", 20, 3600):
        return RedirectResponse(f"/sous-traitance/{pid}", 302)
    if rated_id == m0["id"] or rating < 1 or rating > 5:
        return RedirectResponse(f"/sous-traitance/{pid}", 302)
    db = get_db()
    # On ne peut noter que quelqu'un avec qui on a échangé un message sur cette annonce
    exchanged = db.execute(
        """SELECT 1 FROM subcontract_messages WHERE post_id=?
           AND ((sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)) LIMIT 1""",
        (pid, m0["id"], rated_id, rated_id, m0["id"])).fetchone()
    if exchanged:
        db.execute(
            """INSERT INTO subcontract_ratings(post_id,rater_id,rated_id,rating,comment,created_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(post_id,rater_id,rated_id) DO UPDATE SET rating=excluded.rating, comment=excluded.comment""",
            (pid, m0["id"], rated_id, rating, comment.strip()[:500], datetime.now().isoformat()))
        db.commit()
    db.close()
    who = rated_id if m0["id"] != rated_id else ""
    return RedirectResponse(f"/sous-traitance/{pid}?with={who}", 302)

@app.post("/sous-traitance/{pid}/signaler")
async def subtraitance_report(req: Request, pid: str, reason:str=Form(""), csrf_token:str=Form("")):
    m0 = get_member(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login", 302)
    if not check_rate_limit(f"st_report_{m0['id']}", 10, 3600):
        return RedirectResponse(f"/sous-traitance/{pid}?reported=1", 302)
    db = get_db()
    post = db.execute("SELECT titre FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if post:
        db.execute(
            "INSERT INTO subcontract_reports(post_id,reporter_id,reason,created_at) VALUES(?,?,?,?)",
            (pid, m0["id"], reason.strip()[:500], datetime.now().isoformat()))
        db.commit()
        try:
            tg_admin(f"🚩 Annonce signalée : « {post['titre'][:80]} »\n{cfg.SITE_URL}/admin/sous-traitance")
        except Exception as e:
            logger.warning(f"[report] notif admin échouée: {e}")
    db.close()
    return RedirectResponse(f"/sous-traitance/{pid}?reported=1", 302)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/dashboard",302)
    if not has_access(member):
        return render(req,"dashboard.html",{
            "locked":True,"favs":[],"notifs":[],"recs":[],
            "stats":{"favs":0,"notifs":0,"active":0,"today":0,"recs":0},
            "sector_dist":[],"trend":[]})
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
            f"SELECT * FROM tenders WHERE secteur IN ({ph}) AND statut='actif' ORDER BY scraped_at DESC LIMIT 5",
            ms).fetchall()]
    else:
        recs = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 5").fetchall()]
    stats = {
        "favs":   db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?",(member["id"],)).fetchone()[0],
        "notifs": db.execute("SELECT COUNT(*) FROM notif_log WHERE member_id=?",(member["id"],)).fetchone()[0],
        "active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
        "today":  db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND scraped_at>=date('now')").fetchone()[0],
        "recs":   len(recs),
    }
    # Répartition par grande famille (Travaux / Équipements / Services) — les
    # 83 codes du référentiel commencent par T/P/S selon leur catégorie.
    grp_rows = db.execute(
        "SELECT substr(secteur,1,1) g, COUNT(*) n FROM tenders WHERE statut='actif' AND secteur!='' GROUP BY g").fetchall()
    grp_labels = {"T": "Travaux", "P": "Équipements", "S": "Services"}
    sector_dist = [{"code": r["g"], "label": grp_labels.get(r["g"], r["g"]), "n": r["n"]} for r in grp_rows if r["g"] in grp_labels]
    sector_dist.sort(key=lambda x: -x["n"])
    # Tendance hebdomadaire (8 dernières semaines) pour le graphique d'évolution.
    trend_rows = db.execute(
        """SELECT strftime('%Y-%W', scraped_at) wk, COUNT(*) n FROM tenders
           WHERE statut='actif' GROUP BY wk ORDER BY wk DESC LIMIT 8""").fetchall()
    trend = list(reversed([{"week": r["wk"], "n": r["n"]} for r in trend_rows]))
    db.close()
    return render(req,"dashboard.html",{
        "favs":favs,"notifs":notifs,"recs":recs,"stats":stats,
        "sector_dist":sector_dist,"trend":trend})

@app.get("/tarifs", response_class=HTMLResponse)
async def tarifs(req: Request): return render(req,"tarifs.html",{})

# ══════════════════════════════════════════════════════════
# PAGES LÉGALES
# ══════════════════════════════════════════════════════════
@app.get("/mentions-legales", response_class=HTMLResponse)
async def legal_mentions(req: Request): return render(req, "legal_mentions.html", {})

@app.get("/cgu", response_class=HTMLResponse)
async def legal_cgu(req: Request): return render(req, "legal_cgu.html", {})

@app.get("/confidentialite", response_class=HTMLResponse)
async def legal_confidentialite(req: Request): return render(req, "legal_confidentialite.html", {})

@app.get("/contact", response_class=HTMLResponse)
async def contact_page(req: Request): return render(req, "contact.html", {})

# ══════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request, ref:str=""):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"register.html",{"ref":ref})

@app.post("/register")
async def register_post(req: Request,
    nom:str=Form(""), email:str=Form(""), phone:str=Form(""),
    company:str=Form(""), pw:str=Form(""), pw2:str=Form(""),
    ref:str=Form(""), csrf_token:str=Form(""), secteurs_sel:list=Form(default=[])):
    vals = {"nom":nom,"email":email,"phone":phone,"company":company}
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    if not check_rate_limit(f"register_{get_ip(req)}", 5, 600):
        return render(req,"register.html",{"err":tr_("err_too_many_generic",lang),"vals":vals})
    err  = None
    if not email or not pw: err = tr_("err_email_pw_required",lang)
    elif not validate_email(email): err = tr_("err_email_invalid",lang)
    elif pw != pw2: err = tr_("err_pw_mismatch",lang)
    else:
        ok, msg = validate_password(pw, lang)
        if not ok: err = msg
    if err: return render(req,"register.html",{"err":err,"vals":vals})
    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?",(email,)).fetchone():
            return render(req,"register.html",{"err":tr_("err_email_taken",lang),"vals":vals})
        sects       = clean_secteurs(secteurs_sel)
        trial_ends  = (datetime.now()+timedelta(days=14)).strftime("%Y-%m-%d")
        created_at  = datetime.now().isoformat()
        session_tok = make_session_token()
        my_ref_code = secrets.token_urlsafe(5).upper().replace("_","A").replace("-","B")[:7]
        referred_by = 0
        if ref:
            r = db.execute("SELECT id FROM members WHERE referral_code=?", (ref.strip().upper(),)).fetchone()
            if r: referred_by = r["id"]
        db.execute(
            """INSERT INTO members(nom,email,phone,company,pw_hash,secteurs,plan,created_at,trial_ends,
               session_token,referral_code,referred_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nom,email,phone,company,hash_pw(pw),json.dumps(sects),"free",created_at,trial_ends,
             session_tok,my_ref_code,referred_by))
        db.commit()
    finally: db.close()
    resp = RedirectResponse("/dashboard?welcome=1",302)
    resp.set_cookie("_session", session_tok,
                    max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request, next:str=""):
    if get_member(req): return RedirectResponse(next or "/dashboard",302)
    return render(req,"login.html",{"next":next})

@app.post("/login")
async def login_post(req: Request, email:str=Form(""), pw:str=Form(""), next:str=Form(""), csrf_token:str=Form("")):
    ip = get_ip(req)
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    if not check_rate_limit(ip):
        return render(req,"login.html",{"err":tr_("err_too_many_5min",lang),"vals":{"email":email},"next":next})
    db = get_db()
    m  = db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email,)).fetchone()
    if not m or not verify_pw(pw, m["pw_hash"]):
        db.close()
        return render(req,"login.html",{"err":tr_("err_login_incorrect",lang),"vals":{"email":email},"next":next})
    session_tok = make_session_token()
    db.execute("UPDATE members SET last_login=?, session_token=? WHERE id=?",
               (datetime.now().isoformat(), session_tok, m["id"]))
    db.commit(); db.close()
    onboarded = m["onboarded"] if "onboarded" in m.keys() else 1
    logger.info(f"[Login] ✅ {email} connecté")
    dest = next or ("/dashboard?welcome=1" if not onboarded else "/dashboard")
    resp = RedirectResponse(dest, 302)
    resp.set_cookie("_session", session_tok,
                    max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

@app.get("/logout")
async def logout():
    r = RedirectResponse("/",302); r.delete_cookie("_session"); return r

@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/settings",302)
    if not member.get("referral_code"):
        code = secrets.token_urlsafe(5).upper().replace("_","A").replace("-","B")[:7]
        db = get_db()
        db.execute("UPDATE members SET referral_code=? WHERE id=?", (code, member["id"]))
        db.commit(); db.close()
    ms = clean_secteurs(json.loads(member.get("secteurs","[]") or "[]"))
    referral_count = 0
    db2 = get_db()
    referral_count = db2.execute("SELECT COUNT(*) FROM members WHERE referred_by=?", (member["id"],)).fetchone()[0]
    db2.close()
    return render(req,"settings.html",{"ms":ms,"referral_count":referral_count})

@app.post("/settings")
async def settings_post(req: Request,
    nom:str=Form(""), phone:str=Form(""), company:str=Form(""),
    telegram:str=Form(""), csrf_token:str=Form(""), secteurs_sel:list=Form(default=[])):
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login",302)
    if not check_rate_limit(f"settings_{member['id']}", 15, 600):
        return RedirectResponse("/settings",302)
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

@app.get("/settings/export")
async def settings_export(req: Request):
    """Export des données personnelles (droit d'accès — loi 09-08/CNDP)."""
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/settings", 302)
    db = get_db()
    try:
        favs = [r["tender_id"] for r in db.execute(
            "SELECT tender_id FROM favorites WHERE member_id=?", (member["id"],)).fetchall()]
        posts = [dict(r) for r in db.execute(
            "SELECT id,type,titre,secteur,region,budget,date_limite,description,statut,created_at FROM subcontract_posts WHERE member_id=?",
            (member["id"],)).fetchall()]
        sent = [dict(r) for r in db.execute(
            "SELECT post_id,recipient_id,body,created_at FROM subcontract_messages WHERE sender_id=?",
            (member["id"],)).fetchall()]
        received = [dict(r) for r in db.execute(
            "SELECT post_id,sender_id,body,created_at FROM subcontract_messages WHERE recipient_id=?",
            (member["id"],)).fetchall()]
        ratings_given = [dict(r) for r in db.execute(
            "SELECT post_id,rated_id,rating,comment,created_at FROM subcontract_ratings WHERE rater_id=?",
            (member["id"],)).fetchall()]
        ratings_received = [dict(r) for r in db.execute(
            "SELECT post_id,rater_id,rating,comment,created_at FROM subcontract_ratings WHERE rated_id=?",
            (member["id"],)).fetchall()]
    finally:
        db.close()
    data = {
        "profil": {
            "nom": member.get("nom"), "email": member.get("email"), "phone": member.get("phone"),
            "company": member.get("company"), "plan": member.get("plan"),
            "secteurs": json.loads(member.get("secteurs","[]") or "[]"),
            "regions": json.loads(member.get("regions","[]") or "[]"),
            "telegram": member.get("telegram"), "whatsapp": member.get("whatsapp"),
            "created_at": member.get("created_at"),
        },
        "favoris": favs,
        "annonces_sous_traitance": posts,
        "messages_envoyes": sent,
        "messages_recus": received,
        "evaluations_donnees": ratings_given,
        "evaluations_recues": ratings_received,
    }
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(content=body, media_type="application/json",
                     headers={"Content-Disposition": "attachment; filename=mes-donnees-maroc-entrepreneuriat.json"})

@app.post("/settings/delete")
async def settings_delete(req: Request, password:str=Form(""), csrf_token:str=Form("")):
    """Suppression de compte (droit à l'effacement — loi 09-08/CNDP).

    Les échanges/évaluations liés aux annonces de sous-traitance sont
    supprimés avec le compte plutôt qu'anonymisés : le service ne fait
    pas de compromis partiel sur une demande de suppression."""
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login", 302)
    if not check_rate_limit(f"del_acct_{member['id']}", 5, 600):
        return RedirectResponse("/settings?err=too_many", 302)
    if not verify_pw(password, member.get("pw_hash", "")):
        return RedirectResponse("/settings?err=wrongpw", 302)
    mid = member["id"]
    db = get_db()
    try:
        db.execute("DELETE FROM favorites WHERE member_id=?", (mid,))
        db.execute("DELETE FROM notif_log WHERE member_id=?", (mid,))
        db.execute("DELETE FROM notif_queue WHERE member_id=?", (mid,))
        db.execute("""DELETE FROM subcontract_messages WHERE post_id IN
                      (SELECT id FROM subcontract_posts WHERE member_id=?)""", (mid,))
        db.execute("DELETE FROM subcontract_messages WHERE sender_id=? OR recipient_id=?", (mid, mid))
        db.execute("DELETE FROM subcontract_ratings WHERE rater_id=? OR rated_id=?", (mid, mid))
        db.execute("DELETE FROM subcontract_reports WHERE reporter_id=?", (mid,))
        db.execute("DELETE FROM subcontract_posts WHERE member_id=?", (mid,))
        db.execute("DELETE FROM members WHERE id=?", (mid,))
        db.commit()
    finally:
        db.close()
    r = RedirectResponse("/?deleted=1", 302)
    r.delete_cookie("_session")
    return r

# ══════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_get(req: Request):
    if _is_admin(req): return RedirectResponse("/admin",302)
    return render(req,"admin_login.html",{})

@app.post("/admin/login")
async def admin_login_post(req: Request, pwd:str=Form(""), csrf_token:str=Form("")):
    ip = get_ip(req)
    csrf_guard(req, csrf_token)
    if not check_rate_limit(f"admin_{ip}", 5, 600):
        return render(req,"admin_login.html",{"err":"Trop de tentatives."})
    if not cfg.ADMIN_PASS or cfg.ADMIN_PASS == "atlas2026":
        logger.error("[admin] ADMIN_PASS non configuré ou valeur par défaut — accès refusé par sécurité")
        return render(req,"admin_login.html",{"err":"Configuration serveur invalide — contactez l'administrateur système."})
    if pwd != cfg.ADMIN_PASS:
        return render(req,"admin_login.html",{"err":"Mot de passe incorrect"})
    r = RedirectResponse("/admin",302)
    r.set_cookie("_admin",make_token("admin",cfg.ADMIN_PASS),
                 httponly=True,max_age=86400*7,samesite="lax",secure=COOKIE_SECURE)
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

    # ── Analytics : croissance des membres, répartition des plans,
    # estimation du revenu mensualisé (paiement manuel — jamais de vrai
    # historique de transactions, donc calculé à partir des plans actifs) ──
    growth_rows = db.execute(
        """SELECT strftime('%Y-%W', created_at) wk, COUNT(*) n FROM members
           WHERE created_at != '' GROUP BY wk ORDER BY wk DESC LIMIT 8""").fetchall()
    member_growth = list(reversed([{"week": r["wk"], "n": r["n"]} for r in growth_rows]))
    plan_rows = db.execute(
        "SELECT plan, COUNT(*) n FROM members WHERE actif=1 GROUP BY plan").fetchall()
    plan_dist = {r["plan"]: r["n"] for r in plan_rows}
    pro_price  = cfg.PLANS.get("pro",{}).get("price",0)
    biz_price  = cfg.PLANS.get("business",{}).get("price",0)
    mrr_estimate = round(plan_dist.get("pro",0) * (pro_price/12) + plan_dist.get("business",0) * (biz_price/24))
    total_active_members = db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0]
    referral_top = [dict(r) for r in db.execute(
        """SELECT m.nom, m.email, COUNT(r.id) n FROM members m
           JOIN members r ON r.referred_by = m.id
           GROUP BY m.id ORDER BY n DESC LIMIT 5""").fetchall()]
    recent_errors = [dict(r) for r in db.execute(
        "SELECT * FROM error_log ORDER BY created_at DESC LIMIT 10").fetchall()]
    errors_7j = db.execute(
        "SELECT COUNT(*) FROM error_log WHERE created_at>=datetime('now','-7 days')").fetchone()[0]
    db.close()
    csrf_tok = get_csrf_token(req) or secrets.token_urlsafe(24)
    resp = templates.TemplateResponse("admin.html",{
        "request":req,"stats":stats,"sectors":sectors,
        "members":members,"scrapes":scrapes,
        "logs":State.logs[-100:],"running":State.running,
        "last_run":State.last_run,"cfg":cfg,"multi_ok":MULTI_OK,
        "member_growth":member_growth,"plan_dist":plan_dist,
        "mrr_estimate":mrr_estimate,"total_active_members":total_active_members,
        "referral_top":referral_top,"recent_errors":recent_errors,"errors_7j":errors_7j,
        "csrf_token":csrf_tok})
    if not req.cookies.get("_csrf"):
        resp.set_cookie("_csrf", csrf_tok, max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp


# Le champ "adjudicataire" contient parfois, à la place d'un vrai nom
# d'entreprise, un statut de procédure (marché resté sans suite) — ces
# valeurs ne sont pas des prospects et fausseraient le classement.
NON_COMPANY_ADJUDICATAIRE = {
    "infructueux", "annule", "annulé", "voir pv", "neant", "néant",
    "sans suite", "non attribue", "non attribué", "abandonne", "abandonné",
    "sans objet", "declare infructueux", "déclaré infructueux",
}

def _prospects_base_filter():
    """WHERE/params qui excluent les valeurs d'adjudicataire qui ne sont pas
    de vrais noms d'entreprise (marché resté sans suite, annulé, etc.)."""
    junk_ph = ",".join(["?"] * len(NON_COMPANY_ADJUDICATAIRE))
    where = [
        "adjudicataire!='' AND LENGTH(TRIM(adjudicataire))>3",
        f"LOWER(TRIM(adjudicataire)) NOT IN ({junk_ph})",
    ]
    return " AND ".join(where), list(NON_COMPANY_ADJUDICATAIRE)

def _prospects_query(req: Request):
    """Construit le WHERE/params communs à la page et à l'export CSV des
    prospects : les adjudicataires (entreprises ayant déjà gagné un marché)
    regroupés par nom, c'est le vivier de clients potentiels le plus fiable
    puisqu'il s'agit d'entreprises réellement actives sur le marché marocain."""
    q = req.query_params.get("q", "")
    s = req.query_params.get("s", "")
    r = req.query_params.get("r", "")
    wh, params = _prospects_base_filter()
    where = [wh]
    if q:
        where.append("adjudicataire LIKE ?"); params.append(f"%{q}%")
    if s:
        where.append("secteur=?"); params.append(s)
    if r:
        where.append("region=?"); params.append(r)
    return " AND ".join(where), params, q, s, r

@app.get("/admin/prospects", response_class=HTMLResponse)
async def admin_prospects(req: Request, sort: str = "wins", page: int = 1):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    wh, params, q, s, r = _prospects_query(req)
    db = get_db(); per = 30; page = max(1, page)
    order = "wins DESC" if sort == "wins" else "last_seen DESC"
    total = db.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM tender_results WHERE {wh} GROUP BY UPPER(TRIM(adjudicataire)))",
        params).fetchone()[0]
    rows = [dict(x) for x in db.execute(f"""
        SELECT MAX(adjudicataire) AS name, COUNT(*) AS wins,
               GROUP_CONCAT(DISTINCT secteur) AS secteurs_raw,
               GROUP_CONCAT(DISTINCT region) AS regions_raw,
               MAX(scraped_at) AS last_seen
        FROM tender_results
        WHERE {wh}
        GROUP BY UPPER(TRIM(adjudicataire))
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """, params + [per, (page-1)*per]).fetchall()]
    regions = [row[0] for row in db.execute(
        "SELECT DISTINCT region FROM tender_results WHERE region!='' ORDER BY region LIMIT 60").fetchall()]
    base_wh, base_params = _prospects_base_filter()
    total_companies = db.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM tender_results WHERE {base_wh} GROUP BY UPPER(TRIM(adjudicataire)))",
        base_params).fetchone()[0]
    db.close()
    pages = max(1, (total+per-1)//per)
    return templates.TemplateResponse("admin_prospects.html", {
        "request": req, "cfg": cfg, "rows": rows, "total": total, "total_companies": total_companies,
        "page": page, "pages": pages, "q": q, "sf": s, "rf": r, "sort": sort,
        "regions": regions, "sector_groups": cfg.SECTOR_GROUPS})

@app.get("/admin/prospects/export")
async def admin_prospects_export(req: Request):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    wh, params, *_ = _prospects_query(req)
    db = get_db()
    rows = db.execute(f"""
        SELECT MAX(adjudicataire) AS name, COUNT(*) AS wins,
               GROUP_CONCAT(DISTINCT secteur) AS secteurs_raw,
               GROUP_CONCAT(DISTINCT region) AS regions_raw,
               MAX(scraped_at) AS last_seen
        FROM tender_results
        WHERE {wh}
        GROUP BY UPPER(TRIM(adjudicataire))
        ORDER BY wins DESC
    """, params).fetchall()
    db.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Entreprise", "Marches_gagnes", "Secteurs", "Regions", "Derniere_activite"])
    for row in rows:
        secteurs = ", ".join(get_label(c) for c in (row["secteurs_raw"] or "").split(",") if c)
        regions  = ", ".join(c for c in (row["regions_raw"] or "").split(",") if c)
        writer.writerow([row["name"], row["wins"], secteurs, regions, (row["last_seen"] or "")[:10]])
    return Response(content=buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                     headers={"Content-Disposition": "attachment; filename=prospects_maroc_entrepreneuriat.csv"})

@app.get("/admin/sous-traitance", response_class=HTMLResponse)
async def admin_subtraitance(req: Request):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    posts = [dict(r) for r in db.execute("""
        SELECT p.*, m.nom AS auteur_nom, m.email AS auteur_email,
               (SELECT COUNT(*) FROM subcontract_reports WHERE post_id=p.id) AS n_reports
        FROM subcontract_posts p LEFT JOIN members m ON m.id = p.member_id
        ORDER BY n_reports DESC, p.created_at DESC LIMIT 200
    """).fetchall()]
    reports = [dict(r) for r in db.execute("""
        SELECT r.*, m.email AS reporter_email FROM subcontract_reports r
        LEFT JOIN members m ON m.id = r.reporter_id
        ORDER BY r.created_at DESC LIMIT 100
    """).fetchall()]
    db.close()
    csrf_tok = get_csrf_token(req) or secrets.token_urlsafe(24)
    resp = templates.TemplateResponse("admin_subtraitance.html", {
        "request": req, "cfg": cfg, "posts": posts, "reports": reports, "csrf_token": csrf_tok})
    if not req.cookies.get("_csrf"):
        resp.set_cookie("_csrf", csrf_tok, max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

@app.post("/admin/sous-traitance/{pid}/delete")
async def admin_subtraitance_delete(req: Request, pid: str, csrf_token:str=Form("")):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    db = get_db()
    db.execute("DELETE FROM subcontract_messages WHERE post_id=?", (pid,))
    db.execute("DELETE FROM subcontract_ratings WHERE post_id=?", (pid,))
    db.execute("DELETE FROM subcontract_reports WHERE post_id=?", (pid,))
    db.execute("DELETE FROM subcontract_posts WHERE id=?", (pid,))
    db.commit(); db.close()
    return RedirectResponse("/admin/sous-traitance", 302)

@app.get("/admin/backups", response_class=HTMLResponse)
async def admin_backups(req: Request):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    files = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.startswith("atlas_") and f.endswith(".db"):
            p = os.path.join(BACKUP_DIR, f)
            files.append({
                "name": f,
                "size_mb": round(os.path.getsize(p) / (1024*1024), 2),
                "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"),
            })
    return templates.TemplateResponse("admin_backups.html", {"request": req, "cfg": cfg, "files": files})

@app.get("/admin/backups/run")
async def admin_backups_run(req: Request):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    path = make_db_backup()
    return RedirectResponse("/admin/backups", 302) if path else JSONResponse({"ok": False, "msg": "Base introuvable"}, 500)

@app.get("/admin/backups/download/{filename}")
async def admin_backups_download(req: Request, filename: str):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    safe_name = os.path.basename(filename)
    path = os.path.join(BACKUP_DIR, safe_name)
    if not safe_name.startswith("atlas_") or not safe_name.endswith(".db") or not os.path.isfile(path):
        return HTMLResponse("Fichier introuvable", 404)
    return FileResponse(path, filename=safe_name, media_type="application/octet-stream")

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
async def set_plan(req: Request, mid:int, plan:str=Form(""), csrf_token:str=Form("")):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    csrf_guard(req, csrf_token)
    if plan not in cfg.PLANS: return JSONResponse({"ok":False,"msg":"Plan invalide"})
    db = get_db()
    db.execute("UPDATE members SET plan=? WHERE id=?",(plan,mid))
    db.commit(); db.close()
    return RedirectResponse("/admin",302)

@app.post("/admin/member/{mid}/toggle")
async def toggle_member(req: Request, mid:int, csrf_token:str=Form("")):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    csrf_guard(req, csrf_token)
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
    m0 = get_member(req)
    if not m0:
        return JSONResponse({"ok":False,"msg":"Réservé aux membres — connectez-vous"},401)
    if not has_access(m0):
        return JSONResponse({"ok":False,"msg":"Abonnement requis"},403)
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
    m0 = get_member(req)
    if not m0:
        return JSONResponse({"ok":False,"msg":"Réservé aux membres — connectez-vous"},401)
    if not has_access(m0):
        return JSONResponse({"ok":False,"msg":"Abonnement requis"},403)
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
async def forgot_post(req: Request, email: str = Form(""), csrf_token: str = Form("")):
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    if not check_rate_limit(f"forgot_{get_ip(req)}", 5, 600):
        return render(req, "forgot.html", {"err": tr_("err_too_many_generic",lang)})
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
                email, tr_("email_reset_subject",lang),
                f"""<h2>{tr_("email_reset_h2",lang)}</h2>
                <p>{tr_("email_reset_p",lang)}</p>
                <a href="{reset_url}" style="display:inline-block;padding:12px 24px;background:#f2662d;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
                  {tr_("email_reset_btn",lang)}
                </a>
                <p style="color:#666;font-size:12px;margin-top:16px">{tr_("email_reset_expiry",lang)}</p>"""))
        except Exception as e:
            logger.error(f"[reset email] {e}")
        db.close()
    return render(req, "forgot.html", {"sent": True})

@app.get("/reset", response_class=HTMLResponse)
async def reset_get(req: Request, token: str = ""):
    lang = get_lang(req)
    db  = get_db()
    m   = db.execute("SELECT * FROM members WHERE reset_token=?", (token,)).fetchone()
    db.close()
    if not m or not m["reset_token"]:
        return render(req, "reset.html", {"err": tr_("err_reset_invalid_expired",lang)})
    if datetime.fromisoformat(m["reset_expires"] or "2000-01-01") < datetime.now():
        return render(req, "reset.html", {"err": tr_("err_reset_expired",lang)})
    return render(req, "reset.html", {"token": token})

@app.post("/reset")
async def reset_post(req: Request, token: str = Form(""),
                     pw: str = Form(""), pw2: str = Form(""), csrf_token: str = Form("")):
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    if pw != pw2:
        return render(req, "reset.html", {"token": token, "err": tr_("err_pw_mismatch",lang)})
    if len(pw) < 8:
        return render(req, "reset.html", {"token": token, "err": tr_("err_pw_min8",lang)})
    db = get_db()
    m  = db.execute("SELECT * FROM members WHERE reset_token=?", (token,)).fetchone()
    if not m or not m["reset_token"]:
        db.close()
        return render(req, "reset.html", {"err": tr_("err_reset_invalid",lang)})
    if datetime.fromisoformat(m["reset_expires"] or "2000-01-01") < datetime.now():
        db.close()
        return render(req, "reset.html", {"err": tr_("err_reset_expired",lang)})
    db.execute("UPDATE members SET pw_hash=?, reset_token='', reset_expires='', session_token='' WHERE id=?",
               (hash_pw(pw), m["id"]))
    db.commit(); db.close()
    return RedirectResponse("/login?reset=1", 302)

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

# ── PWA (installable sur mobile) ───────────────────────────
def _pwa_icon_svg(size: int) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
<rect width="{size}" height="{size}" fill="#1e1611"/>
<text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle"
      font-family="Georgia, serif" font-weight="800" font-size="{int(size*0.42)}" fill="#f2662d">ME</text>
</svg>"""

@app.get("/icon-192.svg")
async def icon_192():
    return Response(_pwa_icon_svg(192), media_type="image/svg+xml")

@app.get("/icon-512.svg")
async def icon_512():
    return Response(_pwa_icon_svg(512), media_type="image/svg+xml")

@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "name": "Maroc Entrepreneuriat",
        "short_name": "ME",
        "description": "Veille des marchés publics et privés au Maroc",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#f8f1e1",
        "theme_color": "#f8f1e1",
        "lang": "fr",
        "icons": [
            {"src": "/icon-192.svg", "sizes": "192x192", "type": "image/svg+xml", "purpose": "any"},
            {"src": "/icon-512.svg", "sizes": "512x512", "type": "image/svg+xml", "purpose": "any"},
        ],
    })

@app.get("/sw.js")
async def service_worker():
    js = """
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', (e) => { e.respondWith(fetch(e.request)); });
"""
    return Response(js, media_type="application/javascript")
