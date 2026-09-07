"""
ATLAS PRO — Database Layer (SQLite)
"""
import os, sqlite3, logging
from datetime import datetime
from app.core.config import cfg

logger = logging.getLogger("atlas.db")

# ── SQLite (local / Railway) ──────────────────────────────
def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA cache_size=-32000")  # 32MB cache
    return db

# ── Schema SQLite ─────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    id               TEXT PRIMARY KEY,
    objet            TEXT NOT NULL DEFAULT '',
    acheteur         TEXT DEFAULT '',
    secteur          TEXT DEFAULT '',
    region           TEXT DEFAULT '',
    montant          TEXT DEFAULT '',
    date_publication TEXT DEFAULT '',
    date_limite      TEXT DEFAULT '',
    description      TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    statut           TEXT DEFAULT 'actif',
    views            INTEGER DEFAULT 0,
    scraped_at       TEXT DEFAULT '',
    updated_at       TEXT DEFAULT '',
    type_offre       TEXT DEFAULT 'Public',
    source           TEXT DEFAULT 'marchespublics',
    type_procedure   TEXT DEFAULT 'marche'
);
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nom          TEXT DEFAULT '',
    email        TEXT UNIQUE NOT NULL,
    phone        TEXT DEFAULT '',
    company      TEXT DEFAULT '',
    pw_hash      TEXT DEFAULT '',
    plan         TEXT DEFAULT 'free',
    secteurs     TEXT DEFAULT '[]',
    regions      TEXT DEFAULT '[]',
    telegram     TEXT DEFAULT '',
    notif_email  INTEGER DEFAULT 1,
    notif_tg     INTEGER DEFAULT 0,
    notif_digest INTEGER DEFAULT 1,
    actif        INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT '',
    trial_ends   TEXT DEFAULT '',
    last_login   TEXT DEFAULT '',
    session_token  TEXT DEFAULT '',
    whatsapp       TEXT DEFAULT '',
    notif_wa       INTEGER DEFAULT 0,
    reset_token    TEXT DEFAULT '',
    reset_expires  TEXT DEFAULT '',
    onboarded      INTEGER DEFAULT 0,
    last_digest_sent TEXT DEFAULT '',
    referral_code    TEXT DEFAULT '',
    referred_by      INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    tender_id TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
CREATE TABLE IF NOT EXISTS notif_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER,
    tender_id TEXT,
    channel TEXT,
    sent_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    found INTEGER DEFAULT 0,
    saved INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    run_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER,
    email      TEXT DEFAULT '',
    message    TEXT DEFAULT '',
    features   TEXT DEFAULT '[]',
    rating     INTEGER DEFAULT 0,
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tender_results (
    id                TEXT PRIMARY KEY,
    reference         TEXT DEFAULT '',
    objet             TEXT DEFAULT '',
    acheteur          TEXT DEFAULT '',
    adjudicataire     TEXT DEFAULT '',
    region            TEXT DEFAULT '',
    budget            TEXT DEFAULT '',
    montant           TEXT DEFAULT '',
    secteur           TEXT DEFAULT '',
    date_adjudication TEXT DEFAULT '',
    date_ouverture    TEXT DEFAULT '',
    date_affichage    TEXT DEFAULT '',
    dao_url           TEXT DEFAULT '',
    pv_url            TEXT DEFAULT '',
    scraped_at        TEXT DEFAULT '',
    type_procedure    TEXT DEFAULT 'marche'
);

