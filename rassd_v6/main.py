"""
MAROC ENTREPRENEURIAT v3.2 — SaaS Veille Marchés Publics Maroc
Full audit & fix — Production ready
"""
import os, re, json, secrets, asyncio, logging, hashlib, csv, io, time, traceback, unicodedata
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
                                get_member, has_access, email_ok, validate_email,
                                validate_password, days_left,
                                get_csrf_token, verify_csrf, subscription_state)
from app.core.sectors import get_label
from app.core import marque
from app.core import organismes
from app.core.i18n import get_lang, make_t, SUPPORTED_LANGS, tr as tr_
from app.services.notifications import dispatch_notifications, envoyer_apercu, tg_admin

# Les sources secondaires (ONDA, ONEE, ONCF, IAM, SNRT, Le Matin, banques)
# ont été retirées: deux bloquent les robots, les autres ne renvoyaient plus
# que la navigation de leur site. Ne restent que les sources qui ramènent de
# vrais avis: le portail public (bons de commande et appels d'offres) et la
# plateforme privée.

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
    # Constaté en production: prendre le DERNIER élément de X-Forwarded-For
    # revenait à compter par nœud de l'hébergeur, lequel change d'une requête
    # à l'autre. Le compteur anti-force-brute se dispersait et ne déclenchait
    # qu'au hasard (12 tentatives de connexion → 9 bloquées, mais 8
    # inscriptions → 1 seule bloquée). X-Real-IP est posé par le proxy
    # lui-même et désigne le vrai client; il ne peut pas être falsifié de
    # l'extérieur puisque le proxy écrase ce que le client aurait envoyé.
    for entete in ("x-real-ip", "cf-connecting-ip"):
        valeur = req.headers.get(entete, "").strip()
        if valeur:
            return valeur
    xff = req.headers.get("x-forwarded-for", "")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[0]
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
def _empreinte(objet: str) -> str:
    """Signature d'un marché, indépendante de la source qui l'a publié.

    Le portail et l'agrégateur privé publient parfois la même consultation
    avec une ponctuation ou une casse différente. Sans cette empreinte, le
    membre reçoit deux alertes pour un seul marché.
    """
    base = unicodedata.normalize("NFD", (objet or "").lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", base).strip()[:110]


def _save_tenders(tenders: list, new_list: list) -> int:
    if not tenders: return 0
    db = get_db(); saved = 0
    # Empreintes des marchés déjà ouverts: la même consultation venue d'une
    # autre source ne doit pas créer un second enregistrement.
    deja = {}
    for ligne in db.execute(
            "SELECT id, objet, date_limite FROM tenders WHERE statut='actif'").fetchall():
        deja[(_empreinte(ligne["objet"]), (ligne["date_limite"] or "").strip())] = ligne["id"]
    for t in tenders:
        cle = (_empreinte(t.get("objet")), (t.get("date_limite") or "").strip())
        if cle[0] and cle in deja and deja[cle] != t.get("id"):
            logger.info(f"[doublon] {t.get('id')} ignoré — déjà en base sous {deja[cle]}")
            continue
        deja[cle] = t.get("id")
        try:
            db.execute("""INSERT OR IGNORE INTO tenders
                (id,objet,acheteur,secteur,region,montant,
                 date_publication,date_limite,description,
                 url,statut,scraped_at,updated_at,type_offre,source,type_procedure,
                 nature,quantite,organisme)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t["id"], t["objet"], t["acheteur"],
                 t.get("secteur",""), t.get("region",""),
                 t.get("montant",""), t.get("date_publication",""),
                 t.get("date_limite",""), t.get("description",""),
                 t["url"], t["statut"], t["scraped_at"], t["scraped_at"],
                 t.get("type_offre","Public"), t.get("source","marchespublics"),
                 t.get("type_procedure","marche"),
                 t.get("nature",""), t.get("quantite",""),
                 organismes.categorie(t.get("acheteur",""), t.get("type_offre",""))))
            if db.execute("SELECT changes()").fetchone()[0]:
                saved += 1
                new_list.append(t)
        except Exception as e:
            logger.error(f"[save] {e}")
    db.commit(); db.close()
    return saved

def _save_results(results: list) -> int:
    if not results: return 0
    # Le montant est stocké deux fois: en texte pour l'affichage fidèle à la
    # source, en nombre pour filtrer et trier.
    from app.services.soustraitance import parse_montant
    # Le nom de l'attributaire aussi: en clair pour l'affichage, reduit
    # pour le rapprochement avec l'annuaire. Sans cette cle, un
    # attributaire n'est jamais relie a son telephone et la piste de
    # sous-traitance reste inexploitable.
    from app.services.companies import normalize_company_name
    db = get_db(); saved = 0
    for r in results:
        try:
            db.execute("""INSERT OR IGNORE INTO tender_results
                (id,reference,objet,acheteur,adjudicataire,region,budget,montant,
                 secteur,date_adjudication,date_ouverture,date_affichage,
                 dao_url,pv_url,scraped_at,type_procedure,montant_num,
                 adjudicataire_norm)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], r.get("reference",""), r["objet"], r.get("acheteur",""),
                 r.get("adjudicataire",""), r.get("region",""), r.get("budget",""),
                 r.get("montant",""), r.get("secteur",""),
                 r.get("date_adjudication",""), r.get("date_ouverture",""),
                 r.get("date_affichage",""), r.get("dao_url",""), r.get("pv_url",""),
                 r["scraped_at"], r.get("type_procedure","marche"),
                 parse_montant(r.get("montant","")),
                 normalize_company_name(r.get("adjudicataire",""))))
            if db.execute("SELECT changes()").fetchone()[0]:
                saved += 1
        except Exception as e:
            logger.error(f"[save_results] {e}")
    db.commit(); db.close()
    return saved

