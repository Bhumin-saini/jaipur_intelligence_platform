"""
JIP — Intelligence Storage Layer (FR-03)
SQLite with WAL mode + busy_timeout to prevent lock errors.
"""
import sqlite3, os
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "jip.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    body         TEXT,
    url          TEXT    UNIQUE NOT NULL,
    published_at TEXT,
    scraped_at   TEXT    DEFAULT (datetime('now')),
    nlp_status   TEXT    CHECK(nlp_status IN ('pending','success','failed','duplicate')) DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id     INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    event_type     TEXT,
    summary        TEXT,
    severity       TEXT CHECK(severity IN ('low','medium','high')) DEFAULT 'low',
    keywords       TEXT,
    locations      TEXT,
    organizations  TEXT,
    people         TEXT,
    related_topics TEXT,
    lat            REAL    DEFAULT 26.9124,
    lng            REAL    DEFAULT 75.7873,
    raw_llm_output TEXT,
    created_at     TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    type            TEXT CHECK(type IN ('person','organization','location')) NOT NULL,
    normalized_name TEXT NOT NULL,
    mention_count   INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    first_seen_at   TEXT DEFAULT (datetime('now')),
    last_seen_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(normalized_name, type)
);

CREATE TABLE IF NOT EXISTS event_entities (
    event_id  INTEGER REFERENCES events(id)   ON DELETE CASCADE,
    entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    role      TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_events_severity  ON events(severity);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_entities_type    ON entities(type);
"""

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "articles", "nlp_status", "TEXT DEFAULT 'pending'")
        conn.execute("UPDATE articles SET nlp_status = COALESCE(nlp_status, 'pending')")
        conn.execute(
            """UPDATE articles
               SET nlp_status = 'success'
               WHERE id IN (SELECT article_id FROM events)
                 AND nlp_status IN ('pending', '')"""
        )
        _ensure_column(conn, "entities", "first_seen_at", "TEXT")
        _ensure_column(conn, "entities", "last_seen_at", "TEXT")
        conn.execute("UPDATE entities SET first_seen_at = COALESCE(first_seen_at, created_at)")
        conn.execute("UPDATE entities SET last_seen_at = COALESCE(last_seen_at, created_at)")


def _ensure_column(conn, table: str, column: str, column_type: str):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