CREATE TABLE IF NOT EXISTS subcontract_posts (
    id           TEXT PRIMARY KEY,
    member_id    INTEGER NOT NULL,
    type         TEXT DEFAULT 'demande',
    titre        TEXT DEFAULT '',
    secteur      TEXT DEFAULT '',
    region       TEXT DEFAULT '',
    budget       TEXT DEFAULT '',
    date_limite  TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    statut       TEXT DEFAULT 'actif',
    created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subcontract_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      TEXT NOT NULL,
    sender_id    INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    body         TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',
    read_at      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subcontract_ratings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    TEXT NOT NULL,
    rater_id   INTEGER NOT NULL,
    rated_id   INTEGER NOT NULL,
    rating     INTEGER DEFAULT 5,
    comment    TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    UNIQUE(post_id, rater_id, rated_id)
);
CREATE TABLE IF NOT EXISTS notif_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    tender_id  TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
-- ── Abonnements / paiements ────────────────────────────────
-- Le paiement est encaissé hors plateforme (virement, espèces, WhatsApp) puis
-- enregistré par l'admin : ces tables tracent la réalité comptable, elles ne
-- simulent aucune passerelle de paiement.
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id    INTEGER NOT NULL,
    plan_id      TEXT DEFAULT 'monthly',
    price        REAL DEFAULT 0,
    currency     TEXT DEFAULT 'MAD',
    status       TEXT DEFAULT 'TRIAL',
    start_date   TEXT DEFAULT '',
    end_date     TEXT DEFAULT '',
    trial_start  TEXT DEFAULT '',
    trial_end    TEXT DEFAULT '',
    payment_id   INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT '',
    updated_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id       INTEGER NOT NULL,
    subscription_id INTEGER DEFAULT 0,
    amount          REAL DEFAULT 0,
    currency        TEXT DEFAULT 'MAD',
    method          TEXT DEFAULT '',
    reference       TEXT DEFAULT '',
    status          TEXT DEFAULT 'PAID',
    period_start    TEXT DEFAULT '',
    period_end      TEXT DEFAULT '',
    paid_at         TEXT DEFAULT '',
    recorded_by     TEXT DEFAULT 'admin',
    note            TEXT DEFAULT '',
    created_at      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type        TEXT DEFAULT 'receipt',
    number          TEXT DEFAULT '',
    member_id       INTEGER NOT NULL,
    subscription_id INTEGER DEFAULT 0,
    payment_id      INTEGER DEFAULT 0,
    payload         TEXT DEFAULT '{}',
    accepted_at     TEXT DEFAULT '',
    accepted_ip     TEXT DEFAULT '',
    created_at      TEXT DEFAULT ''
);
-- ── Base entreprises (intelligence commerciale) ────────────
-- normalized_name sert de clé de rapprochement: c'est le nom réduit à sa
-- forme canonique (sans accents, sans forme juridique, sans ponctuation),
-- ce qui permet de reconnaître "STE ATLAS BTP SARL" et "Atlas B.T.P. S.A.R.L"
-- comme une seule et même entreprise.
CREATE TABLE IF NOT EXISTS companies (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    legal_name       TEXT DEFAULT '',
    trade_name       TEXT DEFAULT '',
    normalized_name  TEXT DEFAULT '',
    sector           TEXT DEFAULT '',
    subsector        TEXT DEFAULT '',
    city             TEXT DEFAULT '',
    region           TEXT DEFAULT '',
    address          TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    mobile           TEXT DEFAULT '',
    email            TEXT DEFAULT '',
    website          TEXT DEFAULT '',
    ice              TEXT DEFAULT '',
    if_num           TEXT DEFAULT '',
    rc               TEXT DEFAULT '',
    source           TEXT DEFAULT '',
    source_url       TEXT DEFAULT '',
    source_type      TEXT DEFAULT '',
    wins             INTEGER DEFAULT 0,
    verified         INTEGER DEFAULT 0,
    last_verified_at TEXT DEFAULT '',
    created_at       TEXT DEFAULT '',
    updated_at       TEXT DEFAULT ''
);
-- Chaque source d'où provient une entreprise est conservée: on ne supprime
-- jamais une provenance en fusionnant deux doublons.
CREATE TABLE IF NOT EXISTS company_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    source      TEXT DEFAULT '',
    source_url  TEXT DEFAULT '',
    raw_name    TEXT DEFAULT '',
    seen_at     TEXT DEFAULT ''
);
-- ── Registre de conformité des sources (§28) ───────────────
CREATE TABLE IF NOT EXISTS source_registry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name      TEXT UNIQUE NOT NULL,
    source_type      TEXT DEFAULT '',
    domain           TEXT DEFAULT '',
    source_url       TEXT DEFAULT '',
    access_method    TEXT DEFAULT '',
    robots_status    TEXT DEFAULT 'unknown',
    terms_checked    INTEGER DEFAULT 0,
    scraping_allowed TEXT DEFAULT 'unknown',
    api_available    INTEGER DEFAULT 0,
    status           TEXT DEFAULT 'active',
    last_checked     TEXT DEFAULT '',
    notes            TEXT DEFAULT ''
);
-- ── Exécutions de scraper, par source (§24) ────────────────
CREATE TABLE IF NOT EXISTS scraper_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT DEFAULT '',
    status         TEXT DEFAULT 'RUNNING',
    records_found  INTEGER DEFAULT 0,
    records_saved  INTEGER DEFAULT 0,
    duplicates     INTEGER DEFAULT 0,
    errors         INTEGER DEFAULT 0,
    duration_ms    INTEGER DEFAULT 0,
    message        TEXT DEFAULT '',
    started_at     TEXT DEFAULT '',
    finished_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subcontract_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT NOT NULL,
    reporter_id INTEGER NOT NULL,
    reason      TEXT DEFAULT '',
    created_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS error_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    path       TEXT DEFAULT '',
    method     TEXT DEFAULT '',
    message    TEXT DEFAULT '',
    traceback  TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_t_scraped  ON tenders(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_secteur  ON tenders(secteur);
CREATE INDEX IF NOT EXISTS idx_t_deadline ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_t_type     ON tenders(type_offre);
CREATE INDEX IF NOT EXISTS idx_t_proc     ON tenders(type_procedure);
CREATE INDEX IF NOT EXISTS idx_m_email    ON members(email);
CREATE INDEX IF NOT EXISTS idx_fav_member ON favorites(member_id);
CREATE INDEX IF NOT EXISTS idx_r_scraped  ON tender_results(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_r_secteur  ON tender_results(secteur);
CREATE INDEX IF NOT EXISTS idx_sp_statut  ON subcontract_posts(statut);
CREATE INDEX IF NOT EXISTS idx_sp_type    ON subcontract_posts(type);
CREATE INDEX IF NOT EXISTS idx_sp_member  ON subcontract_posts(member_id);
CREATE INDEX IF NOT EXISTS idx_sm_post    ON subcontract_messages(post_id);
CREATE INDEX IF NOT EXISTS idx_sm_sender  ON subcontract_messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_sm_recip   ON subcontract_messages(recipient_id);
CREATE INDEX IF NOT EXISTS idx_sr_post    ON subcontract_ratings(post_id);
CREATE INDEX IF NOT EXISTS idx_sr_rated   ON subcontract_ratings(rated_id);
CREATE INDEX IF NOT EXISTS idx_nq_member  ON notif_queue(member_id);
CREATE INDEX IF NOT EXISTS idx_srep_post  ON subcontract_reports(post_id);
CREATE INDEX IF NOT EXISTS idx_err_created ON error_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sub_member  ON subscriptions(member_id);
CREATE INDEX IF NOT EXISTS idx_sub_status  ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_pay_member  ON payments(member_id);
CREATE INDEX IF NOT EXISTS idx_pay_paid    ON payments(paid_at DESC);
CREATE INDEX IF NOT EXISTS idx_doc_member  ON documents(member_id);
CREATE INDEX IF NOT EXISTS idx_doc_number  ON documents(number);
CREATE INDEX IF NOT EXISTS idx_co_norm     ON companies(normalized_name);
CREATE INDEX IF NOT EXISTS idx_co_sector   ON companies(sector);
CREATE INDEX IF NOT EXISTS idx_co_region   ON companies(region);
CREATE INDEX IF NOT EXISTS idx_co_ice      ON companies(ice);
CREATE INDEX IF NOT EXISTS idx_co_wins     ON companies(wins DESC);
CREATE INDEX IF NOT EXISTS idx_cosrc_co    ON company_sources(company_id);
CREATE INDEX IF NOT EXISTS idx_srun_src    ON scraper_runs(source);
CREATE INDEX IF NOT EXISTS idx_srun_start  ON scraper_runs(started_at DESC);
"""

def migrate_db():
    """Ajoute les colonnes manquantes si nécessaire.

    Les erreurs 'duplicate column' sont ignorées (normal = colonne déjà présente).
    Les autres erreurs sont loguées mais n'arrêtent pas le processus.
    """
    db = get_db()
    cols = [
        "ALTER TABLE members ADD COLUMN session_token TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN whatsapp TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN notif_wa INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN reset_token TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN reset_expires TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN onboarded INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN type_offre TEXT DEFAULT 'Public'",
        "ALTER TABLE tenders ADD COLUMN source TEXT DEFAULT 'marchespublics'",
        "ALTER TABLE members ADD COLUMN last_digest_sent TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN referral_code TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN referred_by INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN type_procedure TEXT DEFAULT 'marche'",
        "ALTER TABLE tender_results ADD COLUMN type_procedure TEXT DEFAULT 'marche'",
        # Abonnement / essai gratuit
        "ALTER TABLE members ADD COLUMN trial_start TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN subscription_status TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN subscription_end TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN email_verified INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN whatsapp_verified INTEGER DEFAULT 0",
        # Consentement WhatsApp + vérification du numéro
        "ALTER TABLE members ADD COLUMN wa_optin_at TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN wa_verify_code TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN wa_verify_expires TEXT DEFAULT ''",
        # Filtres d'alerte (moteur de correspondance)
        "ALTER TABLE members ADD COLUMN notif_regions TEXT DEFAULT '[]'",
        "ALTER TABLE members ADD COLUMN notif_keywords TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN notif_min_budget INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN notif_types TEXT DEFAULT '[]'",
        # Journal de notification: statut de livraison
        "ALTER TABLE notif_log ADD COLUMN status TEXT DEFAULT 'SENT'",
        "ALTER TABLE notif_log ADD COLUMN error TEXT DEFAULT ''",
        "ALTER TABLE notif_log ADD COLUMN provider TEXT DEFAULT ''",
    ]
    for col in cols:
        try:
            db.execute(col)
            db.commit()
        except sqlite3.OperationalError as e:
            # 'duplicate column name' = colonne existe déjà, c'est OK
            if "duplicate column" not in str(e).lower():
                logger.warning(f"[migrate] {col[:50]}...: {e}")
        except Exception as e:
            logger.error(f"[migrate] Erreur inattendue: {e}")
    db.close()

def seed_source_registry():
    """Enregistre les sources exploitées et leur statut de conformité (§28).

    Les valeurs consignées correspondent à des vérifications réelles, pas à
    des suppositions: au 07/09/2026, marchespublics.gov.ma renvoie 403 sur
    /robots.txt (aucun fichier servi) et global-marches.com renvoie une page
    HTML applicative à la place d'un robots.txt (donc aucun fichier non plus).
    L'admin peut corriger ces champs depuis /admin/sources.
    """
    rows = [
        # source_name, type, domain, url, access, robots, terms_checked, allowed, api, status, notes
        ("marchespublics", "public", "marchespublics.gov.ma",
         "https://www.marchespublics.gov.ma", "http_public", "unavailable_403", 0, "public_data", 0, "active",
         "Portail officiel des marchés publics. /robots.txt renvoie 403 — aucune directive publiée. "
         "Données de commande publique par nature publiques. Rythme de requêtes volontairement modéré."),
        ("global-marches", "private_aggregator", "global-marches.com",
         "https://global-marches.com", "authenticated_account", "absent", 0, "partner_agreement", 0, "active",
         "Agrégateur privé (AO privés + bons de commande). Accès via un compte fourni par l'éditeur "
         "du site. À formaliser par un accord écrit (licence de données ou API) — un accord verbal ne "
         "protège pas la continuité du service. Nom de la source jamais exposé aux utilisateurs finaux."),
        ("tender_results", "derived", "", "", "internal", "n/a", 1, "own_data", 0, "active",
         "Données dérivées des résultats d'adjudication déjà collectés — sert de base à la table companies."),
    ]
    db = get_db()
    try:
        for r in rows:
            db.execute(
                """INSERT OR IGNORE INTO source_registry
                   (source_name,source_type,domain,source_url,access_method,robots_status,
                    terms_checked,scraping_allowed,api_available,status,last_checked,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*r[:10], datetime.now().strftime("%Y-%m-%d"), r[10]))
        db.commit()
    except Exception as e:
        logger.error(f"[seed_source_registry] {e}")
    finally:
        db.close()

def migrate_subscriptions():
    """Renseigne subscription_status pour les membres créés avant la mise en
    place de l'essai gratuit.

    Prudence volontaire: les membres 'free' existants sont marqués EXPIRED et
    non TRIAL. Sans cela, l'activation du contrôle d'accès basé sur l'essai
    ouvrirait rétroactivement l'accès complet à d'anciens comptes jamais
    payants (leur trial_ends de 14 jours ayant pu être écrit récemment), ce que
    l'admin n'a jamais validé. Seules les nouvelles inscriptions bénéficient de
    l'essai de 7 jours. Idempotent: ne touche que les lignes non renseignées.
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, plan FROM members WHERE subscription_status IS NULL OR subscription_status=''"
        ).fetchall()
        for row in rows:
            status = "ACTIVE" if row["plan"] in ("pro", "business") else "EXPIRED"
            db.execute("UPDATE members SET subscription_status=? WHERE id=?", (status, row["id"]))
        if rows:
            db.commit()
            logger.info(f"✅ {len(rows)} membre(s) migré(s) vers le suivi d'abonnement")
    except Exception as e:
        logger.error(f"[migrate_subscriptions] {e}")
    finally:
        db.close()

def migrate_secteurs():
    """Reclassifie les marchés scrapés avant le passage aux codes officiels MB SA
    (l'ancien scraper stockait des libellés libres du type "Travaux BTP" qui ne
    correspondent à aucun code choisi par les membres — les alertes ne
    partaient donc jamais pour eux). Ne retouche que les lignes invalides,
    donc ne coûte rien une fois toutes les lignes migrées.
    """
    from app.core.sectors import SECTORS, classify
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, objet, description FROM tenders WHERE secteur NOT IN ({})".format(
                ",".join("?" * len(SECTORS))),
            list(SECTORS.keys())
        ).fetchall()
        for row in rows:
            code = classify(f"{row['objet']} {row['description'][:400]}")
            db.execute("UPDATE tenders SET secteur=? WHERE id=?", (code, row["id"]))
        if rows:
            db.commit()
            logger.info(f"✅ {len(rows)} marchés reclassifiés vers les codes officiels")
    except Exception as e:
        logger.error(f"[migrate_secteurs] {e}")
    finally:
        db.close()

def init_db():
    """Initialise le schéma de la base de données.

    Exécute chaque statement SQL séparément pour que les tables déjà existantes
    ne bloquent pas la création des nouvelles.
    """
    db = get_db()
    for stmt in SCHEMA.split(";"):
        s = stmt.strip()
        if s:
            try:
                db.execute(s)
            except sqlite3.OperationalError as e:
                # Table/index déjà présent = OK
                if "already exists" not in str(e).lower():
                    logger.warning(f"[init_db] {s[:60]}...: {e}")
            except Exception as e:
                logger.error(f"[init_db] Erreur: {e}")
    db.commit()
    db.close()
    logger.info("✅ DB initialisée")
    try:
        migrate_db()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration: {e}")
    try:
        migrate_subscriptions()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration abonnements: {e}")
    try:
        seed_source_registry()
    except Exception as e:
        logger.error(f"[init_db] Erreur registre des sources: {e}")
    try:
        migrate_secteurs()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration secteurs: {e}")