def _record_run(source: str, status: str, found: int = 0, saved: int = 0,
                errors: int = 0, started=None, message: str = ""):
    """Trace l'exécution d'un scraper, source par source (§24).

    Volontairement tolérant aux pannes: un échec d'écriture du journal ne doit
    jamais interrompre une veille en cours.
    """
    try:
        now = datetime.now()
        dur = int((now - started).total_seconds() * 1000) if started else 0
        db = get_db()
        db.execute(
            """INSERT INTO scraper_runs(source,status,records_found,records_saved,duplicates,
               errors,duration_ms,message,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (source, status, found, saved, max(0, found - saved), errors, dur,
             (message or "")[:300], (started or now).isoformat(), now.isoformat()))
        db.commit(); db.close()
    except Exception as e:
        logger.error(f"[scraper_runs] {e}")

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
        _t = datetime.now()
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
            _record_run("marchespublics", "SUCCESS", len(results), saved, started=_t)
        except Exception as e:
            State.log(f"❌ marchespublics: {e}")
            logger.error(f"[scraper] {e}", exc_info=True)
            _record_run("marchespublics", "FAILED", errors=1, started=_t, message=str(e))

        # ── Appels d'offres du portail ─────────────────────
        # Section distincte des avis d'achat sur bon de commande: ce sont les
        # marchés d'un montant significatif, avec leur estimation en dirhams.
        _t = datetime.now()
        try:
            State.log("─" * 48)
            State.log("  Appels d'offres — marchespublics.gov.ma")
            from app.services.ao_scraper import run as ao_run
            db     = get_db()
            known_ao = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
            db.close()
            ao_results = await loop.run_in_executor(None, lambda: ao_run(known_ao, State.log))
            State.found += len(ao_results)
            saved_ao = _save_tenders(ao_results, new_tenders)
            State.saved += saved_ao
            State.log(f"✅ Appels d'offres: {saved_ao} nouveaux")
            _record_run("marchespublics-ao", "SUCCESS", len(ao_results), saved_ao, started=_t)
        except Exception as e:
            State.log(f"❌ Appels d'offres: {e}")
            logger.error(f"[ao_scraper] {e}", exc_info=True)
            _record_run("marchespublics-ao", "FAILED", errors=1, started=_t, message=str(e))

        # ── Marchés privés ─────────────────────────────────
        _t = datetime.now()
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
            _record_run("global-marches", "SUCCESS", len(gm_results), saved3, started=_t)
        except Exception as e:
            State.log(f"❌ Marchés privés: {e}")
            _record_run("global-marches", "FAILED", errors=1, started=_t, message=str(e))
            logger.error(f"[gm scraper] {e}", exc_info=True)

        # ── Résultats des marchés (adjudications) ──────────
        _t = datetime.now()
        try:
            State.log("─" * 48)
            from app.services.private_scraper import run_results as gm_run_results
            db      = get_db()
            known4  = {r[0] for r in db.execute("SELECT id FROM tender_results").fetchall()}
            db.close()
            gm_res  = await loop.run_in_executor(None, lambda: gm_run_results(known4, State.log))
            saved4  = _save_results(gm_res)
            State.log(f"✅ Résultats des marchés: {saved4} nouveaux")
            _record_run("global-marches-results", "SUCCESS", len(gm_res), saved4, started=_t)
        except Exception as e:
            State.log(f"❌ Résultats des marchés: {e}")
            _record_run("global-marches-results", "FAILED", errors=1, started=_t, message=str(e))
            logger.error(f"[gm results scraper] {e}", exc_info=True)

        # ── Bons de commande ────────────────────────────────
        _t = datetime.now()
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
            _record_run("bons-de-commande", "SUCCESS", len(bc_results), saved5, started=_t)
        except Exception as e:
            State.log(f"❌ Bons de commande: {e}")
            _record_run("bons-de-commande", "FAILED", errors=1, started=_t, message=str(e))
            logger.error(f"[bc scraper] {e}", exc_info=True)

        # ── Résultats des bons de commande ──────────────────
        _t = datetime.now()
        try:
            State.log("─" * 48)
            from app.services.private_scraper import run_bc_results as gm_run_bc_results
            db      = get_db()
            known6  = {r[0] for r in db.execute("SELECT id FROM tender_results").fetchall()}
            db.close()
            bc_res  = await loop.run_in_executor(None, lambda: gm_run_bc_results(known6, State.log))
            saved6  = _save_results(bc_res)
            State.log(f"✅ Résultats des bons de commande: {saved6} nouveaux")
            _record_run("bc-results", "SUCCESS", len(bc_res), saved6, started=_t)
        except Exception as e:
            State.log(f"❌ Résultats des bons de commande: {e}")
            _record_run("bc-results", "FAILED", errors=1, started=_t, message=str(e))
            logger.error(f"[bc results scraper] {e}", exc_info=True)

        # ── Gagnants de marchés → annuaire et file d'appel ────
        # Une entreprise qui vient de remporter un marché est le meilleur
        # prospect que la plateforme sache produire. Fait à chaque cycle
        # plutôt que sur commande: sinon la liste d'appel vieillit dès la
        # collecte suivante.
        _t = datetime.now()
        try:
            from app.services.gagnants import inscrire, semer_prospection
            st = await loop.run_in_executor(None, lambda: inscrire(State.log))
            await loop.run_in_executor(None, lambda: semer_prospection(State.log))
            State.log(f"✅ Gagnants: {st['gagnants']} attributaire(s), "
                      f"{st['creees']} fiche(s) créée(s)")
            _record_run("gagnants", "SUCCESS", st["lignes"], st["creees"], started=_t)
        except Exception as e:
            State.log(f"❌ Gagnants: {e}")
            _record_run("gagnants", "FAILED", errors=1, started=_t, message=str(e))
            logger.error(f"[gagnants] {e}", exc_info=True)

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
        # Filet de sécurité: les marchés écrits en base mais jamais notifiés
        # (redémarrage du serveur entre l'écriture et l'envoi, import lancé
        # depuis l'admin) sont repris ici. La déduplication évite les doublons.
        try:
            from app.services.notifications import dispatch_pending
            await loop.run_in_executor(None, dispatch_pending)
        except Exception as e:
            logger.error(f"[rattrapage] {e}")

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
        # Clôture des marchés dont la date limite est passée. Sans ce passage,
        # expire_tenders() n'était appelé que par un bouton de l'admin: la
        # plateforme affichait des milliers de consultations déjà fermées.
        try:
            loop = asyncio.get_event_loop()
            expires, actifs = await loop.run_in_executor(None, expire_tenders)
            if expires:
                logger.info(f"[expiration] {expires} marché(s) clôturé(s), {actifs} encore ouverts")
        except Exception as e:
            logger.error(f"[expiration] {e}")
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

async def supervision_scheduler():
    """Surveille la plateforme et prévient l'administrateur.

    Une veille qui s'arrête ne se voit pas: le site reste debout et les
    membres cessent simplement de recevoir des marchés. Contrôle toutes les
    heures, bilan complet une fois par jour.
    """
    from app.services.supervision import verifier
    await asyncio.sleep(300)
    dernier_bilan = ""
    while True:
        try:
            aujourdhui = date.today().isoformat()
            bilan = (datetime.now().hour >= cfg.DAILY_REPORT_HOUR
                     and dernier_bilan != aujourdhui)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: verifier(envoyer_bilan=bilan))
            if bilan:
                dernier_bilan = aujourdhui
        except Exception as e:
            logger.error(f"[supervision_scheduler] {e}")
        await asyncio.sleep(3600)


async def daily_digest_scheduler():
    """Envoie les résumés quotidiens le matin, heure du Maroc."""
    from app.services.notifications import send_daily_digests
    await asyncio.sleep(240)
    while True:
        try:
            if datetime.now().hour >= cfg.DAILY_DIGEST_HOUR:
                loop = asyncio.get_event_loop()
                n = await loop.run_in_executor(None, send_daily_digests)
                if n: logger.info(f"[résumé quotidien] {n} envoi(s)")
        except Exception as e:
            logger.error(f"[daily_digest_scheduler] {e}")
        await asyncio.sleep(1800)


async def recap_prep_scheduler():
    """Fige chaque soir le lot à envoyer à la main le lendemain matin.

    L'envoi WhatsApp reste manuel — c'est un choix, pas une limite: pour les
    premiers abonnés, un message écrit de la main du fondateur vaut mieux
    qu'une notification de plus. Mais la matière, elle, se prépare toute
    seule: à l'heure dite, chaque membre actif reçoit sa ligne, avec le
    compte de ses marchés du jour.

    Préparer le soir plutôt qu'au moment d'ouvrir la page évite deux ennuis
    constatés: la liste changeait entre deux consultations, et rien ne disait
    qui avait déjà été prévenu.
    """
    from app.services.recap import preparer

    await asyncio.sleep(300)
    dernier = ""
    while True:
        try:
            maintenant = datetime.now()
            jour = maintenant.strftime("%Y-%m-%d")
            if maintenant.hour >= cfg.RECAP_PREP_HOUR and dernier != jour:
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, lambda: preparer(jour))
                dernier = jour
                logger.info(f"[récap] lot du {jour} prêt: "
                            f"{stats['avec_marches']}/{stats['membres']} membre(s)")
                if stats["avec_marches"]:
                    tg_admin(f"📋 Récap du {jour} prêt — "
                             f"{stats['avec_marches']} membre(s) à prévenir, "
                             f"{stats['marches']} marché(s).\n"
                             f"{cfg.SITE_URL}/admin/recap")
        except Exception as e:
            logger.error(f"[recap_prep_scheduler] {e}")
        await asyncio.sleep(1800)


async def renewal_scheduler():
    """Relance les abonnements qui arrivent à échéance (J-7, J-1, jour J)."""
    from app.services.notifications import send_renewal_reminders
    await asyncio.sleep(420)
    while True:
        try:
            loop = asyncio.get_event_loop()
            n = await loop.run_in_executor(None, send_renewal_reminders)
            if n: logger.info(f"[relance abo] {n} relance(s)")
        except Exception as e:
            logger.error(f"[renewal_scheduler] {e}")
        await asyncio.sleep(12 * 3600)


async def trial_sequence_scheduler():
    """Accompagne les essais gratuits: une vérification toutes les 6 heures.

    send_trial_sequence() est idempotent (members.trial_seq), donc plusieurs
    passages le même jour n'envoient jamais deux fois la même étape.
    """
    from app.services.notifications import send_trial_sequence
    await asyncio.sleep(180)
    while True:
        try:
            loop = asyncio.get_event_loop()
            n = await loop.run_in_executor(None, send_trial_sequence)
            if n: logger.info(f"[essai] {n} email(s) d'accompagnement")
        except Exception as e:
            logger.error(f"[trial_sequence_scheduler] {e}")
        await asyncio.sleep(6 * 3600)


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

def envoyer_sauvegarde_telegram(chemin: str) -> bool:
    """Expédie la sauvegarde compressée sur Telegram, à l'administrateur.

    Une copie qui dort sur le même disque que la base ne protège de rien: si
    le volume Railway disparaît, tout part avec lui. Telegram accepte 50 Mo
    par document, et la base compressée tient largement dedans.
    """
    import gzip, shutil
    if not (cfg.TELEGRAM_BOT and cfg.ADMIN_CHAT_ID):
        return False
    archive = f"{chemin}.gz"
    try:
        with open(chemin, "rb") as src, gzip.open(archive, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        taille = os.path.getsize(archive)
        if taille > 49 * 1024 * 1024:
            logger.warning(f"[backup] archive trop lourde pour Telegram ({taille/1e6:.0f} Mo)")
            return False
        import requests as _rq
        with open(archive, "rb") as fh:
            r = _rq.post(
                f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendDocument",
                data={"chat_id": cfg.ADMIN_CHAT_ID,
                      "caption": f"Sauvegarde {os.path.basename(chemin)} — "
                                 f"{taille/1e6:.1f} Mo compressés"},
                files={"document": fh}, timeout=180)
        if r.status_code == 200:
            logger.info("[backup] ✅ copie hors Railway envoyée sur Telegram")
            return True
        logger.error(f"[backup] Telegram {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"[backup] envoi Telegram: {e}")
        return False
    finally:
        try:
            if os.path.exists(archive): os.remove(archive)
        except OSError:
            pass


async def backup_scheduler():
    await asyncio.sleep(90)
    jour = 0
    while True:
        try:
            loop = asyncio.get_event_loop()
            path = await loop.run_in_executor(None, make_db_backup)
            if path:
                logger.info(f"[backup] ✅ {path}")
                # Une fois par semaine, la copie quitte Railway.
                if jour % 7 == 0:
                    await loop.run_in_executor(None, lambda: envoyer_sauvegarde_telegram(path))
            jour += 1
        except Exception as e:
            logger.error(f"[backup_scheduler] {e}")
        await asyncio.sleep(86400)

async def wa_digest_scheduler():
    """Vérifie toutes les 15 minutes s'il faut envoyer les résumés WhatsApp.

    send_daily_wa_digests() ne fait rien avant WA_DIGEST_HOUR et n'envoie
    qu'une fois par membre et par jour: les passages répétés sont sans effet.
    """
    from app.services.notifications import send_daily_wa_digests
    if not cfg.WA_ENABLED:
        logger.info("[wa_digest] canal WhatsApp suspendu (WA_ENABLED=0) — planificateur inactif")
        return
    await asyncio.sleep(120)
    while True:
        try:
            loop = asyncio.get_event_loop()
            n = await loop.run_in_executor(None, send_daily_wa_digests)
            if n: logger.info(f"[wa_digest] {n} résumé(s) envoyé(s)")
        except Exception as e:
            logger.error(f"[wa_digest_scheduler] {e}")
        await asyncio.sleep(900)

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

# Chemins accessibles sans avoir confirmé son adresse: pages publiques,
# gestion du compte et, bien sûr, la page de vérification elle-même. Tout le
# reste (marchés, bons de commande, résultats, sous-traitance, API) attend la
# confirmation. Liste blanche plutôt que liste noire: une nouvelle route de
# données est protégée par défaut, pas oubliée.
# "/" est comparé exactement: en préfixe il laisserait passer tout le site.
CHEMINS_LIBRES_EXACTS = frozenset((
    "/", "/login", "/register", "/logout", "/forgot", "/reset", "/tarifs",
    "/contact", "/cgu", "/confidentialite", "/mentions-legales", "/health",
    "/robots.txt", "/sitemap.xml", "/manifest.json", "/sw.js",
    "/webhooks/brevo",
))
CHEMINS_LIBRES_PREFIXES = (
    "/verifier-email", "/settings", "/static", "/admin", "/icon-",
    "/marches-publics",
    # L'invitation est une page publique: l'entreprise invitée n'a pas encore
    # de compte, elle ne peut donc pas avoir confirmé d'adresse.
    "/invitation",
)


class PorteAdminMiddleware(BaseHTTPMiddleware):
    """Rend l'administration invisible tant qu'on n'a pas ouvert sa porte.

    Le lien « Admin » a été retiré du site, mais l'adresse /admin reste
    devinable: les robots la testent en permanence. Quand ADMIN_GATE est
    renseignée, /admin répond 404 — comme une page qui n'existe pas — sauf
    pour un navigateur ayant d'abord visité l'URL secrète, qui dépose un
    cookie de passage valable trente jours.
    """
    async def dispatch(self, req, call_next):
        chemin = req.url.path
        if not cfg.ADMIN_GATE:
            return await call_next(req)

        if chemin == f"/{cfg.ADMIN_GATE.strip('/')}":
            resp = RedirectResponse("/admin/login", 302)
            resp.set_cookie("_gate", make_token("gate", cfg.ADMIN_GATE),
                            max_age=86400 * 30, httponly=True,
                            samesite="lax", secure=COOKIE_SECURE)
            logger.info("[porte admin] ouverture par l'URL privée")
            return resp

        if chemin.startswith("/admin"):
            if req.cookies.get("_gate", "") != make_token("gate", cfg.ADMIN_GATE):
                logger.info(f"[porte admin] accès refusé à {chemin} depuis {get_ip(req)}")
                # 404 et non 403: un « accès refusé » confirmerait au visiteur
                # que l'administration se trouve bien à cette adresse.
                return templates.TemplateResponse("404.html", {"request": req, "cfg": cfg,
                                                               "tr": make_t(get_lang(req)),
                                                               "lang": get_lang(req),
                                                               "dir": "rtl" if get_lang(req) == "ar" else "ltr",
                                                               "member": None},
                                                  status_code=404)
        return await call_next(req)


class DomaineCanoniqueMiddleware(BaseHTTPMiddleware):
    """Renvoie www.exemple.com vers exemple.com, une fois pour toutes.

    Servir le même site sous deux domaines fait voir à Google deux sites
    identiques qui se concurrencent, et coupe en deux le bénéfice du
    référencement. Le domaine de référence est celui de SITE_URL.
    """
    async def dispatch(self, req, call_next):
        hote = (req.headers.get("host") or "").split(":")[0].lower()
        canonique = cfg.SITE_URL.split("//")[-1].split("/")[0].lower()
        if hote.startswith("www.") and not canonique.startswith("www.") \
                and hote[4:] == canonique:
            cible = f"{cfg.SITE_URL.rstrip('/')}{req.url.path}"
            if req.url.query:
                cible += f"?{req.url.query}"
            # 301: le moteur de recherche transfère l'antériorité au domaine
            # retenu, au lieu de traiter la redirection comme provisoire.
            return RedirectResponse(cible, status_code=301)
        return await call_next(req)


class VerificationEmailMiddleware(BaseHTTPMiddleware):
    """Bloque l'accès aux données tant que l'adresse n'est pas confirmée.

    Une adresse inventée passe la validation de forme: sans ce filtre, un
    compte ouvert sur une boîte inexistante obtient un essai gratuit complet
    et ne recevra jamais la moindre alerte.
    """
    async def dispatch(self, req, call_next):
        chemin = req.url.path
        if (chemin not in CHEMINS_LIBRES_EXACTS
                and not chemin.startswith(CHEMINS_LIBRES_PREFIXES)):
            membre = get_member(req)
            if membre and not email_ok(membre):
                if chemin.startswith("/api/"):
                    return JSONResponse(
                        {"ok": False, "msg": "Adresse email non confirmée"}, 403)
                return RedirectResponse("/verifier-email?requis=1", 302)
        return await call_next(req)


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
    State.log(f"MAROC ENTREPRENEURIAT v{cfg.APP_VERSION}")
    if cfg.WA_SECRET == "atlas_wa_secret_2024":
        logger.warning("[startup] WA_SECRET utilise sa valeur par défaut — configure-la dans les variables d'environnement Railway.")
    asyncio.create_task(scheduler())
    asyncio.create_task(digest_scheduler())
    asyncio.create_task(backup_scheduler())
    asyncio.create_task(wa_digest_scheduler())
    asyncio.create_task(trial_sequence_scheduler())
    asyncio.create_task(supervision_scheduler())
    asyncio.create_task(renewal_scheduler())
    asyncio.create_task(daily_digest_scheduler())
    asyncio.create_task(recap_prep_scheduler())
    yield

app = FastAPI(lifespan=lifespan, title=cfg.APP_NAME,
              version=cfg.APP_VERSION, docs_url=None, redoc_url=None)
app.add_middleware(SecurityMiddleware)
app.add_middleware(VerificationEmailMiddleware)
app.add_middleware(DomaineCanoniqueMiddleware)
app.add_middleware(PorteAdminMiddleware)

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

def _client_parti(exc: Exception) -> bool:
    """L'exception vient-elle d'un visiteur qui a coupé la connexion ?

    Quand un onglet se ferme pendant l'envoi de la réponse, Starlette remonte
    l'incident comme une exception applicative: « No response returned. » ou
    une ressource fermée. Ce n'est pas un bug, il n'y a rien à corriger, et
    l'inscrire au journal des erreurs finit par déclencher la supervision
    pour du trafic parfaitement normal — robots inclus.
    """
    nom = type(exc).__name__
    if nom in ("ClientDisconnect", "ClosedResourceError", "BrokenResourceError",
               "EndOfStream", "ConnectionResetError", "BrokenPipeError"):
        return True
    texte = str(exc).lower()
    return ("no response returned" in texte
            or "response content shorter" in texte
            or "client disconnected" in texte)


@app.exception_handler(Exception)
async def unhandled_exception_handler(req: Request, exc: Exception):
    """Filet de sécurité pour toute exception Python non gérée explicitement
    (@app.exception_handler(500) ne couvre que les HTTPException(500) levées
    volontairement — sans ce handler, un bug applicatif imprévu remontait
    jusqu'à la page d'erreur générique non brandée de Starlette)."""
    if _client_parti(exc):
        logger.info(f"[client parti] {req.method} {req.url.path}")
        # 499 (nginx): le client a fermé avant la fin. La réponse ne partira
        # nulle part, mais le code dit la vérité dans les journaux d'accès.
        return Response(status_code=499)

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
from app.core.acheteurs import lisible as _acheteur_lisible
# Le libellé brut porte une étiquette de famille collée par la source:
# « casablanca BAIA SOCIETE CASABLANCA BAÏA ». Le client lisait deux fois
# le même nom et doutait du sérieux de la veille.
templates.env.globals["acheteur"] = _acheteur_lisible
# Le numéro tel qu'on le compose, pas tel qu'on le stocke.
from app.services.companies import telephone_lisible as _tel_lisible
templates.env.globals["tel"] = _tel_lisible
templates.env.globals["get_label"] = get_label
templates.env.globals["source_label"] = source_label
# Globales plutot que variables de contexte: toutes les pages ne passent pas
# par render(), et une marque absente faisait echouer le rendu entier.
templates.env.globals["logo"] = marque.logo
templates.env.globals["etoile"] = marque.etoile
templates.env.globals["entete_document"] = marque.entete_document
templates.env.globals["medaillon"] = marque.medaillon
templates.env.globals["favicon"] = marque.favicon_data_uri
templates.env.globals["sceau"] = marque.sceau
# Les motifs du zellige, calculés une fois et posés en fond.
templates.env.globals["fond_trame"] = marque.fond_trame
templates.env.globals["fond_rosace"] = marque.fond_rosace
# `ico` et non `icone`: la macro du rail a un paramètre de ce nom, qui
# masquerait la globale à l'intérieur de la macro.
templates.env.globals["ico"] = marque.icone
templates.env.globals["fond_frise"] = marque.fond_frise


def initiales(nom: str, email: str = "") -> str:
    """Une ou deux lettres pour la pastille de profil.

    Le nom complet s'etalait dans la barre superieure jusqu'a cent soixante
    pixels, deux fois — nom et societe —, et c'est la premiere chose que
    voyait un membre sur chaque page. Deux lettres suffisent a se reconnaitre.
    """
    mots = [m for m in (nom or "").replace("-", " ").split() if m]
    if len(mots) >= 2:
        return (mots[0][0] + mots[-1][0]).upper()
    if mots:
        return mots[0][:2].upper()
    return (email or "?")[:2].upper()


templates.env.globals["initiales"] = initiales
# La source separe « Unite de mesure » et « Quantite », la collecte les
# recolle: « 50 jour ». L'accord et le libelle se font a l'affichage, pour
# que les fiches deja en base en profitent sans etre recollectees.
from app.core import quantites
templates.env.globals["quantite_texte"] = quantites.texte
templates.env.globals["quantite_est_duree"] = quantites.est_duree
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
        "sub":          subscription_state(m),
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
            # Chiffres de la page d'accueil. Ils y remplacent trois témoignages
            # de clients inventés — noms, villes et citations — alors que la
            # plateforme n'avait encore aucun abonné. Un prospect peut vérifier
            # un compteur; il ne peut pas vérifier un témoignage anonyme, et
            # découvrir qu'il est faux coûte la vente et la réputation.
            "resultats": db.execute("SELECT COUNT(*) FROM tender_results").fetchone()[0],
            "secteurs_actifs": db.execute(
                "SELECT COUNT(DISTINCT secteur) FROM tenders "
                "WHERE statut='actif' AND COALESCE(secteur,'')<>''").fetchone()[0],
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
    # Par lots: un IN (...) de plusieurs milliers d'identifiants dépasse la
    # limite de paramètres de SQLite et ferait échouer toute la clôture.
    for i in range(0, len(expired), 500):
        lot = expired[i:i+500]
        ph  = ",".join(["?"] * len(lot))
        db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", lot)
    if expired:
        db.commit()
    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return len(expired), active

def clean_secteurs(raw: list) -> list:
    return list({s for s in raw if s and s.strip()})


def mes_secteurs(member: dict) -> list:
    """Les secteurs déclarés par le membre, nettoyés."""
    if not member:
        return []
    return clean_secteurs(json.loads(member.get("secteurs", "[]") or "[]"))


def restreindre_aux_secteurs(member: dict, where: list, params: list,
                             colonne: str = "secteur") -> list:
    """N'expose au membre que les marchés de ses secteurs. Rend ses secteurs.

    Un abonné paie pour une veille, pas pour un annuaire: lui montrer les
    mille sept cents marchés actifs alors que trente le concernent, c'est lui
    demander de faire lui-même le tri qu'on lui vend.

    **Un profil sans secteur ne restreint rien.** Filtrer sur une liste vide
    rendrait zéro résultat partout, et la plateforme paraîtrait cassée à
    l'instant précis où un nouveau venu la découvre. Les pages l'invitent
    alors à choisir ses secteurs.
    """
    secteurs = mes_secteurs(member)
    if not secteurs:
        return []
    where.append(f"{colonne} IN ({','.join('?' * len(secteurs))})")
    params.extend(secteurs)
    return secteurs

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
    # Les marchés de ses secteurs, et d'eux seuls. Toutes les autres listes
    # passent par `restreindre_aux_secteurs`; celle-ci ne le faisait pas, et
    # l'accueil montrait au membre des marchés qui ne le concernaient pas —
    # exactement le tri qu'on lui vend et qu'on lui laissait faire.
    recent = []
    if has_access(member):
        ou, params = ["statut='actif'"], []
        restreindre_aux_secteurs(member, ou, params)
        recent = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {' AND '.join(ou)} "
            f"ORDER BY scraped_at DESC LIMIT 9", params).fetchall()]
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 12").fetchall()]
    db.close()
    return render(req, "landing.html", {"stats":stats,"recent":recent,"sectors":sectors})

# La date limite est stockee telle que la source l'ecrit: « 30/09/2026 » le
# plus souvent, « 2026-09-30 » parfois. Pour la comparer en SQL il faut la
# ramener a la forme ISO, seule ordonnable comme une chaine.
DATE_LIMITE_ISO = ("CASE WHEN date_limite LIKE '__/__/____' "
                   "THEN substr(date_limite,7,4)||'-'||substr(date_limite,4,2)"
                   "||'-'||substr(date_limite,1,2) ELSE date_limite END")

# Fenetres proposees au membre, en jours. Sept jours est la plus utile: c'est
# le delai sous lequel un dossier se monte encore, au-dela on consulte, on ne
# candidate plus.
ECHEANCES = {"3": 3, "7": 7, "15": 15, "30": 30}


def filtre_echeance(valeur: str, where: list, params: list) -> None:
    """Restreint aux marches dont l'echeance tombe dans la fenetre demandee."""
    jours = ECHEANCES.get(valeur)
    if not jours:
        return
    where.append(f"COALESCE(date_limite,'') <> '' AND {DATE_LIMITE_ISO} "
                 f"BETWEEN date('now') AND date('now', '+{jours} days')")


@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, q:str="", s:str="", r:str="", t:str="",
                        e:str="", page:int=1, sort:str="recent"):
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
    # Le membre ne voit que ses secteurs. Un filtre demandé en dehors d'eux
    # est ignoré: l'adresse ne doit pas ouvrir ce que la page n'offre pas.
    siens = restreindre_aux_secteurs(m0, where, params)
    if siens and s not in siens:
        s = ""
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
        params += [f"%{q}%"]*3
    if s: where.append("secteur=?");    params.append(s)
    if r: where.append("region=?");     params.append(r)
    # Le filtre porte sur la nature de l'acheteur, pas sur la provenance de
    # l'avis: « Public » et « Prive » melangeaient les deux.
    if t in ("public", "semi_public", "prive"):
        where.append("organisme=?"); params.append(t)
    filtre_echeance(e, where, params)
    wh    = " AND ".join(where)
    order = "scraped_at DESC" if sort == "recent" else f"{DATE_LIMITE_ISO} ASC"
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(x) for x in db.execute(
        f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
        params+[per,(page-1)*per]).fetchall()]
    favs = {x[0] for x in db.execute(
        "SELECT tender_id FROM favorites WHERE member_id=?", (m0["id"],)).fetchall()}
    my_secteurs = clean_secteurs(json.loads(m0.get("secteurs","[]") or "[]"))
    # Les listes ne proposent que ce qui existe: offrir les 83 secteurs du
    # referentiel quand trente sont representes mene a des pages vides.
    secteurs_dispo = [x[0] for x in db.execute(
        "SELECT DISTINCT secteur FROM tenders WHERE statut='actif' "
        "AND type_procedure!='bon_commande' AND COALESCE(secteur,'')<>'' "
        "ORDER BY secteur").fetchall()]
    # Offrir un secteur qu'on ne peut pas afficher, c'est promettre une page
    # vide: le menu se limite à ce que le membre a choisi.
    if siens:
        secteurs_dispo = [x for x in secteurs_dispo if x in siens]
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "tenders.html", {
        "tenders":rows,"total":total,"page":page,"pages":pages,
        "q":q,"sf":s,"rf":r,"tf":t,"ef":e,"sort":sort,"favs":favs,"regions":regions,
        "secteurs_dispo":secteurs_dispo,"my_secteurs":my_secteurs})

