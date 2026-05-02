"""
ATLAS PRO — Database Layer
Supports: SQLite (local) + Supabase (cloud PostgreSQL)
"""
import os, sqlite3, logging
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

# ── Supabase (cloud) ─────────────────────────────────────
_supa = None
def get_supabase():
    global _supa
    if _supa: return _supa
    url = cfg.SUPABASE_URL
    key = cfg.SUPABASE_KEY
    if not url or not key: return None
    try:
        from supabase import create_client
        _supa = create_client(url, key)
        logger.info("✅ Supabase connecté")
        return _supa
    except Exception as e:
        logger.error(f"[Supabase] {e}")
        return None

def supabase_sync_tender(t: dict) -> bool:
    """Sync un tender vers Supabase (upsert)"""
    supa = get_supabase()
    if not supa: return False
    try:
        supa.table("tenders").upsert({
            "id":               t["id"],
            "objet":            t["objet"],
            "acheteur":         t.get("acheteur",""),
            "secteur":          t.get("secteur",""),
            "region":           t.get("region",""),
            "montant":          t.get("montant",""),
            "date_publication": t.get("date_publication",""),
            "date_limite":      t.get("date_limite",""),
            "url":              t.get("url",""),
            "statut":           t.get("statut","actif"),
            "scraped_at":       t.get("scraped_at",""),
        }).execute()
        return True
    except Exception as e:
        logger.error(f"[Supabase sync] {e}")
        return False

def supabase_sync_batch(tenders: list) -> int:
    """Sync batch vers Supabase"""
    supa = get_supabase()
    if not supa or not tenders: return 0
    try:
        rows = [{
            "id": t["id"], "objet": t["objet"],
            "acheteur": t.get("acheteur",""),
            "secteur": t.get("secteur",""),
            "region": t.get("region",""),
            "date_limite": t.get("date_limite",""),
            "url": t.get("url",""),
            "statut": "actif",
            "scraped_at": t.get("scraped_at",""),
        } for t in tenders]
        supa.table("tenders").upsert(rows).execute()
        logger.info(f"[Supabase] {len(rows)} marchés synchronisés")
        return len(rows)
    except Exception as e:
        logger.error(f"[Supabase batch] {e}")
        return 0

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
    updated_at       TEXT DEFAULT ''
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
    onboarded      INTEGER DEFAULT 0
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

CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_t_scraped  ON tenders(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_secteur  ON tenders(secteur);
CREATE INDEX IF NOT EXISTS idx_t_deadline ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_m_email    ON members(email);
CREATE INDEX IF NOT EXISTS idx_fav_member ON favorites(member_id);
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
