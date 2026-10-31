"""Runs, people and segments: import stage-1 results, (re)classify them, and read them back."""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from . import config, db, pipeline, settings
from .pipeline import STATES


def run_dir(run_id: int) -> Path:
    return config.RUNS_DIR / str(run_id)


@lru_cache(maxsize=32)
def _raw(run_id: int, mtime: float) -> dict:
    return json.loads((run_dir(run_id) / "raw.json").read_text())


def raw(run_id: int) -> dict:
    p = run_dir(run_id) / "raw.json"
    return _raw(run_id, p.stat().st_mtime)


def import_raw(video_id: int, result: dict, thumbs_src: Path | None = None, ref_src: Path | None = None) -> int:
    """Store a `pipeline.detect_track()` result as a new run, then classify it."""
    if result.get("version") != 2 or "tracks" not in result:
        raise ValueError("Not a WorkWatch v2 analysis file (re-run `python -m workwatch analyze`)")
    with db.tx() as c:
        v = db.row(c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
        prev = db.latest_run_id(c, video_id)
        carry = {r["track_id"]: dict(r) for r in c.execute(
            "SELECT track_id, label, worker_id, removed FROM persons WHERE run_id=?", (prev,))} if prev else {}
        run_id = c.execute(
            "INSERT INTO runs (org_id, video_id, created_at, params, stats, ref) VALUES (?,?,?,?,?,?)",
            (v["org_id"], video_id, db.now(), db.dumps(result.get("params", {})), db.dumps(result.get("stats", {})),
             db.dumps(result.get("ref"))),
        ).lastrowid
        d = run_dir(run_id)
        (d / "thumbs").mkdir(parents=True, exist_ok=True)
        (d / "raw.json").write_text(json.dumps({k: result[k] for k in ("version", "video", "params", "tracks")},
                                               separators=(",", ":")))
        if ref_src and Path(ref_src).exists():
            shutil.copy(ref_src, d / "ref.jpg")
        thumbs = result.get("thumbs") or {}
        for tid_s, samples in result["tracks"].items():
            tid = int(tid_s)
            thumb = thumbs.get(tid_s) or thumbs.get(tid)
            if thumb and thumbs_src and (Path(thumbs_src) / thumb).exists():
                shutil.copy(Path(thumbs_src) / thumb, d / "thumbs" / thumb)
            else:
                thumb = None
            old = carry.get(tid, {})
            label = old.get("label") or f"Person {tid}"
            c.execute("INSERT INTO persons (run_id, track_id, label, worker_id, thumb, first_seen, last_seen, removed) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (run_id, tid, label, old.get("worker_id"), thumb, samples[0][0], samples[-1][0],
                       old.get("removed", 0)))
        meta, dec = result.get("video", {}), result.get("decode") or {}
        c.execute("UPDATE videos SET duration=COALESCE(?, duration), fps=COALESCE(?, fps), width=COALESCE(?, width), "
                  "height=COALESCE(?, height), partial=MAX(partial, ?), gap_note=COALESCE(gap_note, ?), annotated=0, "
                  "sent=0 WHERE id=?",
                  (meta.get("duration"), meta.get("fps"), meta.get("width"), meta.get("height"),
                   int(bool(dec.get("partial"))), dec.get("gap_note"), video_id))
        classify_video(c, video_id)
    return run_id


def _root(pid, merged):
    seen = set()
    while merged.get(pid) and pid not in seen:
        seen.add(pid)
        pid = merged[pid]
    return pid


def classify_video(c, video_id: int) -> int | None:
    """Apply the video's zones and the org's analysis rules to the latest run. Keeps review decisions
    on segments that come out identical, so tweaking a name or a far-away zone doesn't wipe reviews."""
    v = db.row(c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    run_id = db.latest_run_id(c, video_id)
    if not v or not run_id:
        return None
    rules = settings.get(c, v["org_id"])["rules"]
    persons = db.rows(c.execute("SELECT * FROM persons WHERE run_id=?", (run_id,)))
    merged = {p["id"]: p["merged_into"] for p in persons}
    by_id = {p["id"]: p for p in persons}
    groups: dict[int, list[int]] = defaultdict(list)
    root_pid = {}
    for p in persons:
        root = by_id[_root(p["id"], merged)]
        if root["removed"]:
            continue
        groups[root["track_id"]].append(p["track_id"])
        root_pid[root["track_id"]] = root["id"]

    res = pipeline.classify(raw(run_id), v["zones"], rules, groups) if v["zones"] else {}

    old = {}
    for s in db.rows(c.execute('SELECT * FROM segments WHERE run_id=? AND review_status NOT IN (\'none\',\'pending\')',
                               (run_id,))):
        old[(s["person_id"], round(s["start"], 2), round(s["end"], 2), s["state"])] = s
    c.execute("DELETE FROM segments WHERE run_id=?", (run_id,))
    c.execute("UPDATE persons SET totals='{}', zones='{}' WHERE run_id=?", (run_id,))
    for tid, out in res.items():
        pid = root_pid[tid]
        c.execute("UPDATE persons SET totals=?, zones=?, first_seen=?, last_seen=? WHERE id=?",
                  (db.dumps(out["totals"]), db.dumps(out["zones"]), out["first_seen"], out["last_seen"], pid))
        for s in out["segments"]:
            prev = old.get((pid, round(s["start"], 2), round(s["end"], 2), s["state"]))
            status = prev["review_status"] if prev else ("pending" if s["flagged"] else "none")
            c.execute('INSERT INTO segments (run_id, person_id, start, "end", state, zone, confidence, flagged, '
                      "flag_reason, review_status, reviewed_state, note, reviewed_by, reviewed_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (run_id, pid, s["start"], s["end"], s["state"], s["zone"], s["confidence"], int(s["flagged"]),
                       s["flag_reason"], status, prev and prev["reviewed_state"], prev and prev["note"],
                       prev and prev["reviewed_by"], prev and prev["reviewed_at"]))
    c.execute("UPDATE runs SET rules=?, classified_at=? WHERE id=?", (db.dumps(rules), db.now(), run_id))
    return run_id


