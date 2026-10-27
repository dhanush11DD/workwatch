"""SQLite storage. One connection per call; WAL mode so the worker thread and API can share it."""
import json
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',      -- manager | viewer
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    rtsp_url TEXT,
    zones TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    camera_id INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    recorded_on TEXT,                         -- YYYY-MM-DD
    duration REAL, fps REAL, width INTEGER, height INTEGER,
    zones TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',       -- new | queued | processing | done | error
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    params TEXT, stats TEXT
);
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    thumb TEXT,
    first_seen REAL, last_seen REAL,
    merged_into INTEGER REFERENCES persons(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    start REAL NOT NULL, "end" REAL NOT NULL,
    state TEXT NOT NULL,                      -- working | idle
    zone TEXT,
    confidence REAL,
    flagged INTEGER NOT NULL DEFAULT 0,
    flag_reason TEXT,
    review_status TEXT NOT NULL DEFAULT 'none', -- none | pending | confirmed | corrected
    reviewed_state TEXT,
    reviewed_by TEXT, reviewed_at REAL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    report_date TEXT,
    video_ids TEXT NOT NULL,
    rows TEXT NOT NULL,
    totals TEXT NOT NULL,
    csv_path TEXT NOT NULL,
    created_by TEXT,
    emailed_to TEXT, emailed_at REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_video ON runs(video_id);
CREATE INDEX IF NOT EXISTS idx_seg_run ON segments(run_id);
CREATE INDEX IF NOT EXISTS idx_seg_review ON segments(review_status);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with tx() as c:
        c.executescript(SCHEMA)


def now() -> float:
    return time.time()


def row(r):
    if r is None:
        return None
    d = dict(r)
    for key in ("zones", "params", "stats", "rows", "totals", "video_ids"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


def rows(rs):
    return [row(r) for r in rs]


def effective_state(seg) -> str:
    if seg["review_status"] == "corrected" and seg["reviewed_state"]:
        return seg["reviewed_state"]
    return seg["state"]


def latest_run_id(conn, video_id):
    r = conn.execute("SELECT id FROM runs WHERE video_id=? ORDER BY id DESC LIMIT 1", (video_id,)).fetchone()
    return r["id"] if r else None


def latest_run_ids(conn):
    return [r["id"] for r in conn.execute("SELECT MAX(id) AS id FROM runs GROUP BY video_id").fetchall()]
