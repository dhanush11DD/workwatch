"""Saving pipeline results and reading them back as per-person totals."""
from __future__ import annotations

import json
import shutil

from . import config, db


def run_dir(run_id: int):
    return config.RUNS_DIR / str(run_id)


def import_results(video_id: int, result: dict, thumbs_src=None) -> int:
    """Store an `analyze()` result as a new run of `video_id`. Returns the run id."""
    with db.tx() as c:
        # Re-runs with the same model/settings reproduce track ids, so keep names given to people last time.
        prev = db.latest_run_id(c, video_id)
        names = {r["track_id"]: r["label"] for r in c.execute(
            "SELECT track_id, label FROM persons WHERE run_id=? AND label NOT LIKE 'Worker %'", (prev,))} if prev else {}
        cur = c.execute(
            "INSERT INTO runs (video_id, created_at, params, stats) VALUES (?,?,?,?)",
            (video_id, db.now(), json.dumps(result.get("params", {})), json.dumps(result.get("stats", {}))),
        )
        run_id = cur.lastrowid
        d = run_dir(run_id)
        (d / "thumbs").mkdir(parents=True, exist_ok=True)
        (d / "tracks.json").write_text(json.dumps(result.get("tracks", {}), separators=(",", ":")))
        for p in result["people"]:
            thumb = p.get("thumb")
            if thumb and thumbs_src and (thumbs_src / thumb).exists():
                shutil.copy(thumbs_src / thumb, d / "thumbs" / thumb)
            pid = c.execute(
                "INSERT INTO persons (run_id, track_id, label, thumb, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                (run_id, p["track_id"], names.get(p["track_id"], p["label"]), thumb, p["first_seen"], p["last_seen"]),
            ).lastrowid
            for s in p["segments"]:
                c.execute(
                    'INSERT INTO segments (run_id, person_id, start, "end", state, zone, confidence, flagged, '
                    "flag_reason, review_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run_id, pid, s["start"], s["end"], s["state"], s["zone"], s["confidence"],
                     int(s["flagged"]), s["flag_reason"], "pending" if s["flagged"] else "none"),
                )
        meta = result.get("video", {})
        c.execute(
            "UPDATE videos SET status='done', progress=1, error=NULL, duration=COALESCE(?, duration), "
            "fps=COALESCE(?, fps), width=COALESCE(?, width), height=COALESCE(?, height) WHERE id=?",
            (meta.get("duration"), meta.get("fps"), meta.get("width"), meta.get("height"), video_id),
        )
    return run_id


def _union(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _length(intervals):
    return sum(b - a for a, b in intervals)


def _root(pid, merged):
    seen = set()
    while merged.get(pid) and pid not in seen:
        seen.add(pid)
        pid = merged[pid]
    return pid


def run_people(conn, run_id: int) -> list[dict]:
    """Per-person totals for a run, with merges and review corrections applied."""
    persons = db.rows(conn.execute("SELECT * FROM persons WHERE run_id=? ORDER BY track_id", (run_id,)))
    merged = {p["id"]: p["merged_into"] for p in persons}
    by_id = {p["id"]: {**p, "working_s": 0.0, "idle_s": 0.0, "flagged": 0, "pending": 0, "segments": [],
                       "track_ids": [p["track_id"]]}
             for p in persons if not p["merged_into"]}
    for p in persons:
        if p["merged_into"] and (owner := by_id.get(_root(p["id"], merged))):
            owner["track_ids"].append(p["track_id"])
    segs = db.rows(conn.execute('SELECT * FROM segments WHERE run_id=? ORDER BY start', (run_id,)))
    for s in segs:
        owner = by_id.get(_root(s["person_id"], merged))
        if owner is None:
            continue
        s["effective_state"] = db.effective_state(s)
        owner["flagged"] += s["flagged"]
        owner["pending"] += s["review_status"] == "pending"
        owner["first_seen"] = min(owner["first_seen"], s["start"])
        owner["last_seen"] = max(owner["last_seen"], s["end"])
        owner["segments"].append(s)
    out = list(by_id.values())
    for p in out:
        p["segments"].sort(key=lambda s: s["start"])
        # Merged tracks can overlap in time: count each second once, and working wins over idle.
        work = _union([(s["start"], s["end"]) for s in p["segments"] if s["effective_state"] == "working"])
        idle = _union([(s["start"], s["end"]) for s in p["segments"] if s["effective_state"] != "working"])
        p["working_s"] = _length(work)
        p["idle_s"] = _length(_union(work + idle)) - p["working_s"]
        obs = p["working_s"] + p["idle_s"]
        p["efficiency"] = round(100 * p["working_s"] / obs, 1) if obs else 0.0
    return out


def video_with_status(conn, video_id: int):
    v = db.row(conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    if not v:
        return None
    v["run_id"] = db.latest_run_id(conn, video_id)
    if v["camera_id"]:
        cam = conn.execute("SELECT name FROM cameras WHERE id=?", (v["camera_id"],)).fetchone()
        v["camera_name"] = cam["name"] if cam else None
    return v