@app.get("/bons-de-commande", response_class=HTMLResponse)
async def bons_commande_page(req: Request, q:str="", s:str="", r:str="",
                              e:str="", page:int=1, sort:str="recent"):
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
    siens = restreindre_aux_secteurs(m0, where, params)
    if siens and s not in siens:
        s = ""
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
        params += [f"%{q}%"]*3
    if s: where.append("secteur=?"); params.append(s)
    if r: where.append("region=?");  params.append(r)
    filtre_echeance(e, where, params)
    wh    = " AND ".join(where)
    order = "scraped_at DESC" if sort == "recent" else f"{DATE_LIMITE_ISO} ASC"
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(x) for x in db.execute(
        f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
        params+[per,(page-1)*per]).fetchall()]
    favs = {x[0] for x in db.execute(
        "SELECT tender_id FROM favorites WHERE member_id=?", (m0["id"],)).fetchall()}
    my_secteurs = clean_secteurs(json.loads(m0.get("secteurs","[]") or "[]"))
    secteurs_dispo = [x[0] for x in db.execute(
        "SELECT DISTINCT secteur FROM tenders WHERE statut='actif' "
        "AND type_procedure='bon_commande' AND COALESCE(secteur,'')<>'' "
        "ORDER BY secteur").fetchall()]
    if siens:
        secteurs_dispo = [x for x in secteurs_dispo if x in siens]
    db.close()
    pages = max(1,(total+per-1)//per)
    return render(req, "bons_commande.html", {
        "tenders":rows,"total":total,"page":page,"pages":pages,
        "q":q,"sf":s,"rf":r,"ef":e,"sort":sort,"favs":favs,"regions":regions,
        "secteurs_dispo":secteurs_dispo,"my_secteurs":my_secteurs})

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
    # Hors de ses secteurs, la fiche n'est pas accessible non plus: sans
    # cela, la restriction des listes ne tiendrait qu'à l'affichage, et une
    # adresse devinée ou un vieux lien ouvrirait tout. Seule exception, un
    # marché que le membre a lui-même mis en favori: le lui cacher reviendrait
    # à lui retirer ce qu'il a rangé.
    siens = mes_secteurs(m0)
    if siens and (t["secteur"] or "") not in siens:
        garde = db.execute("SELECT 1 FROM favorites WHERE member_id=? AND tender_id=?",
                           (m0["id"], tid)).fetchone()
        if not garde:
            db.close()
            return render(req, "404.html", {"hors_secteur": True}, status_code=404)
    try:
        db.execute("UPDATE tenders SET views=views+1 WHERE id=?", (tid,))
    except Exception as e:
        logger.warning(f"[views] {e}")
    secteur = t["secteur"] or ""
    # Les marchés voisins partagent le secteur de la fiche, donc la règle est
    # déjà respectée — sauf pour une fiche ouverte via un favori hors secteur,
    # où l'on ne propose rien plutôt que d'ouvrir une porte dérobée.
    montrer_voisins = bool(secteur) and (not siens or secteur in siens)
    related = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE secteur=? AND id!=? AND statut='actif' AND type_procedure=? ORDER BY scraped_at DESC LIMIT 4",
        (secteur, tid, t["type_procedure"] or "marche")).fetchall()] if montrer_voisins else []
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
async def resultats_page(req: Request, q: str = "", page: int = 1,
                         type_p: str = "", secteur: str = "", region: str = "",
                         min_montant: str = "", tri: str = "recent"):
    """Les adjudications, filtrables.

    La page ne proposait qu'une recherche en texte libre sur 1659 lignes. Or
    ce qu'un membre vient y chercher est précis: qui a gagné, à quel prix,
    dans mon secteur et ma région. Sans filtres, l'information existait mais
    restait inatteignable.
    """
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/resultats", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db(); per = 25; page = max(1, page)
    where, params = ["1=1"], []
    siens = restreindre_aux_secteurs(m0, where, params)
    if siens and secteur not in siens:
        secteur = ""
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR adjudicataire LIKE ?)")
        params += [f"%{q}%"] * 3
    if type_p in ("marche", "bon_commande"):
        where.append("type_procedure=?"); params.append(type_p)
    if secteur:
        where.append("secteur=?"); params.append(secteur)
    if region:
        where.append("region LIKE ?"); params.append(f"%{region}%")
    seuil = 0.0
    if min_montant:
        from app.services.soustraitance import parse_montant
        seuil = parse_montant(min_montant)
        if seuil > 0:
            where.append("montant_num >= ?"); params.append(seuil)
    # Le tri par montant place les résultats non chiffrés en dernier plutôt
    # qu'en tête: un 0 signifie « montant illisible », pas « marché gratuit ».
    ordre = {"recent":  "scraped_at DESC",
             "montant": "montant_num DESC",
             "ancien":  "scraped_at ASC"}.get(tri, "scraped_at DESC")
    wh    = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tender_results WHERE {wh}", params).fetchone()[0]
    rows  = [dict(x) for x in db.execute(
        f"SELECT * FROM tender_results WHERE {wh} ORDER BY {ordre} LIMIT ? OFFSET ?",
        params + [per, (page - 1) * per]).fetchall()]
    # Les listes déroulantes ne montrent que ce qui existe vraiment en base:
    # proposer les 83 secteurs du référentiel quand 30 sont représentés fait
    # tomber le membre sur des pages vides.
    secteurs_dispo = [r[0] for r in db.execute(
        "SELECT DISTINCT secteur FROM tender_results "
        "WHERE COALESCE(secteur,'')<>'' ORDER BY secteur").fetchall()]
    if siens:
        secteurs_dispo = [x for x in secteurs_dispo if x in siens]
    regions_dispo = [r[0] for r in db.execute(
        "SELECT DISTINCT region FROM tender_results "
        "WHERE COALESCE(region,'')<>'' ORDER BY region").fetchall()]
    db.close()
    pages = max(1, (total + per - 1) // per)
    return render(req, "resultats.html", {
        "resultats": rows, "total": total, "page": page, "pages": pages, "q": q,
        "type_p": type_p, "secteur": secteur, "region": region,
        "min_montant": min_montant, "tri": tri,
        "secteurs_dispo": secteurs_dispo, "regions_dispo": regions_dispo,
        "my_secteurs": siens})

@app.get("/resultats/{rid}/{doc}")
async def resultat_doc_redirect(req: Request, rid: str, doc: str):
    """Sert la pièce (D.A.O ou P.V) depuis la plateforme.

    La route redirigeait vers l'agrégateur: le navigateur quittait le
    domaine et affichait la source dans sa barre d'adresse — un abonné
    découvrait ainsi d'où viennent les données, et n'avait plus besoin de
    l'abonnement. Le fichier transite maintenant par le serveur, qui ouvre
    sa propre session chez la source, et il repart nommé d'après l'objet du
    marché plutôt que « downoald-pv ».
    """
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/resultats", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    if doc not in ("dao", "pv"):
        return RedirectResponse("/resultats", 302)
    db = get_db()
    r = db.execute("SELECT objet, dao_url, pv_url FROM tender_results WHERE id=?",
                   (rid,)).fetchone()
    db.close()
    if not r:
        return RedirectResponse("/resultats", 302)
    url = (r["dao_url"] if doc == "dao" else r["pv_url"]) or ""
    if not url:
        return RedirectResponse("/resultats?piece=absente", 302)

    from app.services import pieces
    loop = asyncio.get_event_loop()
    contenu, type_c, ext = await loop.run_in_executor(None, pieces.recuperer, url)
    if not contenu:
        # Ni redirection de secours vers la source, ni fichier vide: on le dit.
        return RedirectResponse("/resultats?piece=indisponible", 302)

    nom = pieces.nom_fichier(r["objet"], doc, ext)
    return Response(contenu, media_type=type_c, headers={
        "Content-Disposition": f'attachment; filename="{nom}"',
        "Cache-Control": "private, max-age=86400",
    })


# ══════════════════════════════════════════════════════════
# SOUS-TRAITANCE — annonces entre membres (demande / offre)
# avec messagerie interne, réservé aux membres actifs (has_access)
# ══════════════════════════════════════════════════════════
@app.get("/admin/recap", response_class=HTMLResponse)
async def admin_recap(req: Request, jour: str = ""):
    """Un bouton WhatsApp par membre, avec son recapitulatif du jour.

    L'envoi automatique demande un compte Meta approuve et un modele de
    message valide. En attendant, l'envoi reste manuel — et pour les
    premiers abonnes, un message ecrit par le fondateur vaut mieux qu'une
    notification de plus. Ce qui manquait n'etait pas le canal mais la
    matiere: retrouver, pour chaque membre, ses marches du jour.
    """
    if not _is_admin(req):
        return RedirectResponse("/admin/login", 302)
    from app.services.recap import lot_du_jour, preparer
    jour = jour or date.today().strftime("%Y-%m-%d")
    lot = lot_du_jour(jour)
    # Lot absent: soit le préparateur du soir n'est pas encore passé, soit on
    # consulte un jour passé. On le constitue à la demande plutôt que de
    # montrer une page vide — mais c'est bien le passage de 21 h qui le fige.
    if not lot["lignes"]:
        preparer(jour)
        lot = lot_du_jour(jour)
    return render(req, "admin_recap.html", {
        "lignes": lot["lignes"], "jour": jour, "prepare_at": lot["prepare_at"],
        "envoyes": lot["envoyes"], "restants": lot["restants"],
        "csrf_token": get_csrf_token(req) or secrets.token_urlsafe(24)})


@app.post("/admin/recap/envoye")
async def admin_recap_envoye(req: Request, member_id: int = Form(...),
                             jour: str = Form(""), defaire: str = Form(""),
                             csrf_token: str = Form("")):
    """Note qu'un membre a bien reçu son message — ou défait la marque.

    Sans cette trace, deux membres servis deux fois et un troisième oublié:
    rien, sur la page, ne distinguait ceux à qui on venait d'écrire.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    from app.services.recap import annuler_envoi, marquer_envoye
    jour = jour or date.today().strftime("%Y-%m-%d")
    if defaire:
        annuler_envoi(member_id, jour)
    else:
        marquer_envoye(member_id, jour)
    return RedirectResponse(f"/admin/recap?jour={jour}", 302)


@app.get("/recap/{jeton_recu}", response_class=HTMLResponse)
async def recap_membre(req: Request, jeton_recu: str):
    """Le recapitulatif qu'un membre ouvre depuis WhatsApp.

    Accessible sans connexion: le destinataire lit souvent sur un telephone
    ou il n'est pas connecte, et lui demander ses identifiants avant de lui
    montrer ce qu'on vient de lui promettre le ferait fermer la page. Le
    lien est signe, ne vaut que pour un membre et un jour, et expire.
    """
    from app.services.recap import lire_jeton, marches_du_jour
    member_id, jour = lire_jeton(jeton_recu)
    if not member_id:
        return render(req, "404.html", {}, status_code=404)
    db = get_db()
    membre = db.execute("SELECT * FROM members WHERE id=? AND actif=1",
                        (member_id,)).fetchone()
    db.close()
    if not membre:
        return render(req, "404.html", {}, status_code=404)
    membre = dict(membre)
    return render(req, "recap.html", {
        "membre": membre, "jour": jour,
        "marches": marches_du_jour(membre, jour),
        "mes_secteurs": clean_secteurs(json.loads(membre.get("secteurs", "[]") or "[]")),
    })


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
    # La place de marche souffrait du demarrage a froid: personne ne publie
    # tant que personne n'est la. Elle s'ouvre donc sur ce que la base sait
    # deja — les chantiers qui viennent d'etre attribues dans les secteurs du
    # membre, avec le telephone de l'attributaire quand l'annuaire le
    # connait. Aucune annonce n'est requise pour qu'une piste existe.
    from app.services.soustraitance import opportunites_pour, message_de_contact
    pistes = []
    if not mine:
        try:
            pistes = opportunites_pour(m0, limite=6)
            for piste in pistes:
                piste["message"] = message_de_contact(m0, piste)
        except Exception as e:
            logger.error(f"[sous-traitance] pistes indisponibles: {e}")
    return render(req, "subtraitance.html", {
        "posts":rows,"total":total,"page":page,"pages":pages,"tf":tp,"sf":s,"rf":r,
        "mine":mine,"pistes":pistes,
        "sans_secteur": not clean_secteurs(json.loads(m0.get("secteurs","[]") or "[]"))})

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
    tender_id = (req.query_params.get("marche") or "")[:60]
    db.execute("""INSERT INTO subcontract_posts
                  (id,member_id,type,titre,secteur,region,budget,date_limite,description,
                   statut,created_at,tender_id)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               (pid, m0["id"], type if type in ("demande","offre") else "demande",
                titre.strip()[:200], secteur, region, budget.strip()[:100], date_limite,
                description.strip()[:4000], "actif", datetime.now().isoformat(), tender_id))
    db.commit(); db.close()
    # Une annonce que personne ne voit ne sert à rien: les membres dont le
    # métier et la zone correspondent sont prévenus immédiatement.
    try:
        from app.services.soustraitance import notifier_nouvelle_annonce
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: notifier_nouvelle_annonce({
            "id": pid, "member_id": m0["id"], "titre": titre.strip()[:200],
            "secteur": secteur, "region": region, "budget": budget.strip()[:100]}))
    except Exception as e:
        logger.error(f"[sous-traitance] alerte annonce: {e}")
    return RedirectResponse(f"/sous-traitance/{pid}?ok=1", 302)

@app.get("/sous-traitance/profil", response_class=HTMLResponse)
async def st_profil_get(req: Request):
    """Profil de sous-traitance: ce que l'entreprise sait faire, où, avec quoi.

    Sans lui, celui qui reçoit une offre ne sait rien de celui qui la fait.
    """
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/sous-traitance/profil", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db()
    p = db.execute("SELECT * FROM subcontract_profiles WHERE member_id=?", (m0["id"],)).fetchone()
    note = db.execute(
        "SELECT ROUND(AVG(rating),1) a, COUNT(*) n FROM subcontract_ratings WHERE rated_id=?",
        (m0["id"],)).fetchone()
    offres = db.execute("SELECT COUNT(*) FROM subcontract_offers WHERE member_id=?",
                        (m0["id"],)).fetchone()[0]
    db.close()
    profil = dict(p) if p else {}
    return render(req, "st_profil.html", {
        "profil": profil,
        "metiers": json.loads(profil.get("metiers") or "[]"),
        "zones": json.loads(profil.get("zones") or "[]"),
        "note": {"avg": note["a"], "n": note["n"]} if note and note["n"] else None,
        "nb_offres": offres})


