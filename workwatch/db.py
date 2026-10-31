"""SQLite storage (swap for Postgres in production; queries are plain SQL).

Multi-tenancy: every business table carries `org_id`, and every API query filters by the caller's
organization (see `scoped()` and the `org` checks in api code). The audit table is append-only:
triggers reject UPDATE and DELETE so the trail can be used in wage / attendance disputes.
"""
import json
import shutil
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT, address TEXT, logo TEXT,
    gstin TEXT, pan TEXT, billing_address TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    date_format TEXT NOT NULL DEFAULT 'DD-MM-YYYY',
    week_start TEXT NOT NULL DEFAULT 'Monday',
    plan TEXT NOT NULL DEFAULT 'trial',
    trial_ends REAL,
    settings TEXT NOT NULL DEFAULT '{}',
    deletion_requested_at REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    weekly_off TEXT NOT NULL DEFAULT '["Sunday"]',
    holidays TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT UNIQUE,
    phone TEXT UNIQUE,
    name TEXT,
    pw_hash TEXT,
    google_sub TEXT UNIQUE,
    role TEXT NOT NULL DEFAULT 'reviewer',          -- manager | reviewer
    status TEXT NOT NULL DEFAULT 'active',          -- active | removed
    site_ids TEXT NOT NULL DEFAULT '[]',            -- empty = all sites
    language TEXT NOT NULL DEFAULT 'en',
    photo TEXT,
    notify TEXT NOT NULL DEFAULT '{}',
    deletion_requested_at REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_agent TEXT,
    created_at REAL NOT NULL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL, role TEXT NOT NULL,
    site_ids TEXT NOT NULL DEFAULT '[]',
    created_by INTEGER, created_at REAL NOT NULL,
    accepted_at REAL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS otps (
    phone TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL, employee_id TEXT,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    name TEXT NOT NULL, location TEXT, brand TEXT,
    rtsp_url TEXT, onvif TEXT,
    agent_token TEXT UNIQUE, agent_last_seen REAL, agent_version TEXT, last_clip_at REAL,
    shifts TEXT NOT NULL DEFAULT '[{"name":"General","start":"09:00","end":"18:00"}]',
    auto_slice INTEGER NOT NULL DEFAULT 1,
    zones TEXT NOT NULL DEFAULT '[]',               -- zone template applied to new footage
    offline_notified INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER, length INTEGER NOT NULL, offset INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}', video_id INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    camera_id INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    shift TEXT, source TEXT NOT NULL DEFAULT 'upload',  -- upload | camera
    name TEXT NOT NULL, filename TEXT NOT NULL, size INTEGER,
    recorded_on TEXT,
    duration REAL, fps REAL, width INTEGER, height INTEGER,
    zones TEXT NOT NULL DEFAULT '[]',
    partial INTEGER NOT NULL DEFAULT 0, gap_note TEXT,
    annotated INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    footage_deleted INTEGER NOT NULL DEFAULT 0,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',          -- queued | analysing | complete | failed
    progress REAL NOT NULL DEFAULT 0,
    worker TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
    created_at REAL NOT NULL, started_at REAL, finished_at REAL, heartbeat REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    params TEXT, stats TEXT, ref TEXT,
    rules TEXT,                                     -- rule values used by the latest classification
    classified_at REAL
);
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    worker_id INTEGER REFERENCES workers(id) ON DELETE SET NULL,
    thumb TEXT, thumb_box TEXT,
    first_seen REAL, last_seen REAL,
    merged_into INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    removed INTEGER NOT NULL DEFAULT 0,
    totals TEXT NOT NULL DEFAULT '{}', zones TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    start REAL NOT NULL, "end" REAL NOT NULL,
    state TEXT NOT NULL, zone TEXT, confidence REAL,
    flagged INTEGER NOT NULL DEFAULT 0, flag_reason TEXT,
    review_status TEXT NOT NULL DEFAULT 'none',     -- none | pending | approved | reclassified
    reviewed_state TEXT, note TEXT,
    reviewed_by TEXT, reviewed_at REAL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL, report_date TEXT, date_to TEXT,
    filters TEXT NOT NULL DEFAULT '{}', video_ids TEXT NOT NULL,
    rows TEXT NOT NULL, totals TEXT NOT NULL, zones TEXT NOT NULL DEFAULT '{}',
    rules TEXT, notes TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ready',           -- ready | sent
    created_by TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    report_id INTEGER REFERENCES reports(id) ON DELETE CASCADE,
    channel TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'report',
    status TEXT NOT NULL, error TEXT, provider_id TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    event TEXT NOT NULL, title TEXT NOT NULL, body TEXT, link TEXT,
    read_by TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deletion_requests (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    subject TEXT NOT NULL, contact TEXT, details TEXT,
    status TEXT NOT NULL DEFAULT 'open',            -- open | in_progress | completed | rejected
    created_at REAL NOT NULL, resolved_at REAL, resolution TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    number TEXT NOT NULL, period TEXT, plan TEXT,
    amount REAL NOT NULL, gst REAL NOT NULL, total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'due', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL,
    user_id INTEGER, user_label TEXT,
    action TEXT NOT NULL, entity TEXT, entity_id TEXT,
    before TEXT, after TEXT,
    created_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit trail is immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit trail is immutable'); END;

CREATE INDEX IF NOT EXISTS idx_videos_org ON videos(org_id, recorded_on);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_video ON runs(video_id);
CREATE INDEX IF NOT EXISTS idx_persons_run ON persons(run_id);
CREATE INDEX IF NOT EXISTS idx_seg_run ON segments(run_id);
CREATE INDEX IF NOT EXISTS idx_seg_review ON segments(review_status);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit(org_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notif_org ON notifications(org_id, created_at);
"""

JSON_COLS = {"settings", "weekly_off", "holidays", "site_ids", "notify", "shifts", "zones", "metadata",
             "params", "stats", "ref", "rules", "totals", "filters", "video_ids", "rows", "notes",
             "read_by", "before", "after", "thumb_box"}


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
    """Create the schema. A v1 database (single tenant) is moved aside, not migrated in place."""
    if config.DB_PATH.exists():
        conn = connect()
        try:
            has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone()
            has_users = conn.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
        finally:
            conn.close()
        if has_users and not has_meta:
            backup = config.DB_PATH.with_name(f"workwatch.v1.{int(time.time())}.db")
            shutil.move(config.DB_PATH, backup)
            for suffix in ("-wal", "-shm"):
                p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
                if p.exists():
                    p.unlink()
    with tx() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)", (str(SCHEMA_VERSION),))


def now() -> float:
    return time.time()


def row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def rows(rs):
    return [row(r) for r in rs]


def dumps(v) -> str:
    return json.dumps(v, separators=(",", ":"), default=str)


def effective_state(seg) -> str:
    if seg["review_status"] == "reclassified" and seg["reviewed_state"]:
        return seg["reviewed_state"]
    return seg["state"]


def latest_run_id(conn, video_id):
    r = conn.execute("SELECT id FROM runs WHERE video_id=? ORDER BY id DESC LIMIT 1", (video_id,)).fetchone()
    return r["id"] if r else None


def audit(conn, user, action: str, entity: str | None = None, entity_id=None, before=None, after=None, org_id=None):
    conn.execute(
        "INSERT INTO audit (org_id, user_id, user_label, action, entity, entity_id, before, after, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (org_id or user["org_id"], user.get("id") if user else None,
         (user.get("email") or user.get("phone") or user.get("name")) if user else "system",
         action, entity, None if entity_id is None else str(entity_id),
         None if before is None else dumps(before), None if after is None else dumps(after), now()))


def notify(conn, org_id: int, event: str, title: str, body: str = "", link: str = ""):
    conn.execute("INSERT INTO notifications (org_id, event, title, body, link, created_at) VALUES (?,?,?,?,?,?)",
                 (org_id, event, title, body, link, now()))
