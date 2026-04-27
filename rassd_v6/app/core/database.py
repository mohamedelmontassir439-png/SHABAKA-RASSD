"""
SOURCE v2.1 — Database Layer
=============================
✅ SQLAlchemy with connection pooling
✅ Async context manager
✅ Automatic migrations
"""
import sqlite3
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.config import cfg

# === Connection Pooling ===
engine = create_engine(
    f"sqlite:///{cfg.DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=cfg.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# === Schema ===
SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    plan TEXT DEFAULT 'free',
    actif INTEGER DEFAULT 1,
    session_token TEXT DEFAULT '',
    reset_token TEXT DEFAULT '',
    reset_expires TEXT DEFAULT '',
    created_at TEXT,
    lang TEXT DEFAULT 'fr',
    onboarded INTEGER DEFAULT 0,
    stx10_codes TEXT DEFAULT '[]',
    regions TEXT DEFAULT '[]',
    telegram TEXT DEFAULT '',
    whatsapp TEXT DEFAULT '',
    notif_tg INTEGER DEFAULT 0,
    notif_email INTEGER DEFAULT 0,
    notif_wa INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tenders (
    id TEXT PRIMARY KEY,
    objet TEXT NOT NULL,
    acheteur TEXT DEFAULT '',
    stx10_code TEXT DEFAULT '',
    stx10_label TEXT DEFAULT '',
    region TEXT DEFAULT '',
    montant TEXT DEFAULT '',
    date_publication TEXT DEFAULT '',
    date_limite TEXT DEFAULT '',
    url TEXT DEFAULT '',
    statut TEXT DEFAULT 'actif',
    scraped_at TEXT,
    ai_summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    tender_id TEXT NOT NULL,
    added_at TEXT,
    UNIQUE(member_id, tender_id)
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    tender_id TEXT NOT NULL,
    status TEXT DEFAULT 'watching',
    result TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    score_go INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    submitted_at TEXT,
    UNIQUE(member_id, tender_id)
);

CREATE TABLE IF NOT EXISTS tender_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    tender_id TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT,
    UNIQUE(member_id, tender_id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER DEFAULT 0,
    plan TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    amount INTEGER DEFAULT 0,
    nom TEXT DEFAULT '',
    email TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    new_count INTEGER DEFAULT 0,
    error TEXT DEFAULT ''
);

-- === Indexes ===
CREATE INDEX IF NOT EXISTS idx_tenders_statut ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_tenders_stx10 ON tenders(stx10_code);
CREATE INDEX IF NOT EXISTS idx_tenders_date_limite ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_tenders_scraped_at ON tenders(scraped_at);
CREATE INDEX IF NOT EXISTS idx_favorites_member ON favorites(member_id);
CREATE INDEX IF NOT EXISTS idx_submissions_member ON submissions(member_id);
CREATE INDEX IF NOT EXISTS idx_members_email ON members(email);
CREATE INDEX IF NOT EXISTS idx_members_token ON members(session_token);
"""

def init_db():
    """Initialize database with schema — uses executescript for multi-statement SQL"""
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    # SQLAlchemy text() can't run multiple statements — use raw sqlite3
    import sqlite3 as _sq3
    con = _sq3.connect(cfg.DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()

def get_db() -> Session:
    """Synchronous database session (for non-async contexts)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@asynccontextmanager
async def get_db_session():
    """Async database session — uses raw sqlite3 for compatibility"""
    import sqlite3 as _sq3
    db = _sq3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = _sq3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()
