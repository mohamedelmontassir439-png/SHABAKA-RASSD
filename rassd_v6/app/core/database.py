"""
ATLAS PRO — Database Layer (SQLite)
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
    source           TEXT DEFAULT 'marchespublics'
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
CREATE INDEX IF NOT EXISTS idx_t_type     ON tenders(type_offre);
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
        "ALTER TABLE tenders ADD COLUMN type_offre TEXT DEFAULT 'Public'",
        "ALTER TABLE tenders ADD COLUMN source TEXT DEFAULT 'marchespublics'",
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
        migrate_secteurs()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration secteurs: {e}")
