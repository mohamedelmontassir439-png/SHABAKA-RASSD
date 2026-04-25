import os, sqlite3, logging
from app.core.config import cfg

logger = logging.getLogger("source.db")

def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA cache_size=-32000")
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
            telegram      TEXT DEFAULT '',
            whatsapp      TEXT DEFAULT '',
            stx10_codes   TEXT DEFAULT '[]',
            regions       TEXT DEFAULT '[]',
            notif_tg      INTEGER DEFAULT 1,
            notif_email   INTEGER DEFAULT 1,
            notif_wa      INTEGER DEFAULT 0,
            session_token TEXT DEFAULT '',
            reset_token   TEXT DEFAULT '',
            reset_expires TEXT DEFAULT '',
            created_at    TEXT DEFAULT '',
            expires_at    TEXT DEFAULT '',
            onboarded     INTEGER DEFAULT 0,
            lang          TEXT DEFAULT 'fr'
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
            errors   INTEGER DEFAULT 0,
            duration REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            tender_id TEXT NOT NULL,
            added_at  TEXT NOT NULL,
            UNIQUE(member_id, tender_id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id  INTEGER NOT NULL,
            plan       TEXT NOT NULL,
            status     TEXT DEFAULT 'pending',
            amount     INTEGER DEFAULT 0,
            notes      TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tenders_statut   ON tenders(statut);
        CREATE INDEX IF NOT EXISTS idx_tenders_stx10    ON tenders(stx10_code);
        CREATE INDEX IF NOT EXISTS idx_tenders_scraped  ON tenders(scraped_at DESC);
        CREATE INDEX IF NOT EXISTS idx_members_email    ON members(email);
        CREATE INDEX IF NOT EXISTS idx_notif_dedup      ON notif_log(member_id, tender_id, channel);
        CREATE INDEX IF NOT EXISTS idx_favorites        ON favorites(member_id);
    """)

    # Safe migrations
    existing_t = {r[1] for r in db.execute("PRAGMA table_info(tenders)").fetchall()}
    existing_m = {r[1] for r in db.execute("PRAGMA table_info(members)").fetchall()}

    new_t = [("ai_summary","TEXT DEFAULT ''"), ("stx10_label","TEXT DEFAULT ''")]
    new_m = [("lang","TEXT DEFAULT 'fr'"), ("notif_wa","INTEGER DEFAULT 0"),
             ("whatsapp","TEXT DEFAULT ''"), ("regions","TEXT DEFAULT '[]'"),
             ("onboarded","INTEGER DEFAULT 0"), ("expires_at","TEXT DEFAULT ''")]

    for col, typ in new_t:
        if col not in existing_t:
            db.execute(f"ALTER TABLE tenders ADD COLUMN {col} {typ}")
    for col, typ in new_m:
        if col not in existing_m:
            db.execute(f"ALTER TABLE members ADD COLUMN {col} {typ}")

    db.commit()
    db.close()
    logger.info("✅ DB initialisée")
