"""SQLite connection and schema for the baggage desk."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    passenger  TEXT NOT NULL CHECK (trim(passenger) <> ''),
    flight     TEXT NOT NULL CHECK (trim(flight) <> ''),
    claim_type TEXT NOT NULL CHECK (claim_type IN ('delayed', 'lost', 'damaged')),
    tier       TEXT NOT NULL CHECK (tier IN ('standard', 'silver', 'gold')),
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open', 'assigned', 'escalated', 'resolved', 'closed')),
    agent      TEXT,
    note       TEXT NOT NULL DEFAULT '',
    filed_at   TEXT NOT NULL,
    deadline   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id   INTEGER NOT NULL REFERENCES claims(id),
    old_status TEXT
               CHECK (old_status IS NULL
                      OR old_status IN ('open', 'assigned', 'escalated', 'resolved', 'closed')),
    new_status TEXT NOT NULL
               CHECK (new_status IN ('open', 'assigned', 'escalated', 'resolved', 'closed')),
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
"""


def connect(path):
    """Open the database file with rows addressable by column name and foreign keys on."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Create the claims and history tables if they do not exist yet."""
    conn.executescript(SCHEMA)
