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
            ai_summary       TEXT DEFAULT '',
            score_avg        REAL  DEFAULT 0
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

        -- Pipeline de soumissions (NOUVEAU)
        CREATE TABLE IF NOT EXISTS submissions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id  INTEGER NOT NULL,
            tender_id  TEXT NOT NULL,
            status     TEXT DEFAULT 'watching',
            notes      TEXT DEFAULT '',
            score_go   INTEGER DEFAULT 0,
            submitted_at TEXT DEFAULT '',
            result     TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            UNIQUE(member_id, tender_id)
        );

        -- Notes sur les marchés (NOUVEAU)
        CREATE TABLE IF NOT EXISTS tender_notes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            tender_id TEXT NOT NULL,
            note      TEXT NOT NULL,
            created_at TEXT DEFAULT '',
            UNIQUE(member_id, tender_id)
        );

        -- Paiements
        CREATE TABLE IF NOT EXISTS payments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id  INTEGER DEFAULT 0,
            plan       TEXT NOT NULL,
            status     TEXT DEFAULT 'pending',
            amount     INTEGER DEFAULT 0,
            nom        TEXT DEFAULT '',
            email      TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        -- Alertes urgence envoyées
        CREATE TABLE IF NOT EXISTS urgent_alerts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            tender_id TEXT NOT NULL,
            sent_at   TEXT NOT NULL,
            UNIQUE(member_id, tender_id)
        );

        CREATE INDEX IF NOT EXISTS idx_tenders_statut  ON tenders(statut);
        CREATE INDEX IF NOT EXISTS idx_tenders_stx10   ON tenders(stx10_code);
        CREATE INDEX IF NOT EXISTS idx_tenders_scraped ON tenders(scraped_at DESC);
        CREATE INDEX IF NOT EXISTS idx_members_email   ON members(email);
        CREATE INDEX IF NOT EXISTS idx_submissions_m   ON submissions(member_id);
        CREATE INDEX IF NOT EXISTS idx_notif_dedup     ON notif_log(member_id, tender_id, channel);
    """)

    # Migrations sécurisées
    existing_t = {r[1] for r in db.execute("PRAGMA table_info(tenders)").fetchall()}
    existing_m = {r[1] for r in db.execute("PRAGMA table_info(members)").fetchall()}

    for col, typ in [("ai_summary","TEXT DEFAULT ''"), ("score_avg","REAL DEFAULT 0"),
                     ("stx10_label","TEXT DEFAULT ''")]:
        if col not in existing_t:
            try: db.execute(f"ALTER TABLE tenders ADD COLUMN {col} {typ}")
            except: pass

    for col, typ in [("lang","TEXT DEFAULT 'fr'"), ("notif_wa","INTEGER DEFAULT 0"),
                     ("whatsapp","TEXT DEFAULT ''"), ("regions","TEXT DEFAULT '[]'"),
                     ("onboarded","INTEGER DEFAULT 0"), ("reset_token","TEXT DEFAULT ''"),
                     ("reset_expires","TEXT DEFAULT ''")]:
        if col not in existing_m:
            try: db.execute(f"ALTER TABLE members ADD COLUMN {col} {typ}")
            except: pass

    db.commit()
    db.close()
    logger.info("✅ DB initialisée v2.0")
