"""
Modern Business — Base de données SQLite
WAL mode pour performances optimales.
"""
import os, sqlite3
from app.core.config import cfg

def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    id               TEXT PRIMARY KEY,
    objet            TEXT NOT NULL DEFAULT '',
    acheteur         TEXT DEFAULT '',
    region           TEXT DEFAULT '',
    domaine          TEXT DEFAULT '',
    type_marche      TEXT DEFAULT '',
    montant          TEXT DEFAULT '',
    budget_min       REAL DEFAULT 0,
    budget_max       REAL DEFAULT 0,
    date_publication TEXT DEFAULT '',
    date_limite      TEXT DEFAULT '',
    description      TEXT DEFAULT '',
    statut           TEXT DEFAULT 'actif',
    url              TEXT DEFAULT '',
    source           TEXT DEFAULT '',
    contact          TEXT DEFAULT '',
    ai_score         INTEGER DEFAULT 50,
    ai_category      TEXT DEFAULT '',
    ai_reason        TEXT DEFAULT '',
    date_extraction  TEXT DEFAULT '',
    views            INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nom          TEXT DEFAULT '',
    entreprise   TEXT DEFAULT '',
    email        TEXT UNIQUE NOT NULL,
    phone        TEXT DEFAULT '',
    secteur      TEXT DEFAULT '',
    ville        TEXT DEFAULT '',
    pw_hash      TEXT DEFAULT '',
    plan         TEXT DEFAULT 'free',
    actif        INTEGER DEFAULT 0,
    verify_token TEXT DEFAULT '',
    telegram     TEXT DEFAULT '',
    last_login   TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',
    notif_email  INTEGER DEFAULT 1,
    notif_tg     INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS member_filters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    type       TEXT DEFAULT 'secteur',
    value      TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS favoris (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    tender_id  TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
CREATE TABLE IF NOT EXISTS notif_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id   INTEGER NOT NULL,
    tender_ids  TEXT DEFAULT '',
    channel     TEXT DEFAULT 'email',
    status      TEXT DEFAULT 'pending',
    attempts    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT '',
    sent_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scrape_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT DEFAULT '',
    found      INTEGER DEFAULT 0,
    saved      INTEGER DEFAULT 0,
    errors     INTEGER DEFAULT 0,
    duration_s REAL DEFAULT 0,
    run_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agent_repairs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT DEFAULT '',
    detail     TEXT DEFAULT '',
    success    INTEGER DEFAULT 1,
    repaired_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER DEFAULT 0,
    role       TEXT DEFAULT 'user',
    content    TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    key        TEXT UNIQUE NOT NULL,
    name       TEXT DEFAULT 'API Key',
    created_at TEXT DEFAULT '',
    last_used  TEXT DEFAULT '',
    active     INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_t_score   ON tenders(ai_score DESC);
CREATE INDEX IF NOT EXISTS idx_t_date    ON tenders(date_extraction DESC);
CREATE INDEX IF NOT EXISTS idx_t_dl      ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_m_email   ON members(email);
"""

def init_db():
    db = get_db()
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            try: db.execute(stmt)
            except: pass
    db.commit()
    db.close()
