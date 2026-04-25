import os, sqlite3, logging
from app.core.config import cfg
logger = logging.getLogger("source.db")

def get_db():
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tenders (
            id               TEXT PRIMARY KEY,
            objet            TEXT NOT NULL DEFAULT '',
            acheteur         TEXT DEFAULT '',
            stx10_code       TEXT DEFAULT '',
            stx10_label      TEXT DEFAULT '',
            region           TEXT DEFAULT '',
            montant          TEXT DEFAULT '',
            date_publication TEXT DEFAULT '',
            date_limite      TEXT DEFAULT '',
            url              TEXT DEFAULT '',
            statut           TEXT DEFAULT 'actif',
            scraped_at       TEXT DEFAULT '',
            ai_summary       TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS members (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nom           TEXT NOT NULL DEFAULT '',
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            plan          TEXT DEFAULT 'free',
            actif         INTEGER DEFAULT 1,
            lang          TEXT DEFAULT 'fr',
            telegram      TEXT DEFAULT '',
            whatsapp      TEXT DEFAULT '',
            stx10_codes   TEXT DEFAULT '[]',
            regions       TEXT DEFAULT '[]',
            notif_tg      INTEGER DEFAULT 1,
            notif_email   INTEGER DEFAULT 1,
            notif_wa      INTEGER DEFAULT 0,
            session_token TEXT DEFAULT '',
            created_at    TEXT DEFAULT '',
            onboarded     INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS favorites (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            tender_id TEXT NOT NULL,
            added_at  TEXT NOT NULL,
            UNIQUE(member_id, tender_id)
        );
        CREATE TABLE IF NOT EXISTS notif_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            tender_id TEXT NOT NULL,
            channel   TEXT NOT NULL,
            sent_at   TEXT NOT NULL,
            UNIQUE(member_id, tender_id, channel)
        );
        CREATE TABLE IF NOT EXISTS scrape_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            found    INTEGER DEFAULT 0,
            duration REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS payments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id  INTEGER,
            plan       TEXT NOT NULL,
            nom        TEXT DEFAULT '',
            email      TEXT DEFAULT '',
            status     TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_t_statut  ON tenders(statut);
        CREATE INDEX IF NOT EXISTS idx_t_stx10   ON tenders(stx10_code);
        CREATE INDEX IF NOT EXISTS idx_t_scraped ON tenders(scraped_at DESC);
        CREATE INDEX IF NOT EXISTS idx_m_email   ON members(email);
        CREATE INDEX IF NOT EXISTS idx_m_session ON members(session_token);
        CREATE INDEX IF NOT EXISTS idx_n_dedup   ON notif_log(member_id,tender_id,channel);
        CREATE INDEX IF NOT EXISTS idx_f_member  ON favorites(member_id);
    """)
    # Safe migrations
    t_cols = {r[1] for r in db.execute("PRAGMA table_info(tenders)").fetchall()}
    m_cols = {r[1] for r in db.execute("PRAGMA table_info(members)").fetchall()}
    for c,d in [("ai_summary","TEXT DEFAULT ''"),("stx10_label","TEXT DEFAULT ''")]:
        if c not in t_cols: db.execute(f"ALTER TABLE tenders ADD COLUMN {c} {d}")
    for c,d in [("lang","TEXT DEFAULT 'fr'"),("whatsapp","TEXT DEFAULT ''"),
                ("notif_wa","INTEGER DEFAULT 0"),("regions","TEXT DEFAULT '[]'"),
                ("onboarded","INTEGER DEFAULT 0")]:
        if c not in m_cols: db.execute(f"ALTER TABLE members ADD COLUMN {c} {d}")
    db.commit(); db.close()
    logger.info("✅ DB prête")
