import os, sqlite3
from app.core.config import cfg

def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    return db

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
    email_verified INTEGER DEFAULT 0,
    verify_token TEXT DEFAULT '',
    reset_token  TEXT DEFAULT '',
    api_key      TEXT DEFAULT '',
    last_login   TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',
    trial_ends   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    tender_id  TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
CREATE TABLE IF NOT EXISTS notif_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER,
    tender_id  TEXT,
    channel    TEXT,
    opened     INTEGER DEFAULT 0,
    sent_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scrape_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    found      INTEGER DEFAULT 0,
    saved      INTEGER DEFAULT 0,
    expired    INTEGER DEFAULT 0,
    errors     INTEGER DEFAULT 0,
    duration_s REAL DEFAULT 0,
    max_id     INTEGER DEFAULT 0,
    run_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER,
    action     TEXT,
    meta       TEXT DEFAULT '{}',
    ip         TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_t_scraped  ON tenders(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_secteur  ON tenders(secteur);
CREATE INDEX IF NOT EXISTS idx_t_deadline ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_m_email    ON members(email);
CREATE INDEX IF NOT EXISTS idx_m_plan     ON members(plan);
CREATE INDEX IF NOT EXISTS idx_fav_member ON favorites(member_id);
"""

def ensure_member_columns(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(members)").fetchall()}
    migrations = []
    if "email_verified" not in columns:
        migrations.append("ALTER TABLE members ADD COLUMN email_verified INTEGER DEFAULT 0")
    if "verify_token" not in columns:
        migrations.append("ALTER TABLE members ADD COLUMN verify_token TEXT DEFAULT ''")
    if "reset_token" not in columns:
        migrations.append("ALTER TABLE members ADD COLUMN reset_token TEXT DEFAULT ''")
    if "api_key" not in columns:
        migrations.append("ALTER TABLE members ADD COLUMN api_key TEXT DEFAULT ''")
    for stmt in migrations:
        try:
            db.execute(stmt)
        except Exception:
            pass


def init_db():
    db = get_db()
    for stmt in SCHEMA.split(";"):
        s = stmt.strip()
        if s:
            try: db.execute(s)
            except: pass
    ensure_member_columns(db)
    db.commit(); db.close()