def run_people(c, run_id: int, include_removed: bool = True) -> list[dict]:
    """People of a run with totals recomputed from segments, so review reclassifications count."""
    persons = db.rows(c.execute(
        "SELECT p.*, w.name AS worker_name, w.employee_id FROM persons p LEFT JOIN workers w ON w.id=p.worker_id "
        "WHERE run_id=? ORDER BY track_id", (run_id,)))
    merged = {p["id"]: p["merged_into"] for p in persons}
    by_id = {}
    for p in persons:
        if p["merged_into"]:
            continue
        if p["removed"] and not include_removed:
            continue
        by_id[p["id"]] = {**p, "track_ids": [p["track_id"]], "segments": [], "flagged": 0, "pending": 0,
                          "totals": {s: 0.0 for s in STATES}, "zone_totals": defaultdict(lambda: defaultdict(float))}
    for p in persons:
        if p["merged_into"] and (owner := by_id.get(_root(p["id"], merged))):
            owner["track_ids"].append(p["track_id"])
            owner.setdefault("merged", []).append({"id": p["id"], "track_id": p["track_id"]})
    for s in db.rows(c.execute("SELECT * FROM segments WHERE run_id=? ORDER BY start", (run_id,))):
        owner = by_id.get(s["person_id"])
        if owner is None:
            continue
        st = db.effective_state(s)
        s["effective_state"] = st
        d = s["end"] - s["start"]
        owner["totals"][st] += d
        owner["zone_totals"][s["zone"] or "Outside zones"][st] += d
        owner["flagged"] += s["flagged"]
        owner["pending"] += s["review_status"] == "pending"
        owner["segments"].append(s)
    out = list(by_id.values())
    for p in out:
        t = p["totals"]
        p["present_s"] = sum(t.values())
        p["working_s"] = t["working"]
        p["efficiency"] = efficiency(t)
        p["zone_totals"] = {z: dict(v) for z, v in p["zone_totals"].items()}
        p.pop("zones", None)
    return out


def efficiency(t: dict) -> float:
    """Working ÷ (present − exclusion): time in exclusion zones is not held against the worker."""
    base = sum(t.values()) - t.get("exclusion", 0)
    return round(100 * t.get("working", 0) / base, 1) if base > 0 else 0.0


STATUS_LABELS = {"uploaded": "Uploaded", "slice": "Slice received", "queued": "Queued", "analysing": "Analysing",
                 "failed": "Failed", "annotate": "Annotate people & zones", "review": "Review pending",
                 "report_ready": "Report ready", "sent": "Sent"}


def video_view(c, v: dict) -> dict:
    """Video row + pipeline status: Uploaded → Analysing → Annotate → Review pending → Report ready → Sent."""
    job = db.row(c.execute("SELECT * FROM jobs WHERE video_id=? ORDER BY id DESC LIMIT 1", (v["id"],)).fetchone())
    run_id = db.latest_run_id(c, v["id"])
    pending = c.execute("SELECT COUNT(*) FROM segments WHERE run_id=? AND review_status='pending'", (run_id,)).fetchone()[0] if run_id else 0
    people = c.execute("SELECT COUNT(*) FROM persons WHERE run_id=? AND merged_into IS NULL AND removed=0",
                       (run_id,)).fetchone()[0] if run_id else 0
    if job and job["status"] in ("queued", "analysing"):
        status = job["status"]
    elif job and job["status"] == "failed" and not run_id:
        status = "failed"
    elif not run_id:
        status = "slice" if v["source"] == "camera" else "uploaded"
    elif not v["annotated"]:
        status = "annotate"
    elif pending:
        status = "review"
    else:
        status = "sent" if v["sent"] else "report_ready"
    v.update(status=status, status_label=STATUS_LABELS[status], run_id=run_id, pending=pending, people=people,
             job=job and {k: job[k] for k in ("id", "status", "progress", "error", "attempts", "worker")})
    if v.get("camera_id"):
        cam = c.execute("SELECT name FROM cameras WHERE id=?", (v["camera_id"],)).fetchone()
        v["camera_name"] = cam["name"] if cam else None
    if v.get("site_id"):
        s = c.execute("SELECT name FROM sites WHERE id=?", (v["site_id"],)).fetchone()
        v["site_name"] = s["name"] if s else None
    return v