@app.post("/sous-traitance/profil")
async def st_profil_post(req: Request, raison_sociale: str = Form(""), effectif: str = Form(""),
                         moyens: str = Form(""), experience: str = Form(""),
                         references_txt: str = Form(""), certifications: str = Form(""),
                         disponible: str = Form(""), metiers: list = Form(default=[]),
                         zones: list = Form(default=[]), csrf_token: str = Form("")):
    m0 = get_member(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    maintenant = datetime.now().isoformat()
    db = get_db()
    db.execute("""INSERT INTO subcontract_profiles(member_id,raison_sociale,metiers,zones,
                     effectif,moyens,experience,references_txt,certifications,disponible,
                     created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(member_id) DO UPDATE SET
                     raison_sociale=excluded.raison_sociale, metiers=excluded.metiers,
                     zones=excluded.zones, effectif=excluded.effectif, moyens=excluded.moyens,
                     experience=excluded.experience, references_txt=excluded.references_txt,
                     certifications=excluded.certifications, disponible=excluded.disponible,
                     updated_at=excluded.updated_at""",
               (m0["id"], raison_sociale[:200], json.dumps(clean_secteurs(metiers)),
                json.dumps([z for z in zones if z][:12]), effectif[:60], moyens[:1000],
                experience[:60], references_txt[:2000], certifications[:500],
                1 if disponible else 0, maintenant, maintenant))
    db.commit(); db.close()
    return RedirectResponse("/sous-traitance/profil?ok=1", 302)


@app.get("/sous-traitance/opportunites", response_class=HTMLResponse)
async def st_opportunites(req: Request):
    """Chantiers attribués qui vont chercher des sous-traitants.

    C'est l'inverse d'une bourse d'annonces: personne n'a besoin de publier
    quoi que ce soit pour que le membre voie une piste.
    """
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login?next=/sous-traitance/opportunites", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    from app.services.soustraitance import opportunites_pour, message_de_contact
    pistes = opportunites_pour(m0)
    for p in pistes:
        p["message"] = message_de_contact(m0, p)
    return render(req, "st_opportunites.html", {"pistes": pistes})


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
    # Offres structurées: l'auteur les compare toutes, un candidat ne voit
    # que la sienne — le prix d'un concurrent ne le regarde pas.
    if is_owner:
        offres = [dict(x) for x in db.execute(
            """SELECT o.*, m.nom, m.company,
                      (SELECT ROUND(AVG(rating),1) FROM subcontract_ratings WHERE rated_id=o.member_id) AS note,
                      (SELECT COUNT(*) FROM subcontract_ratings WHERE rated_id=o.member_id) AS nb_avis,
                      (SELECT COUNT(*) FROM subcontract_offers WHERE member_id=o.member_id) AS nb_offres
               FROM subcontract_offers o JOIN members m ON m.id=o.member_id
               WHERE o.post_id=? ORDER BY o.created_at ASC""", (pid,)).fetchall()]
    else:
        offres = [dict(x) for x in db.execute(
            "SELECT * FROM subcontract_offers WHERE post_id=? AND member_id=?",
            (pid, m0["id"])).fetchall()]
    marche = None
    if post.get("tender_id"):
        t = db.execute("SELECT id,objet,acheteur,date_limite,montant,region FROM tenders WHERE id=?",
                       (post["tender_id"],)).fetchone()
        marche = dict(t) if t else None
    db.close()
    return render(req, "subtraitance_detail.html", {
        "post": post, "author": dict(author) if author else {}, "is_owner": is_owner,
        "threads": threads, "thread_messages": thread_messages, "other_id": other_id,
        "counterpart_id": counterpart_id, "counterpart_rating": counterpart_rating,
        "my_rating_given": my_rating_given, "offres": offres, "marche": marche,
        "mon_offre": offres[0] if (offres and not is_owner) else None})

UPLOAD_DIR = "data/uploads"


@app.get("/sous-traitance/{pid}/declaration", response_class=HTMLResponse)
async def st_declaration(req: Request, pid: str):
    """Déclaration de sous-traitance à remettre au maître d'ouvrage.

    Le document reprend l'offre retenue et le marché d'origine. Les limites
    légales (part sous-traitable, corps d'état principal) sont rappelées mais
    restent sous la responsabilité de l'entreprise: le texte applicable est
    le décret des marchés publics, pas cette page.
    """
    m0 = get_member(req)
    if not m0:
        return RedirectResponse("/login", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)
    db = get_db()
    post = db.execute("SELECT * FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if not post or post["member_id"] != m0["id"]:
        db.close()
        return HTMLResponse("Accès refusé", 403)
    offre = db.execute(
        """SELECT o.*, m.nom, m.company, m.phone, m.email,
                  p.raison_sociale, p.certifications
           FROM subcontract_offers o JOIN members m ON m.id=o.member_id
           LEFT JOIN subcontract_profiles p ON p.member_id=o.member_id
           WHERE o.post_id=? AND o.statut='retenue'""", (pid,)).fetchone()
    marche = None
    if post["tender_id"]:
        t = db.execute("SELECT id,objet,acheteur FROM tenders WHERE id=?",
                       (post["tender_id"],)).fetchone()
        marche = dict(t) if t else None
    db.close()
    if not offre:
        return RedirectResponse(f"/sous-traitance/{pid}?err=offre", 302)
    return render(req, "st_declaration.html", {
        "post": dict(post), "offre": dict(offre), "marche": marche,
        "donneur": m0, "aujourdhui": date.today().strftime("%d/%m/%Y")})


@app.post("/sous-traitance/{pid}/offre")
async def subtraitance_offre(req: Request, pid: str):
    """Dépôt d'une offre chiffrée: prix, délai, message et pièce jointe.

    Une conversation libre ne se compare pas. Ici l'auteur de l'annonce
    obtient des propositions alignées sur les mêmes colonnes.
    """
    m0 = get_member(req)
    form = await req.form()
    csrf_guard(req, form.get("csrf_token", ""))
    if not m0:
        return RedirectResponse(f"/login?next=/sous-traitance/{pid}", 302)
    if not has_access(m0):
        return RedirectResponse("/tarifs?locked=1", 302)

    db = get_db()
    post = db.execute("SELECT * FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if not post or post["member_id"] == m0["id"] or post["statut"] != "actif":
        db.close()
        return RedirectResponse(f"/sous-traitance/{pid}?err=1", 302)

    nom_fichier = ""
    fichier = form.get("piece_jointe")
    if fichier is not None and getattr(fichier, "filename", ""):
        contenu = await fichier.read()
        if len(contenu) > 5 * 1024 * 1024:
            db.close()
            return RedirectResponse(f"/sous-traitance/{pid}?err=taille", 302)
        ext = os.path.splitext(fichier.filename)[1].lower()
        # Une pièce jointe de sous-traitance est un devis ou une référence:
        # pas de format exécutable, jamais.
        if ext not in (".pdf", ".jpg", ".jpeg", ".png"):
            db.close()
            return RedirectResponse(f"/sous-traitance/{pid}?err=format", 302)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        nom_fichier = f"{pid}_{m0['id']}_{secrets.token_urlsafe(6)}{ext}"
        with open(os.path.join(UPLOAD_DIR, nom_fichier), "wb") as fh:
            fh.write(contenu)

    maintenant = datetime.now().isoformat()
    db.execute("""INSERT INTO subcontract_offers(post_id,member_id,prix,delai,message,
                     piece_jointe,statut,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,'envoyee',?,?)
                  ON CONFLICT(post_id,member_id) DO UPDATE SET
                     prix=excluded.prix, delai=excluded.delai, message=excluded.message,
                     piece_jointe=CASE WHEN excluded.piece_jointe!='' THEN excluded.piece_jointe
                                       ELSE subcontract_offers.piece_jointe END,
                     updated_at=excluded.updated_at""",
               (pid, m0["id"], (form.get("prix") or "")[:60], (form.get("delai") or "")[:60],
                (form.get("message") or "")[:2000], nom_fichier, maintenant, maintenant))
    db.commit()
    auteur = db.execute("SELECT email,nom,notif_email FROM members WHERE id=?",
                        (post["member_id"],)).fetchone()
    db.close()

    if auteur and auteur["notif_email"] and auteur["email"]:
        from app.services.notifications import email_send
        lien = f"{cfg.SITE_URL}/sous-traitance/{pid}"
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: email_send(
            auteur["email"], f"Nouvelle offre pour « {post['titre'][:50]} »",
            f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto">
              <h2 style="font-size:19px;color:#1e1611">Vous avez reçu une offre</h2>
              <p style="font-size:15px;color:#4a4a4a">{(m0.get('company') or m0.get('nom') or '')} a répondu à votre annonce.</p>
              <a href="{lien}" style="display:inline-block;padding:12px 24px;background:#f2662d;
                 color:#fff;border-radius:8px;text-decoration:none;font-weight:600">Comparer les offres</a>
            </div>"""))
    return RedirectResponse(f"/sous-traitance/{pid}?offre=ok", 302)


@app.get("/sous-traitance/{pid}/piece/{nom}")
async def subtraitance_piece(req: Request, pid: str, nom: str):
    """Pièce jointe d'une offre: visible par l'auteur de l'annonce et par
    celui qui l'a déposée, personne d'autre."""
    m0 = get_member(req)
    if not m0 or not has_access(m0):
        return RedirectResponse("/login", 302)
    sur = os.path.basename(nom)
    db = get_db()
    offre = db.execute(
        "SELECT o.*, p.member_id AS auteur FROM subcontract_offers o "
        "JOIN subcontract_posts p ON p.id=o.post_id WHERE o.post_id=? AND o.piece_jointe=?",
        (pid, sur)).fetchone()
    db.close()
    if not offre or m0["id"] not in (offre["member_id"], offre["auteur"]):
        return HTMLResponse("Accès refusé", 403)
    chemin = os.path.join(UPLOAD_DIR, sur)
    if not os.path.isfile(chemin):
        return HTMLResponse("Fichier introuvable", 404)
    return FileResponse(chemin, filename=sur)


@app.post("/sous-traitance/{pid}/offre/{oid}/retenir")
async def subtraitance_retenir(req: Request, pid: str, oid: int, csrf_token: str = Form("")):
    """L'auteur retient une offre: les autres candidats sont informés."""
    m0 = get_member(req)
    csrf_guard(req, csrf_token)
    if not m0:
        return RedirectResponse("/login", 302)
    db = get_db()
    post = db.execute("SELECT * FROM subcontract_posts WHERE id=?", (pid,)).fetchone()
    if not post or post["member_id"] != m0["id"]:
        db.close()
        return HTMLResponse("Accès refusé", 403)
    db.execute("UPDATE subcontract_offers SET statut='ecartee', updated_at=? WHERE post_id=?",
               (datetime.now().isoformat(), pid))
    db.execute("UPDATE subcontract_offers SET statut='retenue', updated_at=? WHERE id=? AND post_id=?",
               (datetime.now().isoformat(), oid, pid))
    db.commit(); db.close()
    return RedirectResponse(f"/sous-traitance/{pid}?retenue=1", 302)


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
    # Les compteurs ne portent que sur ses secteurs. Annoncer « 1 777 marchés
    # actifs » à qui n'en voit que cent quatre, c'est afficher un chiffre
    # qu'aucune de ses pages ne confirme.
    portee = ("AND secteur IN (%s)" % ",".join("?" * len(ms))) if ms else ""
    stats = {
        "favs":   db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?",(member["id"],)).fetchone()[0],
        "notifs": db.execute("SELECT COUNT(*) FROM notif_log WHERE member_id=?",(member["id"],)).fetchone()[0],
        "active": db.execute(f"SELECT COUNT(*) FROM tenders WHERE statut='actif' {portee}", ms).fetchone()[0],
        "today":  db.execute(f"SELECT COUNT(*) FROM tenders WHERE statut='actif' "
                             f"AND scraped_at>=date('now') {portee}", ms).fetchone()[0],
        "recs":   len(recs),
    }
    # Répartition par grande famille (Travaux / Équipements / Services) — les
    # 83 codes du référentiel commencent par T/P/S selon leur catégorie.
    grp_rows = db.execute(
        f"SELECT substr(secteur,1,1) g, COUNT(*) n FROM tenders "
        f"WHERE statut='actif' AND secteur!='' {portee} GROUP BY g", ms).fetchall()
    grp_labels = {"T": "Travaux", "P": "Équipements", "S": "Services"}
    sector_dist = [{"code": r["g"], "label": grp_labels.get(r["g"], r["g"]), "n": r["n"]} for r in grp_rows if r["g"] in grp_labels]
    sector_dist.sort(key=lambda x: -x["n"])
    # Tendance hebdomadaire (8 dernières semaines) pour le graphique d'évolution.
    trend_rows = db.execute(
        f"""SELECT strftime('%Y-%W', scraped_at) wk, COUNT(*) n FROM tenders
            WHERE statut='actif' {portee} GROUP BY wk ORDER BY wk DESC LIMIT 8""",
        ms).fetchall()
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
    # Au moins un secteur, et ce n'est pas une formalité: un profil vide ne
    # restreint rien, si bien que le nouvel inscrit recevait les deux mille
    # quatre cents marchés actifs — l'inverse de ce qu'il vient chercher. Dix
    # secondes ici lui évitent de juger la plateforme sur un flot illisible.
    elif not clean_secteurs(secteurs_sel): err = tr_("err_secteur_requis", lang)
    else:
        ok, msg = validate_password(pw, lang)
        if not ok: err = msg
    if err: return render(req,"register.html",{"err":err,"vals":vals})
    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?",(email,)).fetchone():
            return render(req,"register.html",{"err":tr_("err_email_taken",lang),"vals":vals})
        sects       = clean_secteurs(secteurs_sel)
        now         = datetime.now()
        trial_start = now.strftime("%Y-%m-%d")
        trial_ends  = (now + timedelta(days=cfg.TRIAL_DAYS)).strftime("%Y-%m-%d")
        created_at  = now.isoformat()
        session_tok = make_session_token()
        my_ref_code = secrets.token_urlsafe(5).upper().replace("_","A").replace("-","B")[:7]
        referred_by = 0
        if ref:
            r = db.execute("SELECT id FROM members WHERE referral_code=?", (ref.strip().upper(),)).fetchone()
            if r: referred_by = r["id"]
        email_token   = secrets.token_urlsafe(32)
        token_expires = (now + timedelta(days=7)).isoformat()
        cur = db.execute(
            """INSERT INTO members(nom,email,phone,company,pw_hash,secteurs,plan,created_at,
               trial_start,trial_ends,subscription_status,session_token,referral_code,referred_by,
               email_verified,email_token,email_token_expires)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nom,email,phone,company,hash_pw(pw),json.dumps(sects),"free",created_at,
             trial_start,trial_ends,"TRIAL",session_tok,my_ref_code,referred_by,
             0,email_token,token_expires))
        db.execute(
            """INSERT INTO subscriptions(member_id,plan_id,price,currency,status,
               trial_start,trial_end,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (cur.lastrowid, "trial", 0, "MAD", "TRIAL", trial_start, trial_ends, created_at, created_at))
        db.commit()
    finally: db.close()
    envoyer_lien_verification(email, email_token, lang)
    resp = RedirectResponse("/verifier-email?envoye=1",302)
    resp.set_cookie("_session", session_tok,
                    max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

def envoyer_lien_verification(email: str, token: str, lang: str = "fr"):
    """Envoie le lien de confirmation, hors du thread de la requête.

    Un provider lent ne doit jamais retarder l'inscription: l'envoi part en
    tâche de fond, exactement comme le lien de réinitialisation.
    """
    lien = f"{cfg.SITE_URL}/verifier-email?token={token}"
    try:
        from app.services.notifications import email_send
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: email_send(
            email, tr_("email_verif_subject", lang),
            f"""<h2>{tr_("email_verif_h2", lang)}</h2>
            <p>{tr_("email_verif_p", lang)}</p>
            <a href="{lien}" style="display:inline-block;padding:12px 24px;background:#f2662d;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
              {tr_("email_verif_btn", lang)}
            </a>
            <p style="color:#666;font-size:12px;margin-top:16px">{tr_("email_verif_expiry", lang)}</p>"""))
    except Exception as e:
        logger.error(f"[verif email] {e}")


@app.get("/verifier-email", response_class=HTMLResponse)
async def verifier_email(req: Request, token: str = "", envoye: int = 0, requis: int = 0):
    lang   = get_lang(req)
    membre = get_member(req)
    if token:
        db = get_db()
        m  = db.execute("SELECT * FROM members WHERE email_token=? AND email_token!=''",
                        (token,)).fetchone()
        if not m:
            db.close()
            return render(req, "verifier_email.html",
                          {"err": tr_("verif_err_invalide", lang)}, status_code=400)
        expire = datetime.fromisoformat(m["email_token_expires"] or "2000-01-01")
        if expire < datetime.now():
            db.close()
            return render(req, "verifier_email.html",
                          {"expire": True, "email": m["email"]}, status_code=400)
        db.execute("""UPDATE members SET email_verified=1, email_token='',
                      email_token_expires='',
                      alertes_depuis=? WHERE id=?""",
                   (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m["id"]))
        db.commit(); db.close()
        logger.info(f"[Verif] ✅ {m['email']} a confirmé son adresse")
        # Le membre devient joignable à cet instant: c'est le point de départ
        # de ses alertes. Ce qui existait avant lui est annoncé en un seul
        # message, pas déversé marché par marché.
        from app.services.notifications import envoyer_bienvenue
        try:
            envoyer_bienvenue(m["id"])
        except Exception as e:
            logger.error(f"[bienvenue] {e}", exc_info=True)
        # Le lien peut être ouvert depuis un autre appareil que celui de
        # l'inscription: sans session, on renvoie vers la connexion.
        return RedirectResponse("/dashboard?verifie=1" if membre else "/login?verifie=1", 302)

    if not membre:
        return RedirectResponse("/login", 302)
    if email_ok(membre):
        return RedirectResponse("/dashboard", 302)
    return render(req, "verifier_email.html",
                  {"envoye": bool(envoye), "requis": bool(requis), "email": membre["email"]})


@app.post("/verifier-email/renvoyer")
async def renvoyer_verification(req: Request, csrf_token: str = Form("")):
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    membre = get_member(req)
    if not membre:
        return RedirectResponse("/login", 302)
    if email_ok(membre):
        return RedirectResponse("/dashboard", 302)
    if not check_rate_limit(f"verif_{membre['id']}", 3, 3600):
        return render(req, "verifier_email.html",
                      {"err": tr_("err_too_many_generic", lang), "email": membre["email"]})
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute("UPDATE members SET email_token=?, email_token_expires=? WHERE id=?",
               (token, (datetime.now() + timedelta(days=7)).isoformat(), membre["id"]))
    db.commit(); db.close()
    envoyer_lien_verification(membre["email"], token, lang)
    return RedirectResponse("/verifier-email?envoye=1", 302)


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
    db2 = get_db()
    referral_count = db2.execute("SELECT COUNT(*) FROM members WHERE referred_by=?", (member["id"],)).fetchone()[0]
    all_regions = [r[0] for r in db2.execute(
        "SELECT DISTINCT region FROM tenders WHERE region!='' AND statut='actif' ORDER BY region LIMIT 80").fetchall()]
    db2.close()
    try:
        my_regions = json.loads(member.get("notif_regions","[]") or "[]")
    except json.JSONDecodeError:
        my_regions = []
    try:
        my_types = json.loads(member.get("notif_types","[]") or "[]")
    except json.JSONDecodeError:
        my_types = []
    return render(req,"settings.html",{
        "ms": ms, "referral_count": referral_count, "all_regions": all_regions,
        "my_regions": my_regions, "my_types": my_types})

@app.post("/settings")
async def settings_post(req: Request,
    nom:str=Form(""), phone:str=Form(""), company:str=Form(""),
    csrf_token:str=Form(""), secteurs_sel:list=Form(default=[])):
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login",302)
    if not check_rate_limit(f"settings_{member['id']}", 15, 600):
        return RedirectResponse("/settings",302)
    form     = await req.form()
    n_email  = 1 if form.get("notif_email")  else 0
    n_digest = 1 if form.get("notif_digest") else 0
    n_wa     = 1 if form.get("notif_wa")     else 0
    # Rythme des alertes email: un message par marché, ou un seul par jour.
    rythme   = form.get("notif_rythme", "direct")
    if rythme not in ("direct", "quotidien"):
        rythme = "direct"
    whatsapp = form.get("whatsapp","").strip()
    sects    = clean_secteurs(secteurs_sel)
    # Filtres du moteur de correspondance
    regions  = [r.strip() for r in form.getlist("notif_regions_sel") if r and r.strip()]
    types    = [t.strip() for t in form.getlist("notif_types_sel") if t and t.strip()]
    keywords = form.get("notif_keywords","").strip()[:500]
    try:
        min_budget = max(0, int(float(form.get("notif_min_budget") or 0)))
    except (TypeError, ValueError):
        min_budget = 0
    # Changer de numéro invalide la vérification: le nouveau numéro doit être
    # confirmé à son tour avant de recevoir la moindre alerte WhatsApp.
    wa_verified = member.get("whatsapp_verified", 0)
    if whatsapp != (member.get("whatsapp") or ""):
        wa_verified = 0
    db = get_db()
    try:
        db.execute(
            # La colonne `telegram` subsiste en base — on ne détruit pas les
            # données d'anciens membres — mais plus rien ne l'alimente ni ne
            # la lit: le canal a été retiré de l'offre.
            """UPDATE members SET nom=?,phone=?,company=?,whatsapp=?,
               notif_email=?,notif_wa=?,notif_digest=?,notif_rythme=?,
               secteurs=?,notif_regions=?,notif_types=?,notif_keywords=?,
               notif_min_budget=?,whatsapp_verified=? WHERE id=?""",
            (nom,phone,company,whatsapp,n_email,n_wa,n_digest,rythme,
             json.dumps(sects),json.dumps(regions),json.dumps(types),keywords,min_budget,
             wa_verified,member["id"]))
        db.commit()
    finally: db.close()
    # Pas de rattrapage rétroactif ici: élargir ses secteurs déclencherait
    # sinon des dizaines d'emails d'un coup. Les marchés déjà ouverts sont
    # consultables sur le tableau de bord; les alertes reprennent leur cours
    # normal pour les marchés collectés à partir de maintenant.
    return RedirectResponse("/settings?ok=1",302)

@app.post("/settings/whatsapp/send-code")
async def wa_send_code(req: Request, csrf_token: str = Form("")):
    """Envoie un code de vérification au numéro WhatsApp du membre (opt-in)."""
    if not cfg.WA_ENABLED:
        return RedirectResponse("/settings", 302)
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login", 302)
    if not member.get("whatsapp"):
        return RedirectResponse("/settings?wa=nonumber", 302)
    if not check_rate_limit(f"wa_code_{member['id']}", 5, 3600):
        return RedirectResponse("/settings?wa=toomany", 302)
    from app.services.notifications import send_wa_verification
    code    = f"{secrets.randbelow(1000000):06d}"
    expires = (datetime.now() + timedelta(minutes=15)).isoformat()
    db = get_db()
    db.execute("UPDATE members SET wa_verify_code=?, wa_verify_expires=? WHERE id=?",
               (code, expires, member["id"]))
    db.commit(); db.close()
    ok = send_wa_verification(member["whatsapp"], code)
    return RedirectResponse(f"/settings?wa={'sent' if ok else 'failed'}", 302)

@app.post("/settings/whatsapp/confirm")
async def wa_confirm(req: Request, code: str = Form(""), csrf_token: str = Form("")):
    """Confirme le code reçu et enregistre le consentement WhatsApp."""
    if not cfg.WA_ENABLED:
        return RedirectResponse("/settings", 302)
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login", 302)
    if not check_rate_limit(f"wa_confirm_{member['id']}", 10, 900):
        return RedirectResponse("/settings?wa=toomany", 302)
    stored  = (member.get("wa_verify_code") or "").strip()
    expires = member.get("wa_verify_expires") or ""
    if not stored or not expires:
        return RedirectResponse("/settings?wa=nocode", 302)
    try:
        if datetime.fromisoformat(expires) < datetime.now():
            return RedirectResponse("/settings?wa=expired", 302)
    except ValueError:
        return RedirectResponse("/settings?wa=expired", 302)
    if not secrets.compare_digest(stored, code.strip()):
        return RedirectResponse("/settings?wa=wrong", 302)
    db = get_db()
    db.execute(
        """UPDATE members SET whatsapp_verified=1, wa_optin_at=?, notif_wa=1,
           wa_verify_code='', wa_verify_expires='' WHERE id=?""",
        (datetime.now().isoformat(), member["id"]))
    db.commit(); db.close()
    return RedirectResponse("/settings?wa=verified", 302)

@app.post("/settings/whatsapp/optout")
async def wa_optout(req: Request, csrf_token: str = Form("")):
    """Retrait du consentement WhatsApp (opt-out immédiat)."""
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login", 302)
    db = get_db()
    db.execute(
        "UPDATE members SET notif_wa=0, whatsapp_verified=0, wa_optin_at='' WHERE id=?",
        (member["id"],))
    db.commit(); db.close()
    return RedirectResponse("/settings?wa=optout", 302)

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
            "whatsapp": member.get("whatsapp"),
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

def _purge_member(mid: int) -> dict:
    """Efface un compte et tout ce qui s'y rattache. Retourne le décompte.

    Utilisée aussi bien par la suppression volontaire du membre que par la
    suppression administrative: une seule implémentation, donc aucun risque
    qu'un des deux chemins oublie une table et laisse des données derrière.
    Les échanges et évaluations de sous-traitance partent avec le compte
    plutôt que d'être anonymisés — on ne fait pas de compromis partiel sur
    une demande d'effacement.

    Les paiements, abonnements et documents sont conservés volontairement:
    ce sont des pièces comptables. Ils sont détachés du membre (member_id
    remis à 0) pour ne plus permettre de l'identifier.
    """
    deleted = {}
    db = get_db()
    try:
        for table, where in (
            ("favorites",            "member_id=?"),
            ("notif_log",            "member_id=?"),
            ("notif_queue",          "member_id=?"),
            ("subcontract_messages", "post_id IN (SELECT id FROM subcontract_posts WHERE member_id=?)"),
            ("subcontract_messages", "sender_id=? OR recipient_id=?"),
            ("subcontract_ratings",  "rater_id=? OR rated_id=?"),
            ("subcontract_reports",  "reporter_id=?"),
            ("subcontract_posts",    "member_id=?"),
        ):
            params = (mid, mid) if where.count("?") == 2 else (mid,)
            cur = db.execute(f"DELETE FROM {table} WHERE {where}", params)
            deleted[table] = deleted.get(table, 0) + cur.rowcount
        # Pièces comptables: conservées mais anonymisées.
        for table in ("payments", "subscriptions", "documents"):
            db.execute(f"UPDATE {table} SET member_id=0 WHERE member_id=?", (mid,))
        cur = db.execute("DELETE FROM members WHERE id=?", (mid,))
        deleted["members"] = cur.rowcount
        db.commit()
    finally:
        db.close()
    return deleted

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
    _purge_member(member["id"])
    r = RedirectResponse("/?deleted=1", 302)
    r.delete_cookie("_session")
    return r

# ══════════════════════════════════════════════════════════
# ABONNEMENT · PAIEMENTS · DOCUMENTS
# ══════════════════════════════════════════════════════════
def _next_doc_number(db, doc_type: str) -> str:
    """Numérotation séquentielle par année et par type (REC-2026-0001)."""
    prefix = "REC" if doc_type == "receipt" else "CTR"
    year   = datetime.now().year
    like   = f"{prefix}-{year}-%"
    n = db.execute("SELECT COUNT(*) FROM documents WHERE number LIKE ?", (like,)).fetchone()[0]
    return f"{prefix}-{year}-{n+1:04d}"

def _create_document(db, doc_type: str, member: dict, payload: dict,
                     subscription_id: int = 0, payment_id: int = 0) -> str:
    number = _next_doc_number(db, doc_type)
    db.execute(
        """INSERT INTO documents(doc_type,number,member_id,subscription_id,payment_id,payload,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (doc_type, number, member["id"], subscription_id, payment_id,
         json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()))
    return number

@app.get("/mon-abonnement", response_class=HTMLResponse)
async def my_subscription(req: Request):
    member = get_member(req)
    if not member: return RedirectResponse("/login?next=/mon-abonnement", 302)
    db = get_db()
    payments = [dict(r) for r in db.execute(
        "SELECT * FROM payments WHERE member_id=? ORDER BY paid_at DESC", (member["id"],)).fetchall()]
    docs = [dict(r) for r in db.execute(
        "SELECT id,doc_type,number,created_at,accepted_at FROM documents WHERE member_id=? ORDER BY id DESC",
        (member["id"],)).fetchall()]
    subs = [dict(r) for r in db.execute(
        "SELECT * FROM subscriptions WHERE member_id=? ORDER BY id DESC LIMIT 5", (member["id"],)).fetchall()]
    db.close()
    return render(req, "abonnement.html", {"payments": payments, "docs": docs, "subs": subs})

@app.get("/documents/{number}", response_class=HTMLResponse)
async def view_document(req: Request, number: str):
    """Consultation d'un contrat ou reçu. Un membre n'accède qu'à ses propres
    documents; l'admin peut tous les consulter."""
    member = get_member(req)
    is_adm = _is_admin(req)
    if not member and not is_adm:
        return RedirectResponse(f"/login?next=/documents/{number}", 302)
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE number=?", (number,)).fetchone()
    if not doc or (not is_adm and doc["member_id"] != member["id"]):
        db.close()
        return render(req, "404.html", {}, status_code=404)
    owner = db.execute("SELECT id,nom,email,phone,company FROM members WHERE id=?", (doc["member_id"],)).fetchone()
    db.close()
    try:
        payload = json.loads(doc["payload"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return render(req, "document.html", {
        "doc": dict(doc), "payload": payload, "owner": dict(owner) if owner else {}})

@app.post("/documents/{number}/accepter")
async def accept_document(req: Request, number: str, csrf_token: str = Form("")):
    """Acceptation électronique du contrat par le membre (horodatée + IP)."""
    member = get_member(req)
    csrf_guard(req, csrf_token)
    if not member: return RedirectResponse("/login", 302)
    db = get_db()
    doc = db.execute("SELECT id,member_id,doc_type,accepted_at FROM documents WHERE number=?", (number,)).fetchone()
    if doc and doc["member_id"] == member["id"] and doc["doc_type"] == "contract" and not doc["accepted_at"]:
        db.execute("UPDATE documents SET accepted_at=?, accepted_ip=? WHERE id=?",
                   (datetime.now().isoformat(), get_ip(req), doc["id"]))
        db.commit()
    db.close()
    return RedirectResponse(f"/documents/{number}?accepted=1", 302)

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
        "scrapes":scrapes,
        "logs":State.logs[-100:],"running":State.running,
        "last_run":State.last_run,"cfg":cfg,"multi_ok":False,
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

@app.get("/admin/companies", response_class=HTMLResponse)
async def admin_companies(req: Request, q:str="", s:str="", r:str="",
                           src:str="", avec:str="", page:int=1):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db(); per = 40; page = max(1, page)
    where, params = ["1=1"], []
    if q:
        where.append("(legal_name LIKE ? OR normalized_name LIKE ? OR email LIKE ? OR phone LIKE ?)")
        params += [f"%{q}%"]*4
    if s: where.append("sector=?"); params.append(s)
    if r: where.append("region=?"); params.append(r)
    if src: where.append("source=?"); params.append(src)
    # Filtres de prospection: ne montrer que les fiches réellement contactables.
    if avec == "tel":   where.append("phone!=''")
    elif avec == "mail": where.append("email!=''")
    elif avec == "both": where.append("phone!='' AND email!=''")
    wh = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM companies WHERE {wh}", params).fetchone()[0]
    # Par défaut, les fiches les plus exploitables d'abord: une liste de
    # prospection ne sert à rien si la première page ne contient que des
    # entreprises sans aucun moyen de contact (cas des fiches issues des
    # adjudications, qui ont des marchés gagnés mais ni téléphone ni email).
    tri = {
        "contact": "(email!='') DESC, (phone!='') DESC, wins DESC, legal_name",
        "marches": "wins DESC, (phone!='') DESC, legal_name",
        "nom":     "legal_name",
        "recent":  "id DESC",
    }.get(req.query_params.get("tri", "contact"), "(email!='') DESC, (phone!='') DESC, wins DESC, legal_name")
    rows = [dict(x) for x in db.execute(
        f"SELECT * FROM companies WHERE {wh} ORDER BY {tri} LIMIT ? OFFSET ?",
        params+[per,(page-1)*per]).fetchall()]
    stats = {
        "total":    db.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "phone":    db.execute("SELECT COUNT(*) FROM companies WHERE phone!=''").fetchone()[0],
        "email":    db.execute("SELECT COUNT(*) FROM companies WHERE email!=''").fetchone()[0],
        "sectors":  db.execute("SELECT COUNT(DISTINCT sector) FROM companies WHERE sector!=''").fetchone()[0],
    }
    regions = [x[0] for x in db.execute(
        "SELECT DISTINCT region FROM companies WHERE region!='' ORDER BY region LIMIT 60").fetchall()]
    sources = [dict(x) for x in db.execute(
        "SELECT source, COUNT(*) n FROM companies WHERE source!='' GROUP BY source ORDER BY n DESC").fetchall()]
    db.close()
    from app.services.places_scraper import VILLES
    csrf_tok = get_csrf_token(req) or secrets.token_urlsafe(24)
    resp = templates.TemplateResponse("admin_companies.html", {
        "request": req, "cfg": cfg, "rows": rows, "total": total, "stats": stats,
        "page": page, "pages": max(1,(total+per-1)//per), "q": q, "sf": s, "rf": r,
        "src": src, "avec": avec, "sources": sources, "tri": req.query_params.get("tri","contact"),
        "regions": regions, "sector_groups": cfg.SECTOR_GROUPS, "csrf_token": csrf_tok,
        "villes": VILLES, "places_ready": bool(cfg.GOOGLE_PLACES_API_KEY),
        "places_running": PlacesState.running})
    if not req.cookies.get("_csrf"):
        resp.set_cookie("_csrf", csrf_tok, max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

class PlacesState:
    """État de la collecte annuaire, partagé entre la tâche de fond et l'UI."""
    running   = False
    logs      = []
    stats     = {}
    started   = ""
    finished  = ""
    moteur    = "places"

    @classmethod
    def log(cls, msg: str):
        ligne = f"{datetime.now().strftime('%H:%M:%S')} │ {msg}"
        cls.logs.append(ligne)
        if len(cls.logs) > 400:
            del cls.logs[:-400]
        logger.info(f"[places] {msg}")


async def _run_places_collect(secteurs: list, villes: list, avec_email: bool,
                               moteur: str = "places"):
    if moteur == "maps":
        from app.services.maps_scraper import collecter
    else:
        from app.services.places_scraper import collecter
    PlacesState.moteur   = moteur
    PlacesState.running  = True
    PlacesState.logs     = []
    PlacesState.stats    = {}
    PlacesState.started  = datetime.now().isoformat()
    PlacesState.finished = ""
    debut = datetime.now()
    PlacesState.log(f"Démarrage [{moteur}] — {len(secteurs)} secteur(s) × {len(villes)} ville(s)")
    try:
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(
            None, lambda: collecter(secteurs, villes, PlacesState.log, avec_email))
        PlacesState.stats = stats
        _record_run(f"google-{moteur}", "SUCCESS" if not stats.get("erreurs") else "PARTIAL",
                    stats.get("trouvees", 0), stats.get("creees", 0),
                    stats.get("erreurs", 0), started=debut)
    except Exception as e:
        PlacesState.log(f"❌ {e}")
        logger.error(f"[places] {e}", exc_info=True)
        _record_run(f"google-{moteur}", "FAILED", errors=1, started=debut, message=str(e))
    finally:
        PlacesState.running  = False
        PlacesState.finished = datetime.now().isoformat()

@app.post("/admin/companies/collect")
async def admin_companies_collect(req: Request, csrf_token: str = Form("")):
    """Lance la collecte annuaire (Google Places API) en tâche de fond."""
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    if PlacesState.running:
        return RedirectResponse("/admin/companies?collect=deja", 302)
    form     = await req.form()
    moteur   = "maps" if form.get("moteur") == "maps" else "places"
    if moteur == "places" and not cfg.GOOGLE_PLACES_API_KEY:
        return RedirectResponse("/admin/companies?collect=nokey", 302)
    from app.services.places_scraper import VILLES
    secteurs = [s for s in form.getlist("secteurs") if s in cfg.SECTEURS]
    villes   = [v for v in form.getlist("villes") if v in VILLES]
    if not secteurs:
        secteurs = list(cfg.SECTEURS.keys())
    if not villes:
        villes = VILLES[:5]
    avec_email = bool(form.get("avec_email"))
    asyncio.create_task(_run_places_collect(secteurs, villes, avec_email, moteur))
    return RedirectResponse("/admin/companies?collect=lance", 302)

@app.get("/admin/companies/collect_status")
async def admin_companies_collect_status(req: Request):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    return JSONResponse({
        "ok": True, "running": PlacesState.running, "moteur": PlacesState.moteur,
        "logs": PlacesState.logs[-60:], "stats": PlacesState.stats,
        "started": PlacesState.started, "finished": PlacesState.finished,
    })

@app.post("/admin/companies/import")
async def admin_companies_import(req: Request):
    """Importe un fichier JSON produit par collecte_maps.py sur un poste local.

    Le serveur n'embarque pas de navigateur: la collecte Google Maps tourne
    sur la machine de l'admin, et son résultat est déversé ici. Les fiches
    passent par la même déduplication que les autres sources.
    """
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    form = await req.form()
    csrf_guard(req, form.get("csrf_token", ""))
    fichier = form.get("fichier")
    if not fichier or not hasattr(fichier, "read"):
        return RedirectResponse("/admin/companies?import=nofile", 302)
    contenu = await fichier.read()
    if len(contenu) > 8 * 1024 * 1024:
        return RedirectResponse("/admin/companies?import=toobig", 302)
    try:
        fiches = json.loads(contenu.decode("utf-8"))
        if not isinstance(fiches, list):
            raise ValueError("le fichier doit contenir une liste de fiches")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        logger.warning(f"[import] fichier invalide: {e}")
        return RedirectResponse("/admin/companies?import=invalide", 302)

    from app.services.companies import upsert_company
    stats = {"lues": 0, "creees": 0, "fusionnees": 0, "rejetees": 0}
    db = get_db()
    try:
        for fiche in fiches[:20000]:
            if not isinstance(fiche, dict) or not fiche.get("legal_name"):
                continue
            stats["lues"] += 1
            _cid, action = upsert_company(db, fiche)
            if action == "created":
                stats["creees"] += 1
            elif action == "rejected":
                stats["rejetees"] += 1
            else:
                stats["fusionnees"] += 1
        db.commit()
    finally:
        db.close()
    logger.info(f"[import] {stats}")
    return RedirectResponse(
        f"/admin/companies?import=ok&creees={stats['creees']}"
        f"&fusionnees={stats['fusionnees']}&rejetees={stats['rejetees']}", 302)

@app.post("/admin/companies/seed")
async def admin_companies_seed(req: Request, csrf_token: str = Form("")):
    """Alimente la base entreprises depuis les adjudicataires déjà collectés."""
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    from app.services.companies import seed_from_tender_results
    db = get_db()
    try:
        stats = seed_from_tender_results(db)
    finally:
        db.close()
    return RedirectResponse(
        f"/admin/companies?seeded={stats['created']}&merged={stats['merged']}&rejected={stats['rejected']}", 302)

@app.get("/admin/companies/export")
async def admin_companies_export(req: Request, q:str="", s:str="", r:str="",
                                  src:str="", avec:str=""):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    db = get_db()
    where, params = ["1=1"], []
    if q:
        where.append("(legal_name LIKE ? OR normalized_name LIKE ?)"); params += [f"%{q}%"]*2
    if s: where.append("sector=?"); params.append(s)
    if r: where.append("region=?"); params.append(r)
    if src: where.append("source=?"); params.append(src)
    if avec == "tel":    where.append("phone!=''")
    elif avec == "mail": where.append("email!=''")
    elif avec == "both": where.append("phone!='' AND email!=''")
    rows = db.execute(
        f"SELECT * FROM companies WHERE {' AND '.join(where)} ORDER BY wins DESC", params).fetchall()
    db.close()
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Entreprise","Secteur","Region","Ville","Telephone","Mobile","Email","Site","ICE","RC","Marches_gagnes","Source"])
    for c in rows:
        w.writerow([c["legal_name"], get_label(c["sector"]) if c["sector"] else "", c["region"], c["city"],
                    c["phone"], c["mobile"], c["email"], c["website"], c["ice"], c["rc"], c["wins"], c["source"]])
    return Response(content=buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                     headers={"Content-Disposition": "attachment; filename=entreprises_maroc.csv"})

@app.get("/admin/sources", response_class=HTMLResponse)
async def admin_sources(req: Request):
    """Registre de conformité des sources + état des dernières exécutions."""
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    sources = [dict(r) for r in db.execute(
        "SELECT * FROM source_registry ORDER BY source_type, source_name").fetchall()]
    runs = [dict(r) for r in db.execute(
        "SELECT * FROM scraper_runs ORDER BY started_at DESC LIMIT 40").fetchall()]
    per_source = [dict(r) for r in db.execute("""
        SELECT source,
               COUNT(*) AS runs,
               SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) AS ko,
               MAX(started_at) AS last_run,
               SUM(records_saved) AS saved
        FROM scraper_runs GROUP BY source ORDER BY last_run DESC""").fetchall()]
    db.close()
    return templates.TemplateResponse("admin_sources.html", {
        "request": req, "cfg": cfg, "sources": sources, "runs": runs, "per_source": per_source})

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

@app.get("/admin/wa_digest/run")
async def admin_wa_digest_run(req: Request):
    """Envoie tout de suite les résumés WhatsApp en attente (test Sandbox)."""
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    from app.services.notifications import send_daily_wa_digests
    loop = asyncio.get_event_loop()
    n = await loop.run_in_executor(None, lambda: send_daily_wa_digests(force=True))
    return JSONResponse({"ok": True, "envoyes": n})

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

@app.post("/admin/expire")
async def admin_expire(req: Request, csrf_token: str = Form("")):
    """Passe en « expiré » les marchés dont la date limite est passée.

    Moins grave que la purge, mais cela écrit quand même: en POST comme le
    reste, pour qu'aucune écriture ne dépende d'une simple visite d'URL.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    exp, active = expire_tenders()
    State.log(f"⏳ {exp} marché(s) expiré(s), {active} actif(s)")
    return RedirectResponse(f"/admin/maintenance?expires={exp}", 302)

def _reparer_fiches_portail(limite: int = 400) -> dict:
    """Recharge les fiches du portail public collectées avant la correction.

    L'ancien extracteur cherchait un tableau HTML que la fiche n'a jamais eu:
    des milliers de lignes sont en base sans acheteur ni région. On ne
    retélécharge que les consultations encore ouvertes — les fermées ne sont
    plus affichées, les recharger ne ferait que marteler le portail.
    """
    from app.services.scraper import make_session, parse_page, BASE
    db = get_db()
    cibles = [r["id"] for r in db.execute(
        """SELECT id FROM tenders
           WHERE source='marchespublics' AND statut='actif' AND acheteur=''
           ORDER BY scraped_at DESC LIMIT ?""", (limite,)).fetchall()]
    session, corriges, echecs = make_session(), 0, 0
    for tid in cibles:
        num = tid.replace("bdc_", "")
        try:
            r = session.get(f"{BASE}/show/{num}", timeout=25)
            fiche = parse_page(r.text, num) if r.status_code == 200 else None
            if not fiche:
                echecs += 1
            else:
                db.execute("""UPDATE tenders SET acheteur=?, region=?, secteur=?,
                              type_procedure=? WHERE id=?""",
                           (fiche["acheteur"], fiche["region"], fiche["secteur"],
                            fiche["type_procedure"], tid))
                corriges += 1
                if corriges % 25 == 0:
                    db.commit()
        except Exception as e:
            echecs += 1
            logger.warning(f"[reparation {tid}] {str(e)[:80]}")
        time.sleep(0.4)
    db.commit(); db.close()
    logger.info(f"[reparation] {corriges} fiche(s) complétée(s), {echecs} échec(s)")
    return {"corriges": corriges, "echecs": echecs, "examinees": len(cibles)}


# ══════════════════════════════════════════════════════════
# PROSPECTION — appeler les entreprises collectées
# ══════════════════════════════════════════════════════════
# Heures d'appel au Maroc. Le matériau n'est pas une statistique interne
# mais l'organisation d'une journée de chantier: l'entrepreneur est passé au
# bureau après la tournée du matin, et repart avant la fin d'après-midi.
CRENEAUX_APPEL = [
    ("9h00 – 11h30", "bon", "Le meilleur créneau: sorti des chantiers, encore au bureau."),
    ("11h30 – 12h30", "moyen", "Ça passe, sauf le vendredi (prière)."),
    ("12h30 – 14h30", "mauvais", "Déjeuner. On ne dérange pas."),
    ("14h30 – 16h30", "bon", "Deuxième bon créneau."),
    ("16h30 – 17h30", "moyen", "Fin de journée: utile pour les rappels, pas pour un premier appel."),
    ("Après 17h30", "mauvais", "Trop tard."),
]

STATUTS_PROSPECTION = {
    "a_appeler":  "À appeler",
    "rappeler":   "À rappeler",
    "interesse":  "Intéressé",
    "essai":      "Essai ouvert",
    "abonne":     "Abonné",
    "refus":      "Pas intéressé",
    "injoignable": "Injoignable",
    "ne_pas_contacter": "Ne plus contacter",
}


def _marches_pour_secteur(db, secteur: str, limite: int = 3) -> list:
    """Les marchés ouverts du secteur de l'entreprise appelée.

    C'est le cœur de l'appel: on n'ouvre pas sur une offre commerciale mais
    sur des consultations réelles que l'entreprise peut encore déposer.
    """
    if not secteur:
        return []
    return [dict(r) for r in db.execute(
        """SELECT id, objet, acheteur, region, montant, date_limite, type_procedure
           FROM tenders WHERE statut='actif' AND secteur=?
           ORDER BY scraped_at DESC LIMIT ?""", (secteur, limite)).fetchall()]


@app.get("/admin/prospection", response_class=HTMLResponse)
async def admin_prospection(req: Request, statut: str = "", s: str = "",
                            ville: str = "", q: str = "", gagnants: str = "",
                            page: int = 1):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db(); per = 40; page = max(1, page)
    # Les gagnants de marchés sont les meilleurs prospects que la plateforme
    # sache produire — ils ont de l'argent et du travail devant eux — mais
    # Global Marché ne publie aucun contact: 236 des 237 n'ont pas de
    # téléphone (mesure du 01/10/2026). Les masquer faute de numéro, c'est
    # cacher la liste la plus précieuse. Ce filtre les montre tous, avec de
    # quoi chercher le numéro et le saisir.
    if gagnants:
        where = ["COALESCE(c.wins,0) > 0"]
    else:
        where = ["c.phone!='' OR c.email!=''"]
    params = []
    if q:
        where.append("(c.legal_name LIKE ? OR c.phone LIKE ? OR c.city LIKE ?)")
        params += [f"%{q}%"] * 3
    if s:     where.append("c.sector=?");        params.append(s)
    if ville: where.append("c.city=?");          params.append(ville)
    if statut:
        where.append("COALESCE(p.statut,'a_appeler')=?")
        params.append(statut)
    else:
        # Par défaut on masque les entreprises qui ont demandé à ne plus être
        # contactées: les faire réapparaître dans la liste, c'est les rappeler.
        where.append("COALESCE(p.statut,'a_appeler')!='ne_pas_contacter'")
    wh = " AND ".join(f"({w})" for w in where)

    total = db.execute(
        f"SELECT COUNT(*) FROM companies c LEFT JOIN prospection p ON p.company_id=c.id WHERE {wh}",
        params).fetchone()[0]
    rows = [dict(r) for r in db.execute(f"""
        SELECT c.*, COALESCE(p.statut,'a_appeler') AS statut, p.notes,
               p.prochain_contact, p.dernier_contact, COALESCE(p.appels,0) AS appels
        FROM companies c LEFT JOIN prospection p ON p.company_id=c.id
        WHERE {wh}
        ORDER BY (p.prochain_contact!='' AND p.prochain_contact<=date('now')) DESC,
                 (COALESCE(p.statut,'a_appeler')='a_appeler') DESC,
                 COALESCE(c.wins,0) DESC, (c.phone!='') DESC, c.legal_name
        LIMIT ? OFFSET ?""", params + [per, (page - 1) * per]).fetchall()]

    compteurs = {k: 0 for k in STATUTS_PROSPECTION}
    for st, n in db.execute("""SELECT COALESCE(p.statut,'a_appeler'), COUNT(*)
                               FROM companies c LEFT JOIN prospection p ON p.company_id=c.id
                               WHERE c.phone!='' OR c.email!='' GROUP BY 1"""):
        compteurs[st] = n
    rappels = db.execute(
        """SELECT COUNT(*) FROM prospection WHERE prochain_contact!=''
           AND prochain_contact<=date('now') AND statut NOT IN ('abonne','ne_pas_contacter')"""
    ).fetchone()[0]
    villes = [r[0] for r in db.execute(
        "SELECT DISTINCT city FROM companies WHERE city!='' ORDER BY city LIMIT 60").fetchall()]
    secteurs = [r[0] for r in db.execute(
        "SELECT DISTINCT sector FROM companies WHERE sector!='' ORDER BY sector").fetchall()]
    nb_gagnants = db.execute(
        "SELECT COUNT(*) FROM companies WHERE COALESCE(wins,0) > 0").fetchone()[0]
    nb_fiches = db.execute(
        "SELECT COUNT(*) FROM companies WHERE COALESCE(wins,0) > 0 "
        "AND COALESCE(annuaire_url,'') != ''").fetchone()[0]
    db.close()
    return templates.TemplateResponse("admin_prospection.html", {
        "request": req, "cfg": cfg, "rows": rows, "total": total, "page": page,
        "pages": max(1, (total + per - 1) // per), "statuts": STATUTS_PROSPECTION,
        "compteurs": compteurs, "rappels": rappels, "villes": villes,
        "secteurs": secteurs, "nb_gagnants": nb_gagnants, "nb_fiches": nb_fiches,
        "csrf_token": get_csrf_token(req) or secrets.token_urlsafe(24),
        "f": {"statut": statut, "s": s, "ville": ville, "q": q,
              "gagnants": gagnants},
        "get_label": get_label, "now": datetime.now()})


def _script_appel(entreprise: dict, ouverts: int, marches: list) -> list:
    """Le déroulé de l'appel, avec les chiffres de cette entreprise-là.

    Un script générique se récite et s'entend. Celui-ci ne tient que parce
    qu'il nomme un marché que l'interlocuteur peut vérifier en raccrochant:
    c'est la seule chose qui distingue cet appel d'un démarchage.

    L'ordre n'est pas décoratif. La preuve vient avant l'offre, et la
    question avant l'argumentaire: un entrepreneur qui a dit lui-même qu'il
    rate des marchés n'a plus besoin qu'on le lui explique.
    """
    # La même tournure que les messages écrits: « 1 marché public ouvert »,
    # pas « 1 marché(s) public(s) ouvert(s) ». On lit l'un à voix haute et on
    # envoie l'autre dans la minute; deux formulations trahiraient le script.
    from app.services.campagne import _accroche
    exemple = (marches[0]["objet"][:95] + "…") if marches else ""
    acheteur = marches[0].get("acheteur", "")[:50] if marches else ""
    return [
        ("Ouverture — 10 secondes",
         f"Bonjour, {cfg.FROM_NAME}. Je ne vous vends rien tout de suite : "
         f"je vous appelle parce qu'il y a en ce moment "
         f"{_accroche(entreprise, ouverts)}"),
        ("Preuve — laissez-la parler seule",
         (f"Par exemple : « {exemple} »"
          + (f", chez {acheteur}." if acheteur else ".")
          + " Vous pouvez le vérifier, c'est public."
          ) if exemple else
         "Aucun marché ouvert dans ce secteur aujourd'hui : mieux vaut "
         "rappeler cette entreprise un jour où il y en a."),
        ("La question — puis vous vous taisez",
         "Aujourd'hui, comment vous apprenez qu'un marché comme celui-là "
         "est sorti ? … Et il vous arrive d'en rater ?"),
        ("L'offre — seulement après sa réponse",
         f"C'est exactement ce qu'on fait : chaque matin, les marchés de "
         f"votre secteur et de votre région, par WhatsApp et par email. "
         f"{cfg.TRIAL_DAYS} jours gratuits, sans carte bancaire, et vous "
         f"arrêtez quand vous voulez."),
        ("Clôture — obtenez le WhatsApp, pas un « rappelez-moi »",
         "Je vous envoie le lien sur WhatsApp là, maintenant, pendant qu'on "
         "se parle — c'est quoi votre numéro ? … Je vous rappelle jeudi "
         "pour savoir si ça vous a servi."),
        ("« Envoyez-moi un email »",
         "Bien sûr. Mais l'email se perd : je vous mets aussi le lien sur "
         "WhatsApp, vous l'ouvrez en dix secondes. C'est quel numéro ?"),
        ("« C'est combien ? »",
         f"On en parle dans {cfg.TRIAL_DAYS} jours, quand vous aurez vu si "
         f"ça vous sert. Si ça ne vous rapporte rien, ça ne vaut rien."),
        ("« J'ai déjà quelqu'un qui me les cherche »",
         "Tant mieux. Gardez-le, et prenez les 7 jours en parallèle : si on "
         "sort un marché qu'il n'a pas vu, vous le saurez tout de suite."),
        ("« Ça ne m'intéresse pas »",
         "Très bien, je vous retire de la liste, vous ne serez plus appelé. "
         "— puis passez le statut à « Ne plus contacter »."),
    ]


@app.get("/admin/prospection/plan", response_class=HTMLResponse)
async def admin_plan_appel(req: Request):
    """Par où commencer aujourd'hui, et à quelle heure.

    Trois cent vingt-trois entreprises joignables ne se parcourent pas dans
    l'ordre alphabétique. Cette page classe les secteurs par la force de
    l'argument qu'on peut y tenir — nombre de marchés ouverts multiplié par
    nombre d'entreprises à joindre — et exclut ceux où il n'y a rien à citer.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    from app.services.campagne import priorites, villes_a_joindre
    return templates.TemplateResponse("admin_plan.html", {
        "request": req, "cfg": cfg, "priorites": priorites(),
        "villes": villes_a_joindre(), "creneaux": CRENEAUX_APPEL})


@app.post("/admin/prospection/apparier")
async def admin_prospection_apparier(req: Request, csrf_token: str = Form("")):
    """Rattache aux gagnants leur fiche dans un annuaire professionnel.

    Global Marché ne publie pas les contacts des attributaires. Un annuaire
    marocain d'entreprises en a une partie: on y reconnaît l'entreprise par
    son nom canonique exact et on pose le lien de sa fiche publique. La page
    s'ouvre ensuite dans le navigateur du fondateur — la plateforme ne la lit
    pas, le site refusant les clients automatiques, ce qui est son droit.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    try:
        from app.services.annuaire_externe import apparier
        stats = apparier(logger.info)
        logger.info(f"[annuaire externe] {stats['apparies']} fiche(s) rattachée(s)")
    except Exception as e:
        # Le site peut être indisponible ou avoir changé ses sitemaps: la page
        # d'appel doit rester utilisable, le compte affiché dira simplement
        # qu'aucune fiche n'a été rattachée.
        logger.error(f"[annuaire externe] {e}", exc_info=True)
    return RedirectResponse("/admin/prospection?gagnants=1", 302)


@app.get("/admin/prospection/{cid}", response_class=HTMLResponse)
async def admin_prospection_fiche(req: Request, cid: int):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    c = db.execute("""SELECT c.*, COALESCE(p.statut,'a_appeler') AS statut, p.notes,
                             p.prochain_contact, p.dernier_contact, COALESCE(p.appels,0) AS appels
                      FROM companies c LEFT JOIN prospection p ON p.company_id=c.id
                      WHERE c.id=?""", (cid,)).fetchone()
    if not c:
        db.close()
        return render(req, "404.html", {}, status_code=404)
    entreprise = dict(c)
    marches = _marches_pour_secteur(db, entreprise.get("sector", ""), 3)
    ouverts = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND secteur=?",
                         (entreprise.get("sector", ""),)).fetchone()[0]
    inv = db.execute("SELECT * FROM invitations WHERE company_id=? ORDER BY created_at DESC",
                     (cid,)).fetchone()
    db.close()
    invitation = dict(inv) if inv else None
    lien = f"{cfg.SITE_URL}/invitation/{invitation['token']}" if invitation else ""
    # Les messages prêts à partir portent les marchés du secteur, pas une
    # description de la plateforme: c'est ce qui se vérifie et donc ce qui
    # fait ouvrir le lien.
    from app.services.campagne import message_email, message_whatsapp
    msg_wa = message_whatsapp(entreprise, lien)
    msg_objet, msg_html = message_email(entreprise, lien)
    # Message prêt à envoyer: il ouvre sur des marchés réels, pas sur une
    # offre commerciale — c'est ce qui fait ouvrir le lien.
    message = ""
    if lien:
        exemple = marches[0]["objet"][:90] if marches else ""
        message = (
            f"Bonjour, ici {cfg.FROM_NAME}. Nous suivons les marchés publics au Maroc.\n\n"
            f"Il y a actuellement {ouverts} marché(s) ouvert(s) dans votre domaine"
            f"{' à ' + entreprise['city'] if entreprise.get('city') else ''}"
            + (f", dont : {exemple}." if exemple else ".") +
            f"\n\nVoici votre lien personnel pour les consulter gratuitement pendant "
            f"{cfg.TRIAL_DAYS} jours et recevoir les demandes de sous-traitance de votre "
            f"secteur :\n{lien}\n\nSi vous ne souhaitez plus être contacté, dites-le nous "
            f"et nous retirons vos coordonnées.")
    return templates.TemplateResponse("admin_prospection_fiche.html", {
        "request": req, "cfg": cfg, "c": entreprise, "marches": marches,
        "script": _script_appel(entreprise, ouverts, marches),
        "msg_wa": msg_wa, "msg_objet": msg_objet, "msg_html": msg_html,
        "ouverts": ouverts, "statuts": STATUTS_PROSPECTION, "get_label": get_label,
        "invitation": invitation, "lien_invitation": lien, "message_invitation": message,
        "csrf_token": get_csrf_token(req) or secrets.token_urlsafe(24)})


@app.post("/admin/prospection/{cid}")
async def admin_prospection_maj(req: Request, cid: int, statut: str = Form("a_appeler"),
                                notes: str = Form(""), prochain: str = Form(""),
                                appel: str = Form(""), phone: str = Form(""),
                                email: str = Form(""), csrf_token: str = Form("")):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    if statut not in STATUTS_PROSPECTION:
        statut = "a_appeler"
    maintenant = datetime.now().isoformat()
    db = get_db()
    # Les gagnants de marchés arrivent sans contact: Global Marché n'en publie
    # pas. Le numéro trouvé à la main doit pouvoir être enregistré, sinon il
    # est perdu dès l'onglet fermé et l'entreprise reste invisible dans la
    # file d'appel, qui ne montre par défaut que ce qui est joignable.
    from app.services.companies import normalize_email, normalize_phone
    tel, courriel = normalize_phone(phone), normalize_email(email)
    if tel or courriel:
        champs, valeurs = [], []
        if tel:
            champs.append("phone=?"); valeurs.append(tel)
        if courriel:
            champs.append("email=?"); valeurs.append(courriel)
        champs.append("updated_at=?"); valeurs.append(maintenant)
        db.execute(f"UPDATE companies SET {', '.join(champs)} WHERE id=?",
                   valeurs + [cid])
    existe = db.execute("SELECT appels FROM prospection WHERE company_id=?", (cid,)).fetchone()
    appels = (existe["appels"] if existe else 0) + (1 if appel else 0)
    dernier = maintenant[:10] if appel else (
        db.execute("SELECT dernier_contact FROM prospection WHERE company_id=?",
                   (cid,)).fetchone() or {"dernier_contact": ""})["dernier_contact"]
    db.execute("""INSERT INTO prospection(company_id,statut,notes,prochain_contact,
                     dernier_contact,appels,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?)
                  ON CONFLICT(company_id) DO UPDATE SET
                     statut=excluded.statut, notes=excluded.notes,
                     prochain_contact=excluded.prochain_contact,
                     dernier_contact=excluded.dernier_contact,
                     appels=excluded.appels, updated_at=excluded.updated_at""",
               (cid, statut, notes[:2000], prochain[:10], dernier or "", appels,
                maintenant, maintenant))
    db.commit(); db.close()
    logger.info(f"[prospection] entreprise {cid} → {statut}")
    return RedirectResponse(f"/admin/prospection/{cid}?ok=1", 302)


@app.post("/admin/prospection/{cid}/email")
async def admin_prospection_email(req: Request, cid: int, csrf_token: str = Form("")):
    """Envoie à une entreprise les marchés ouverts de son secteur.

    Un envoi à la fois, depuis sa fiche, et jamais en lot: c'est ce qui
    distingue une prise de contact d'un publipostage, et c'est aussi ce que
    supporte le quota d'envoi. L'appel téléphonique reste premier — l'email
    confirme, il ne remplace pas.

    Sans marché ouvert dans le secteur, on n'envoie rien: un message qui ne
    montre rien ne vaut pas l'adresse qu'il brûle.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    from app.services.campagne import message_email
    from app.services.notifications import email_send

    db = get_db()
    ligne = db.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not ligne:
        db.close()
        return RedirectResponse("/admin/prospection", 302)
    entreprise = dict(ligne)
    inv = db.execute("SELECT token FROM invitations WHERE company_id=? "
                     "ORDER BY created_at DESC", (cid,)).fetchone()
    db.close()
    if not entreprise.get("email"):
        return RedirectResponse(f"/admin/prospection/{cid}?envoi=sans_adresse", 302)

    lien = f"{cfg.SITE_URL}/invitation/{inv['token']}" if inv else ""
    objet, corps = message_email(entreprise, lien)
    if not corps:
        return RedirectResponse(f"/admin/prospection/{cid}?envoi=sans_marche", 302)
    envoye = email_send(entreprise["email"], objet, corps)
    if envoye:
        maintenant = datetime.now().isoformat()
        db = get_db()
        db.execute("""INSERT INTO prospection(company_id,statut,canal,notes,dernier_contact,
                         prochain_contact,appels,created_at,updated_at)
                      VALUES(?,'a_appeler','email','',?,'',0,?,?)
                      ON CONFLICT(company_id) DO UPDATE SET
                         canal='email', dernier_contact=excluded.dernier_contact,
                         updated_at=excluded.updated_at""",
                   (cid, maintenant[:10], maintenant, maintenant))
        db.commit(); db.close()
        logger.info(f"[campagne] email envoyé à {entreprise['email']}")
    return RedirectResponse(
        f"/admin/prospection/{cid}?envoi={'ok' if envoye else 'echec'}", 302)


@app.post("/admin/prospection/{cid}/invitation")
async def admin_invitation(req: Request, cid: int, canal: str = Form("whatsapp"),
                           csrf_token: str = Form("")):
    """Crée le lien d'invitation personnel d'une entreprise.

    Un lien par entreprise: il pré-remplit son profil de sous-traitance et
    dit, campagne après campagne, qui a ouvert et qui s'est inscrit.
    """
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    db = get_db()
    entreprise = db.execute("SELECT id FROM companies WHERE id=?", (cid,)).fetchone()
    if not entreprise:
        db.close()
        return HTMLResponse("Entreprise introuvable", 404)
    ligne = db.execute("SELECT token FROM invitations WHERE company_id=? ORDER BY created_at DESC",
                       (cid,)).fetchone()
    if ligne:
        token = ligne["token"]
        db.execute("UPDATE invitations SET sent_at=?, canal=? WHERE token=?",
                   (datetime.now().isoformat(), canal[:20], token))
    else:
        token = secrets.token_urlsafe(9)
        db.execute("""INSERT INTO invitations(token,company_id,canal,created_at,sent_at)
                      VALUES(?,?,?,?,?)""",
                   (token, cid, canal[:20], datetime.now().isoformat(),
                    datetime.now().isoformat()))
    db.commit(); db.close()
    return RedirectResponse(f"/admin/prospection/{cid}?invite={token}", 302)


def _invitation_contexte(token: str):
    """Charge l'entreprise derrière un jeton d'invitation."""
    db = get_db()
    ligne = db.execute(
        """SELECT i.*, c.legal_name, c.sector, c.city, c.phone, c.email AS company_email,
                  c.subsector
           FROM invitations i JOIN companies c ON c.id=i.company_id
           WHERE i.token=?""", (token,)).fetchone()
    db.close()
    return dict(ligne) if ligne else None


@app.get("/invitation/{token}", response_class=HTMLResponse)
async def invitation_get(req: Request, token: str):
    """Page d'accueil d'une entreprise invitée — sans compte, sans mot de passe."""
    inv = _invitation_contexte(token)
    if not inv:
        return render(req, "404.html", {}, status_code=404)
    if not inv["opened_at"]:
        db = get_db()
        db.execute("UPDATE invitations SET opened_at=? WHERE token=?",
                   (datetime.now().isoformat(), token))
        db.commit(); db.close()
    db = get_db()
    ouverts = db.execute(
        "SELECT COUNT(*) FROM tenders WHERE statut='actif' AND secteur=?",
        (inv.get("sector") or "",)).fetchone()[0]
    exemples = [dict(r) for r in db.execute(
        """SELECT objet, montant, date_limite, region FROM tenders
           WHERE statut='actif' AND secteur=? ORDER BY scraped_at DESC LIMIT 3""",
        (inv.get("sector") or "",)).fetchall()]
    db.close()
    return render(req, "invitation.html", {
        "inv": inv, "ouverts": ouverts, "exemples": exemples,
        "deja": bool(inv["member_id"])})


@app.post("/invitation/{token}")
async def invitation_post(req: Request, token: str, email: str = Form(""),
                          pw: str = Form(""), csrf_token: str = Form("")):
    """Inscription en deux champs: le reste vient de la fiche entreprise."""
    lang = get_lang(req)
    csrf_guard(req, csrf_token)
    inv = _invitation_contexte(token)
    if not inv:
        return render(req, "404.html", {}, status_code=404)
    if not check_rate_limit(f"invit_{get_ip(req)}", 8, 600):
        return render(req, "invitation.html",
                      {"inv": inv, "err": tr_("err_too_many_generic", lang),
                       "ouverts": 0, "exemples": []})
    erreur = None
    if not email or not pw:
        erreur = tr_("err_email_pw_required", lang)
    elif not validate_email(email):
        erreur = tr_("err_email_invalid", lang)
    else:
        ok, msg = validate_password(pw, lang)
        if not ok:
            erreur = msg
    db = get_db()
    if not erreur and db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
        erreur = tr_("err_email_taken", lang)
    if erreur:
        db.close()
        return render(req, "invitation.html",
                      {"inv": inv, "err": erreur, "ouverts": 0, "exemples": []})

    maintenant = datetime.now()
    session_tok = make_session_token()
    email_token = secrets.token_urlsafe(32)
    secteurs = json.dumps([inv["sector"]] if inv.get("sector") else [])
    cur = db.execute(
        """INSERT INTO members(nom,email,phone,company,pw_hash,secteurs,regions,plan,
              created_at,trial_start,trial_ends,subscription_status,session_token,
              referral_code,referred_by,email_verified,email_token,email_token_expires)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (inv.get("legal_name", "")[:120], email, inv.get("phone", ""),
         inv.get("legal_name", "")[:200], hash_pw(pw), secteurs,
         json.dumps([inv["city"]] if inv.get("city") else []), "free",
         maintenant.isoformat(), maintenant.strftime("%Y-%m-%d"),
         (maintenant + timedelta(days=cfg.TRIAL_DAYS)).strftime("%Y-%m-%d"),
         "TRIAL", session_tok,
         secrets.token_urlsafe(5).upper().replace("_", "A").replace("-", "B")[:7], 0,
         0, email_token, (maintenant + timedelta(days=7)).isoformat()))
    mid = cur.lastrowid
    db.execute("""INSERT INTO subscriptions(member_id,plan_id,price,currency,status,
                     trial_start,trial_end,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
               (mid, "trial", 0, "MAD", "TRIAL", maintenant.strftime("%Y-%m-%d"),
                (maintenant + timedelta(days=cfg.TRIAL_DAYS)).strftime("%Y-%m-%d"),
                maintenant.isoformat(), maintenant.isoformat()))
    # Le profil de sous-traitance démarre déjà rempli: métier, ville et
    # raison sociale viennent de la fiche collectée.
    db.execute("""INSERT OR IGNORE INTO subcontract_profiles(member_id,raison_sociale,
                     metiers,zones,disponible,created_at,updated_at)
                  VALUES(?,?,?,?,1,?,?)""",
               (mid, inv.get("legal_name", "")[:200], secteurs,
                json.dumps([inv["city"]] if inv.get("city") else []),
                maintenant.isoformat(), maintenant.isoformat()))
    db.execute("UPDATE invitations SET member_id=? WHERE token=?", (mid, token))
    # L'entreprise invitée devient un prospect « essai ouvert » dans le suivi.
    db.execute("""INSERT INTO prospection(company_id,statut,created_at,updated_at)
                  VALUES(?,'essai',?,?)
                  ON CONFLICT(company_id) DO UPDATE SET statut='essai', updated_at=excluded.updated_at""",
               (inv["company_id"], maintenant.isoformat(), maintenant.isoformat()))
    db.commit(); db.close()

    envoyer_lien_verification(email, email_token, lang)
    logger.info(f"[invitation] {inv.get('legal_name','')} → compte {mid} créé")
    resp = RedirectResponse("/verifier-email?envoye=1", 302)
    resp.set_cookie("_session", session_tok, max_age=86400 * 30, httponly=True,
                    samesite="lax", secure=COOKIE_SECURE)
    return resp


@app.get("/admin/nettoyer-doublons")
async def admin_nettoyer_doublons(req: Request, appliquer: int = 0):
    """Clôture les doublons antérieurs au filtre d'enregistrement.

    Le filtre pose une empreinte sur les nouveaux marchés, mais 56 groupes
    existaient déjà — jusqu'à 17 copies d'une même consultation venue de la
    même source. On garde l'exemplaire le plus complet (montant, acheteur,
    région renseignés) et le plus récent; les autres passent en « expire »
    plutôt que d'être détruits, pour rester traçables.
    """
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    db = get_db()
    groupes, clos = 0, 0
    try:
        lignes = db.execute(
            """SELECT id, objet, date_limite, montant, acheteur, region, scraped_at
               FROM tenders WHERE statut='actif'""").fetchall()
        paquets = {}
        for r in lignes:
            paquets.setdefault((_empreinte(r["objet"]), (r["date_limite"] or "").strip()),
                               []).append(dict(r))
        for cle, lot in paquets.items():
            if not cle[0] or len(lot) < 2:
                continue
            groupes += 1
            # Le meilleur exemplaire d'abord: le plus renseigné, et à égalité
            # le plus récemment collecté.
            lot.sort(key=lambda t: (
                sum(1 for c in ("montant", "acheteur", "region") if (t.get(c) or "").strip()),
                t.get("scraped_at") or ""), reverse=True)
            garde = lot[0]
            for t in lot:
                if t["id"] == garde["id"]:
                    continue
                if appliquer:
                    db.execute("UPDATE tenders SET statut='expire' WHERE id=?", (t["id"],))
                clos += 1
        if appliquer:
            db.commit()
    finally:
        db.close()
    logger.info(f"[doublons] {groupes} groupe(s), {clos} exemplaire(s) "
                f"{'clôturés' if appliquer else 'à clôturer'}")
    return JSONResponse({"ok": True, "groupes": groupes, "exemplaires": clos,
                         "applique": bool(appliquer)})


@app.get("/admin/import-archive")
async def admin_import_archive(req: Request, pages: int = 40):
    """Rattrape l'archive des appels d'offres encore ouverts.

    La veille courante ne lit que les premières pages à chaque cycle: elle
    suffit pour le flux quotidien, pas pour repartir de zéro. Cette route
    remonte l'ensemble des consultations ouvertes, une seule fois.
    """
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    from app.services.ao_scraper import run as ao_run
    db = get_db()
    connus = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
    db.close()
    loop = asyncio.get_event_loop()
    marches = await loop.run_in_executor(
        None, lambda: ao_run(connus, logger.info, pages=pages))
    enregistres = _save_tenders(marches, [])
    logger.info(f"[import-archive] {enregistres} marché(s) importé(s) sur {len(marches)} trouvés")
    return JSONResponse({"ok": True, "trouves": len(marches), "enregistres": enregistres})


@app.get("/admin/reparer-fiches")
async def admin_reparer_fiches(req: Request, limite: int = 400):
    """Complète les fiches du portail et corrige leur type de procédure."""
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    db = get_db()
    reclasses = db.execute(
        """UPDATE tenders SET type_procedure='bon_commande'
           WHERE source='marchespublics' AND type_procedure!='bon_commande'""").rowcount
    db.commit(); db.close()
    loop = asyncio.get_event_loop()
    resultat = await loop.run_in_executor(None, lambda: _reparer_fiches_portail(limite))
    return JSONResponse({"ok": True, "reclasses": reclasses, **resultat})


@app.post("/admin/member/{mid}/plan")
async def set_plan(req: Request, mid:int, plan:str=Form(""), csrf_token:str=Form("")):
    if not _is_admin(req): return JSONResponse({"ok":False},401)
    csrf_guard(req, csrf_token)
    if plan not in cfg.PLANS: return JSONResponse({"ok":False,"msg":"Plan invalide"})
    months = cfg.PLANS[plan].get("months", 0)
    now    = datetime.now()
    db = get_db()
    if months:
        # L'échéance repart de la date de fin en cours si l'abonnement est
        # encore valide (renouvellement), sinon d'aujourd'hui.
        cur = db.execute("SELECT subscription_end FROM members WHERE id=?", (mid,)).fetchone()
        base = now.date()
        if cur and cur["subscription_end"]:
            try:
                prev = datetime.strptime(cur["subscription_end"][:10], "%Y-%m-%d").date()
                if prev > base: base = prev
            except ValueError:
                pass
        end = (base + timedelta(days=int(months * 30.44))).strftime("%Y-%m-%d")
        db.execute(
            "UPDATE members SET plan=?, subscription_status='ACTIVE', subscription_end=? WHERE id=?",
            (plan, end, mid))
        db.execute(
            """INSERT INTO subscriptions(member_id,plan_id,price,currency,status,start_date,end_date,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (mid, plan, cfg.PLANS[plan].get("price", 0), "MAD", "ACTIVE",
             now.strftime("%Y-%m-%d"), end, now.isoformat(), now.isoformat()))
    else:
        db.execute(
            "UPDATE members SET plan=?, subscription_status='EXPIRED', subscription_end='' WHERE id=?",
            (plan, mid))
    db.commit(); db.close()
    return RedirectResponse("/admin",302)

@app.get("/admin/payments", response_class=HTMLResponse)
async def admin_payments(req: Request):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    payments = [dict(r) for r in db.execute("""
        SELECT p.*, m.nom AS member_nom, m.email AS member_email,
               (SELECT number FROM documents d WHERE d.payment_id=p.id AND d.doc_type='receipt' LIMIT 1) AS receipt
        FROM payments p LEFT JOIN members m ON m.id=p.member_id
        ORDER BY p.paid_at DESC LIMIT 200""").fetchall()]
    members = [dict(r) for r in db.execute(
        "SELECT id,nom,email,plan,subscription_end FROM members WHERE actif=1 ORDER BY created_at DESC").fetchall()]
    total = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='PAID'").fetchone()[0]
    this_month = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='PAID' AND paid_at>=date('now','start of month')"
    ).fetchone()[0]
    db.close()
    csrf_tok = get_csrf_token(req) or secrets.token_urlsafe(24)
    resp = templates.TemplateResponse("admin_payments.html", {
        "request": req, "cfg": cfg, "payments": payments, "members": members,
        "total": total, "this_month": this_month, "csrf_token": csrf_tok})
    if not req.cookies.get("_csrf"):
        resp.set_cookie("_csrf", csrf_tok, max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

@app.post("/admin/payments/record")
async def admin_record_payment(req: Request, member_id:int=Form(...), plan:str=Form("monthly"),
                                amount:float=Form(0), method:str=Form("Virement"),
                                reference:str=Form(""), note:str=Form(""), csrf_token:str=Form("")):
    """Enregistre un paiement encaissé hors plateforme, active/prolonge
    l'abonnement et génère automatiquement le reçu et le contrat."""
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    if plan not in cfg.PLANS or plan == "free":
        return RedirectResponse("/admin/payments?err=plan", 302)
    now    = datetime.now()
    months = cfg.PLANS[plan].get("months", 1) or 1
    price  = float(amount) if amount else float(cfg.PLANS[plan].get("price", 0))
    db = get_db()
    member = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        db.close()
        return RedirectResponse("/admin/payments?err=member", 302)
    member = dict(member)
    # Renouvellement: on prolonge depuis l'échéance en cours si elle est future
    base = now.date()
    if member.get("subscription_end"):
        try:
            prev = datetime.strptime(member["subscription_end"][:10], "%Y-%m-%d").date()
            if prev > base: base = prev
        except ValueError:
            pass
    period_start = base.strftime("%Y-%m-%d")
    period_end   = (base + timedelta(days=int(months * 30.44))).strftime("%Y-%m-%d")

    cur = db.execute(
        """INSERT INTO payments(member_id,amount,currency,method,reference,status,
           period_start,period_end,paid_at,recorded_by,note,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (member_id, price, "MAD", method.strip()[:40], reference.strip()[:80], "PAID",
         period_start, period_end, now.strftime("%Y-%m-%d"), "admin", note.strip()[:300], now.isoformat()))
    payment_id = cur.lastrowid
    cur2 = db.execute(
        """INSERT INTO subscriptions(member_id,plan_id,price,currency,status,start_date,end_date,
           payment_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (member_id, plan, price, "MAD", "ACTIVE", period_start, period_end,
         payment_id, now.isoformat(), now.isoformat()))
    sub_id = cur2.lastrowid
    db.execute("UPDATE payments SET subscription_id=? WHERE id=?", (sub_id, payment_id))
    db.execute(
        "UPDATE members SET plan=?, subscription_status='ACTIVE', subscription_end=? WHERE id=?",
        (plan, period_end, member_id))

    common = {
        "plan_id": plan, "plan_name": cfg.PLANS[plan].get("name", plan),
        "price": price, "currency": "MAD",
        "period_start": period_start, "period_end": period_end,
        "method": method.strip()[:40], "reference": reference.strip()[:80],
        "paid_at": now.strftime("%d/%m/%Y"),
        "customer": {"nom": member.get("nom",""), "company": member.get("company",""),
                      "email": member.get("email",""), "phone": member.get("phone","")},
        "issuer": {"name": cfg.COMPANY_NAME, "form": cfg.COMPANY_FORM,
                    "ice": cfg.COMPANY_ICE, "address": cfg.COMPANY_ADDRESS,
                    "email": cfg.CONTACT_EMAIL},
    }
    receipt_no  = _create_document(db, "receipt", member, common, sub_id, payment_id)
    contract_no = _create_document(db, "contract", member, common, sub_id, payment_id)
    db.commit(); db.close()
    logger.info(f"[payment] {price} MAD · membre {member_id} · {receipt_no}")
    return RedirectResponse(f"/admin/payments?ok={receipt_no}", 302)

@app.post("/admin/member/{mid}/delete")
async def admin_delete_member(req: Request, mid: int, confirm: str = Form(""),
                               csrf_token: str = Form("")):
    """Suppression administrative d'un compte.

    L'email du compte doit être ressaisi pour confirmer: sur une liste de
    membres, un clic mal placé effacerait sinon le mauvais compte de façon
    irréversible.
    """
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    csrf_guard(req, csrf_token)
    db = get_db()
    row = db.execute("SELECT id,email FROM members WHERE id=?", (mid,)).fetchone()
    db.close()
    if not row:
        return RedirectResponse("/admin/members?err=introuvable", 302)
    if confirm.strip().lower() != (row["email"] or "").strip().lower():
        return RedirectResponse(f"/admin/members?err=confirmation&mid={mid}", 302)
    _purge_member(mid)
    logger.info(f"[admin] compte supprimé: {row['email']} (id={mid})")
    return RedirectResponse(f"/admin/members?deleted={row['email']}", 302)

@app.get("/admin/members", response_class=HTMLResponse)
async def admin_members(req: Request, q: str = ""):
    """Gestion complète des comptes membres (plan, activation, suppression)."""
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    db = get_db()
    where, params = ["1=1"], []
    if q:
        where.append("(email LIKE ? OR nom LIKE ? OR company LIKE ?)")
        params += [f"%{q}%"] * 3
    rows = [dict(r) for r in db.execute(f"""
        SELECT m.*,
               (SELECT COUNT(*) FROM payments p WHERE p.member_id=m.id) AS n_payments,
               (SELECT COALESCE(SUM(p.amount),0) FROM payments p WHERE p.member_id=m.id) AS total_paid
        FROM members m WHERE {' AND '.join(where)}
        ORDER BY m.created_at DESC LIMIT 300""", params).fetchall()]
    db.close()
    csrf_tok = get_csrf_token(req) or secrets.token_urlsafe(24)
    resp = templates.TemplateResponse("admin_members.html", {
        "request": req, "cfg": cfg, "members": rows, "q": q, "csrf_token": csrf_tok})
    if not req.cookies.get("_csrf"):
        resp.set_cookie("_csrf", csrf_tok, max_age=86400*30, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return resp

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

# ─── Annuaires professionnels ────────────────────────────────────────────

class AnnuairesState:
    """État du rapprochement avec les annuaires, partagé avec la page.

    Reconnaître nos entreprises demande de faire couler 267 000 adresses chez
    Télécontact et deux millions chez Charika: aucune requête HTTP ne tient
    cette durée. La tâche part en fond, la page suit son journal.
    """
    running  = False
    logs     = []
    source   = ""
    etape    = ""
    started  = ""
    finished = ""

    @classmethod
    def log(cls, msg: str):
        cls.logs.append(f"{datetime.now().strftime('%H:%M:%S')} │ {msg}")
        if len(cls.logs) > 400:
            del cls.logs[:-400]
        logger.info(f"[annuaires] {msg}")


async def _run_annuaires(source: str, etape: str):
    from app.services import annuaires
    debut = datetime.now()
    AnnuairesState.running = True
    AnnuairesState.source, AnnuairesState.etape = source, etape
    AnnuairesState.started = debut.isoformat()
    AnnuairesState.logs = []
    AnnuairesState.log(f"→ {etape} · {annuaires.ANNUAIRES[source].libelle}")
    try:
        loop = asyncio.get_event_loop()
        fonction = annuaires.apparier if etape == "apparier" else annuaires.enrichir
        stats = await loop.run_in_executor(
            None, lambda: fonction(source, AnnuairesState.log))
        _record_run(f"annuaire-{source}-{etape}", "SUCCESS",
                    found=stats.get("apparies", stats.get("ouvertes", 0)),
                    saved=stats.get("apparies", stats.get("telephones", 0)), started=debut)
    except Exception as e:
        AnnuairesState.log(f"❌ {e}")
        logger.error(f"[annuaires] {e}", exc_info=True)
        _record_run(f"annuaire-{source}-{etape}", "FAILED", errors=1,
                    started=debut, message=str(e))
    finally:
        AnnuairesState.running = False
        AnnuairesState.finished = datetime.now().isoformat()


@app.get("/admin/annuaires", response_class=HTMLResponse)
async def admin_annuaires(req: Request):
    """Ce que les annuaires publics rendent des entreprises qu'on ne peut pas joindre."""
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    from app.services.annuaires import etat, dernieres_trouvailles
    return templates.TemplateResponse("admin_annuaires.html", {
        "request": req, "cfg": cfg, "e": etat(),
        "trouvailles": dernieres_trouvailles(40),
        "etat_tache": {"running": AnnuairesState.running, "logs": AnnuairesState.logs[-80:]},
        "csrf_token": get_csrf_token(req) or secrets.token_urlsafe(24)})


@app.post("/admin/annuaires/lancer")
async def admin_annuaires_lancer(req: Request, csrf_token: str = Form(""),
                                 source: str = Form(""), etape: str = Form("")):
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    from app.services.annuaires import ANNUAIRES
    if source not in ANNUAIRES or etape not in ("apparier", "enrichir"):
        return RedirectResponse("/admin/annuaires?err=inconnu", 302)
    if AnnuairesState.running:
        return RedirectResponse("/admin/annuaires?err=deja", 302)
    asyncio.create_task(_run_annuaires(source, etape))
    return RedirectResponse("/admin/annuaires", 302)


@app.get("/admin/annuaires/etat")
async def admin_annuaires_etat(req: Request):
    if not _is_admin(req): return JSONResponse({"ok": False}, 401)
    return JSONResponse({"ok": True, "running": AnnuairesState.running,
                         "source": AnnuairesState.source, "etape": AnnuairesState.etape,
                         "logs": AnnuairesState.logs[-80:],
                         "started": AnnuairesState.started,
                         "finished": AnnuairesState.finished})


@app.get("/admin/maintenance", response_class=HTMLResponse)
async def admin_maintenance(req: Request):
    """Les actions qui écrivent dans la base, rassemblées et à l'écart.

    Elles vivaient au bas du tableau de bord, sous les indicateurs: on les
    croisait en consultant, ce qui n'est pas le bon moment pour voir un
    bouton « Vider la base ». Elles ont désormais leur page, atteignable
    depuis le rail — mais le rail ne porte que le lien, jamais le bouton.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    return templates.TemplateResponse("admin_maintenance.html", {
        "request": req, "cfg": cfg,
        "csrf_token": get_csrf_token(req) or secrets.token_urlsafe(24)})


# Mot à recopier pour vider la base: on ne détruit pas des milliers de
# marchés sur un clic, fût-il confirmé par une boîte de dialogue.
MOT_DE_PURGE = "VIDER"


@app.post("/admin/clear")
async def admin_clear(req: Request, confirmation: str = Form(""),
                      csrf_token: str = Form("")):
    """Supprime tous les marchés. Jamais en GET.

    C'était un lien dans la barre de navigation, entre « Membres » et
    « Paiements »: `GET /admin/clear?confirm=yes`, gardé par un simple
    `onclick="return confirm(...)"`. Ce garde-fou ne protège que le clic,
    pas l'adresse: un préchargement du navigateur, une entrée d'historique
    rejouée, une complétion dans la barre d'adresse, et des milliers de
    marchés disparaissaient sans qu'une ligne de formulaire ait été remplie.
    Un GET ne doit jamais détruire, et un jeton CSRF ne peut rien pour lui.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    if confirmation.strip() != MOT_DE_PURGE:
        return RedirectResponse("/admin/maintenance?purge=mot", 302)
    db = get_db()
    n  = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    db.execute("DELETE FROM tenders")
    db.execute("DELETE FROM notif_log")
    db.commit(); db.close()
    State.log(f"🗑 DB vidée ({n} marchés)")
    logger.warning(f"[admin] base vidée: {n} marchés supprimés")
    return RedirectResponse(f"/admin/maintenance?purge={n}", 302)

@app.post("/admin/apercu-alerte")
async def admin_apercu_alerte(req: Request, email: str = Form(""),
                              tender_id: str = Form(""), csrf_token: str = Form("")):
    """Envoie à une adresse l'alerte telle qu'un membre la reçoit.

    En POST: un GET qui envoie un email part sur un simple préchargement du
    navigateur ou une entrée d'historique rejouée — et chaque envoi compte
    sur le quota.
    """
    if not _is_admin(req): return RedirectResponse("/admin/login", 302)
    csrf_guard(req, csrf_token)
    membre = get_member(req)
    destinataire = (email or "").strip() or (membre["email"] if membre else "")
    ok, marche = envoyer_apercu(destinataire, tender_id.strip())
    if not marche:
        etat = "sans_marche" if destinataire else "sans_adresse"
    else:
        etat = "ok" if ok else "echec"
        logger.info(f"[aperçu] {destinataire} ← {marche['id']}: "
                    f"{'envoyé' if ok else 'échec'}")
    return RedirectResponse(f"/admin?apercu={etat}", 302)


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
    # Sans cette ligne, la restriction des pages ne serait qu'un habillage:
    # l'API rendrait à qui la demande les marchés de tous les secteurs.
    siens = restreindre_aux_secteurs(m0, where, params)
    if siens and secteur and secteur not in siens:
        db.close()
        return JSONResponse({"ok": False,
                             "msg": "Secteur hors de votre profil"}, 403)
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
    siens = mes_secteurs(m0)
    garde = db.execute("SELECT 1 FROM favorites WHERE member_id=? AND tender_id=?",
                       (m0["id"], tid)).fetchone() if t else None
    db.close()
    if not t: return JSONResponse({"ok":False,"msg":"Introuvable"},404)
    # Même règle que la fiche: hors secteur, le marché n'existe pas pour ce
    # membre — sauf s'il l'a lui-même mis en favori.
    if siens and (t["secteur"] or "") not in siens and not garde:
        return JSONResponse({"ok":False,"msg":"Introuvable"},404)
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
    # L'inventaire ne liste que les sources réellement collectées: annoncer
    # une source « désactivée » depuis des mois n'informe personne.
    sources = [
        {"name": "marchespublics.gov.ma — bons de commande", "type": "public", "status": "active"},
        {"name": "marchespublics.gov.ma — appels d'offres",  "type": "public", "status": "active"},
        {"name": "Plateforme privée",                        "type": "private", "status": "active"},
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

def _slug(texte: str) -> str:
    """« Études TIC & développement » → « etudes-tic-developpement »."""
    base = unicodedata.normalize("NFD", (texte or "").lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return re.sub(r"-{2,}", "-", base)[:60]


def _secteurs_publics() -> list:
    """Secteurs exposés au référencement, du plus fourni au moins fourni."""
    db = get_db()
    try:
        compte = {r[0]: r[1] for r in db.execute(
            "SELECT secteur, COUNT(*) FROM tenders WHERE statut='actif' GROUP BY 1").fetchall()}
    finally:
        db.close()
    pages = [{"code": code, "label": label, "slug": _slug(label), "n": compte.get(code, 0)}
             for code, label in cfg.SECTEURS.items()]
    return sorted(pages, key=lambda p: -p["n"])


@app.get("/marches-publics", response_class=HTMLResponse)
async def marches_index(req: Request):
    """Annuaire public des secteurs — porte d'entrée depuis les moteurs.

    Le site n'exposait que quatre URLs: impossible de le trouver en cherchant
    « appel d'offres nettoyage Casablanca ». Ces pages annoncent le volume
    réel et un aperçu, sans livrer le détail réservé aux membres.
    """
    return render(req, "seo_index.html", {"pages": _secteurs_publics()})


@app.get("/marches-publics/{slug}", response_class=HTMLResponse)
async def marches_secteur(req: Request, slug: str):
    pages = _secteurs_publics()
    page = next((p for p in pages if p["slug"] == slug), None)
    if not page:
        return render(req, "404.html", {}, status_code=404)
    db = get_db()
    apercu = [dict(r) for r in db.execute(
        """SELECT id, objet, acheteur, region, date_limite, montant, type_procedure
           FROM tenders WHERE statut='actif' AND secteur=?
           ORDER BY scraped_at DESC LIMIT 6""", (page["code"],)).fetchall()]
    villes = [r[0] for r in db.execute(
        """SELECT region FROM tenders WHERE statut='actif' AND secteur=? AND region!=''
           GROUP BY region ORDER BY COUNT(*) DESC LIMIT 8""", (page["code"],)).fetchall()]
    db.close()
    proches = [p for p in pages if p["code"] != page["code"] and p["n"]][:8]
    return render(req, "seo_secteur.html",
                  {"page": page, "apercu": apercu, "villes": villes, "proches": proches})


@app.post("/webhooks/brevo")
async def webhook_brevo(req: Request):
    """Événements de livraison envoyés par Brevo (rebonds, spam, blocages).

    Une adresse qui rebondit définitivement, ou dont le titulaire nous classe
    en spam, doit cesser d'être sollicitée sur-le-champ: s'entêter fait
    chuter la réputation du domaine et emporte la livraison de tous les
    autres messages. L'URL porte un jeton, sans quoi n'importe qui pourrait
    couper les alertes d'un membre en connaissant son adresse.
    """
    if cfg.BREVO_WEBHOOK_TOKEN and req.query_params.get("t") != cfg.BREVO_WEBHOOK_TOKEN:
        return JSONResponse({"ok": False}, 403)
    try:
        evenement = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "corps illisible"}, 400)
    from app.services.notifications import traiter_evenement_brevo
    loop = asyncio.get_event_loop()
    resultat = await loop.run_in_executor(None, lambda: traiter_evenement_brevo(evenement))
    # Toujours 200: un code d'erreur ferait retenter Brevo indéfiniment pour
    # un événement qui, de notre côté, n'appelle aucune action.
    return JSONResponse({"ok": True, "traitement": resultat})


@app.get("/sitemap.xml")
async def sitemap():
    # Les fiches de marchés restent hors du plan du site: elles redirigent
    # vers /login et exposeraient des identifiants sans rien apporter. Les
    # pages sectorielles, elles, ont du contenu public et un volume réel.
    urls = [f"{cfg.SITE_URL}/", f"{cfg.SITE_URL}/tarifs", f"{cfg.SITE_URL}/login",
            f"{cfg.SITE_URL}/register", f"{cfg.SITE_URL}/contact",
            f"{cfg.SITE_URL}/marches-publics", f"{cfg.SITE_URL}/sous-traitance",
            f"{cfg.SITE_URL}/mentions-legales", f"{cfg.SITE_URL}/cgu",
            f"{cfg.SITE_URL}/confidentialite"]
    urls += [f"{cfg.SITE_URL}/marches-publics/{p['slug']}" for p in _secteurs_publics()]
    corps = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{corps}\n</urlset>")
    return Response(xml, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nSitemap: {cfg.SITE_URL}/sitemap.xml\n",
                    media_type="text/plain")

# ── PWA (installable sur mobile) ───────────────────────────
def _pwa_icon_svg(size: int) -> str:
    """Icone de l'application installee, sur fond encre.

    Les deux lettres « ME » ont laisse place au disque coupe: a la taille
    d'une icone de telephone, une forme se reconnait, un texte se devine.
    """
    return marque.etoile(size, fond=marque.ENCRE)


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
        "description": "Veille des marchés publics, semi-publics et privés au Maroc",
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
