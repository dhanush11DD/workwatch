"""Processing infrastructure: the analysis job queue, workers, footage ingestion and scheduled maintenance.

Job states (shown in the UI): queued → analysing → complete | failed (retried once automatically).

Workers:
  * in-process  — threads inside the web server (WW_INPROCESS_WORKER=1, WW_WORKERS=N)
  * local       — `python -m workwatch worker` on the same machine/DB
  * remote GPU  — `python -m workwatch worker --server https://app --token $WW_WORKER_TOKEN`
                  claims jobs over HTTP, downloads the footage, runs stage 1 on its GPU and uploads results.
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import socket
import tempfile
import threading
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, db, events, pipeline, settings, store

log = logging.getLogger("workwatch.jobs")
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts"}
STALE_S = 600
WORKER_NAME = f"{socket.gethostname()}:{os.getpid()}"


# ---------- queue ----------

def enqueue(c, video_id: int) -> int:
    v = c.execute("SELECT org_id FROM videos WHERE id=?", (video_id,)).fetchone()
    busy = c.execute("SELECT id FROM jobs WHERE video_id=? AND status IN ('queued','analysing')", (video_id,)).fetchone()
    if busy:
        return busy["id"]
    return c.execute("INSERT INTO jobs (org_id, video_id, created_at) VALUES (?,?,?)",
                     (v["org_id"], video_id, db.now())).lastrowid


def claim(worker: str) -> dict | None:
    with db.tx() as c:
        # Requeue jobs whose worker stopped heart-beating.
        c.execute("UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END, "
                  "error=COALESCE(error,'worker stopped responding') WHERE status='analysing' AND heartbeat<?",
                  (db.now() - STALE_S,))
        r = c.execute(
            "UPDATE jobs SET status='analysing', worker=?, started_at=?, heartbeat=?, attempts=attempts+1, progress=0 "
            "WHERE id=(SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1) RETURNING *",
            (worker, db.now(), db.now())).fetchone()
        return db.row(r)


def progress(job_id: int, p: float) -> None:
    with db.tx() as c:
        c.execute("UPDATE jobs SET progress=?, heartbeat=? WHERE id=?", (round(p, 3), db.now(), job_id))


def finish(job_id: int, result: dict, thumbs_src=None, ref_src=None) -> int:
    with db.tx() as c:
        job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    run_id = store.import_raw(job["video_id"], result, thumbs_src=thumbs_src, ref_src=ref_src)
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='complete', progress=1, finished_at=?, error=NULL WHERE id=?",
                  (db.now(), job_id))
        v = c.execute("SELECT * FROM videos WHERE id=?", (job["video_id"],)).fetchone()
        n = c.execute("SELECT COUNT(*) FROM persons WHERE run_id=?", (run_id,)).fetchone()[0]
        kind = "Slice" if v["source"] == "camera" else "Footage"
        events.emit(c, v["org_id"], "slice_ready", f"{kind} ready for annotation: {v['name']}",
                    f"{n} people tracked. Name people, remove visitors and confirm zones to continue.",
                    f"/videos/{v['id']}")
    return run_id


def fail(job_id: int, error: str) -> None:
    with db.tx() as c:
        job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        retry = job["attempts"] < 2
        c.execute("UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?",
                  ("queued" if retry else "failed", error[:500], None if retry else db.now(), job_id))
        if not retry:
            v = c.execute("SELECT * FROM videos WHERE id=?", (job["video_id"],)).fetchone()
            events.emit(c, v["org_id"], "analysis_failed", f"Analysis failed: {v['name']}", error[:200],
                        f"/videos/{v['id']}")


def run_local(job: dict) -> None:
    with db.tx() as c:
        v = c.execute("SELECT * FROM videos WHERE id=?", (job["video_id"],)).fetchone()
    tmp = Path(tempfile.mkdtemp(prefix=f"job{job['id']}_", dir=config.DATA_DIR))
    try:
        last = [0.0]

        def prog(p):
            if p - last[0] >= 0.02 or p >= 1:
                last[0] = p
                progress(job["id"], p)

        result = pipeline.detect_track(str(config.VIDEOS_DIR / v["filename"]), thumbs_dir=str(tmp / "thumbs"),
                                       ref_path=str(tmp / "ref.jpg"), progress=prog)
        finish(job["id"], result, thumbs_src=tmp / "thumbs", ref_src=tmp / "ref.jpg")
        log.info("job %s done: %s", job["id"], result["stats"])
    except Exception as e:
        log.exception("job %s failed", job["id"])
        fail(job["id"], str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def worker_loop(stop: threading.Event | None = None, name: str = WORKER_NAME, once: bool = False):
    while not (stop and stop.is_set()):
        job = claim(name)
        if job:
            run_local(job)
            if once:
                return
        else:
            if once:
                return
            time.sleep(2)


def start_inprocess_workers():
    if not config.INPROCESS_WORKER:
        return
    for i in range(max(1, int(os.environ.get("WW_WORKERS", "1")))):
        threading.Thread(target=worker_loop, kwargs={"name": f"{WORKER_NAME}/t{i}"}, daemon=True,
                         name=f"analysis-worker-{i}").start()


# ---------- remote (GPU) worker over HTTP ----------

def remote_worker(server: str, token: str, once: bool = False):
    server = server.rstrip("/")
    hdr = {"X-Worker-Token": token}

    def call(path, data=None, ctype="application/json"):
        req = urllib.request.Request(server + path, data=data, headers={**hdr, "Content-Type": ctype},
                                     method="POST" if data is not None else "GET")
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.read()

    log.info("remote worker %s polling %s", WORKER_NAME, server)
    while True:
        job = json.loads(call("/api/worker/claim", json.dumps({"worker": WORKER_NAME}).encode()) or b"null")
        if not job:
            if once:
                return
            time.sleep(5)
            continue
        tmp = Path(tempfile.mkdtemp(prefix=f"rjob{job['id']}_"))
        try:
            video = tmp / f"video{job['suffix']}"
            req = urllib.request.Request(f"{server}/api/worker/jobs/{job['id']}/video", headers=hdr)
            with urllib.request.urlopen(req, timeout=3600) as r, open(video, "wb") as f:
                shutil.copyfileobj(r, f, 4 << 20)
            last = [0.0]

            def prog(p):
                if p - last[0] >= 0.05 or p >= 1:
                    last[0] = p
                    call(f"/api/worker/jobs/{job['id']}/progress", json.dumps({"progress": p}).encode())

            result = pipeline.detect_track(str(video), thumbs_dir=str(tmp / "thumbs"), ref_path=str(tmp / "ref.jpg"),
                                           progress=prog)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("result.json", json.dumps(result))
                for f in (tmp / "thumbs").glob("*.jpg"):
                    z.write(f, f"thumbs/{f.name}")
                if (tmp / "ref.jpg").exists():
                    z.write(tmp / "ref.jpg", "ref.jpg")
            call(f"/api/worker/jobs/{job['id']}/result", buf.getvalue(), "application/zip")
            log.info("remote job %s done %s", job["id"], result["stats"])
        except Exception as e:
            log.exception("remote job %s failed", job["id"])
            try:
                call(f"/api/worker/jobs/{job['id']}/fail", json.dumps({"error": str(e)}).encode())
            except Exception:
                pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if once:
            return


def import_result_zip(job_id: int, data: bytes) -> int:
    tmp = Path(tempfile.mkdtemp(prefix=f"res{job_id}_", dir=config.DATA_DIR))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.startswith("/") or ".." in n:
                    raise ValueError("bad archive")
            z.extractall(tmp)
        return finish(job_id, json.loads((tmp / "result.json").read_text()), thumbs_src=tmp / "thumbs",
                      ref_src=tmp / "ref.jpg")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- ingestion ----------

def register_video(org_id: int, src: Path, name: str, *, camera_id=None, site_id=None, shift=None, recorded_on=None,
                   source="upload", partial=False, gap_note=None, move=True, is_demo=False, created_by=None,
                   zones=None, analyse=True) -> int:
    meta = pipeline.probe(str(src))
    with db.tx() as c:
        if camera_id:
            cam = db.row(c.execute("SELECT * FROM cameras WHERE id=? AND org_id=?", (camera_id, org_id)).fetchone())
            if not cam:
                raise ValueError("Unknown camera")
            zones = zones if zones is not None else cam["zones"]
            site_id = site_id or cam["site_id"]
            c.execute("UPDATE cameras SET last_clip_at=? WHERE id=?", (db.now(), camera_id))
        vid = c.execute(
            "INSERT INTO videos (org_id, site_id, camera_id, shift, source, name, filename, size, recorded_on, duration, "
            "fps, width, height, zones, partial, gap_note, is_demo, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (org_id, site_id, camera_id, shift, source, name, "", src.stat().st_size,
             recorded_on or date.today().isoformat(), meta["duration"], meta["fps"], meta["width"], meta["height"],
             db.dumps(zones or []), int(partial), gap_note, int(is_demo), created_by, db.now())).lastrowid
        filename = f"{vid}{src.suffix.lower() or '.mp4'}"
        (shutil.move if move else shutil.copy)(str(src), str(config.VIDEOS_DIR / filename))
        c.execute("UPDATE videos SET filename=? WHERE id=?", (filename, vid))
        if analyse:
            enqueue(c, vid)
    return vid


def ingest_inbox() -> list[int]:
    """Import files dropped in data/inbox/<camera id>/ (NVR exports or an ffmpeg segmenter).
    Files modified in the last 2 minutes are assumed to be still recording and are left for the next pass."""
    new = []
    for f in sorted(config.INBOX_DIR.glob("*/*")):
        if f.suffix.lower() not in VIDEO_EXTS or time.time() - f.stat().st_mtime < 120 or not f.parent.name.isdigit():
            continue
        with db.tx() as c:
            cam = c.execute("SELECT * FROM cameras WHERE id=?", (int(f.parent.name),)).fetchone()
        if not cam:
            continue
        try:
            recorded = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
            new.append(register_video(cam["org_id"], f, f"{cam['name']} · {f.stem}", camera_id=cam["id"],
                                      recorded_on=recorded, source="camera"))
        except Exception:
            log.exception("could not ingest %s", f)
    return new


# ---------- demo footage (analysed once, cloned into every new organization) ----------

DEMO_DIR = config.DATA_DIR / "demo"


def build_demo(video: Path, zones: list, name: str) -> dict:
    """Run the pipeline on the sample clip once and cache the result for clone_demo()."""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(video, DEMO_DIR / f"video{video.suffix.lower()}")
    shutil.rmtree(DEMO_DIR / "thumbs", ignore_errors=True)
    res = pipeline.detect_track(str(video), thumbs_dir=str(DEMO_DIR / "thumbs"), ref_path=str(DEMO_DIR / "ref.jpg"),
                                progress=lambda p: print(f"\r{p * 100:5.1f}%", end="", flush=True))
    print()
    (DEMO_DIR / "result.json").write_text(json.dumps(res))
    (DEMO_DIR / "meta.json").write_text(json.dumps({"name": name, "zones": zones}))
    return res


def clone_demo(org_id: int) -> int | None:
    """Give an organization the pre-analysed demo clip (annotated, ready to review). No-op without a cached demo."""
    if not (DEMO_DIR / "result.json").exists():
        return None
    meta = json.loads((DEMO_DIR / "meta.json").read_text())
    src = next(DEMO_DIR.glob("video.*"))
    vid = register_video(org_id, src, meta["name"], zones=meta["zones"], is_demo=True, move=False, analyse=False)
    store.import_raw(vid, json.loads((DEMO_DIR / "result.json").read_text()), thumbs_src=DEMO_DIR / "thumbs",
                     ref_src=DEMO_DIR / "ref.jpg")
    with db.tx() as c:
        c.execute("UPDATE videos SET annotated=1 WHERE id=?", (vid,))
    return vid


# ---------- scheduled maintenance ----------

def maintenance() -> dict:
    """Hourly: inbox, camera health, review reminders, footage retention, weekly summaries."""
    out = {"ingested": ingest_inbox(), "deleted": 0, "offline": 0}
    with db.tx() as c:
        for org in db.rows(c.execute("SELECT * FROM organizations")):
            s = settings.get(c, org["id"])
            # retention: delete footage files, keep analysis + reports
            cutoff = db.now() - s["privacy"]["retention_days"] * 86400
            for v in c.execute("SELECT * FROM videos WHERE org_id=? AND footage_deleted=0 AND is_demo=0 AND created_at<?",
                               (org["id"], cutoff)).fetchall():
                (config.VIDEOS_DIR / v["filename"]).unlink(missing_ok=True)
                c.execute("UPDATE videos SET footage_deleted=1 WHERE id=?", (v["id"],))
                db.audit(c, None, "retention.delete_footage", "video", v["id"], {"name": v["name"]}, None,
                         org_id=org["id"])
                out["deleted"] += 1
            # camera health
            for cam in c.execute("SELECT * FROM cameras WHERE org_id=? AND agent_last_seen IS NOT NULL AND "
                                 "agent_last_seen<? AND offline_notified=0", (org["id"], db.now() - 600)).fetchall():
                events.emit(c, org["id"], "camera_offline", f"Camera offline: {cam['name']}",
                            "The edge agent has not checked in for 10 minutes.", "/settings/cameras")
                c.execute("UPDATE cameras SET offline_notified=1 WHERE id=?", (cam["id"],))
                out["offline"] += 1
            # review reminder
            hrs = s["review"]["reminder_hours"]
            pending = c.execute(
                "SELECT COUNT(*) FROM segments s JOIN runs r ON r.id=s.run_id JOIN videos v ON v.id=r.video_id "
                "WHERE v.org_id=? AND v.annotated=1 AND s.review_status='pending' AND r.id=(SELECT MAX(id) FROM runs "
                "WHERE video_id=v.id)", (org["id"],)).fetchone()[0]
            last = c.execute("SELECT MAX(created_at) FROM notifications WHERE org_id=? AND event='review_pending'",
                             (org["id"],)).fetchone()[0] or 0
            if pending and hrs and db.now() - last > hrs * 3600:
                events.emit(c, org["id"], "review_pending", f"{pending} items pending review",
                            "Clear them to generate the report.", "/review")
    return out


def weekly_summary(org_id: int) -> str:
    from . import reports
    end = date.today()
    start = end - timedelta(days=7)
    with db.tx() as c:
        rows, totals, _, _ = reports.aggregate(c, org_id, {"date_from": start.isoformat(), "date_to": end.isoformat(),
                                                           "reviewed_only": True})
    top = "\n".join(f"• {r['person']}: {reports.hm(r['working_s'])} working ({r['efficiency']}%)" for r in rows[:10])
    return (f"WorkWatch weekly summary {start:%d %b}–{end:%d %b}\n{totals['people']} people · "
            f"{reports.hm(totals['working_s'])} working · {totals['efficiency']}% efficiency\n{top}")


def start_scheduler():
    def loop():
        last_week = None
        while True:
            try:
                maintenance()
                today = date.today()
                if today.weekday() == 0 and last_week != today:
                    last_week = today
                    from . import reports
                    with db.tx() as c:
                        orgs = [o["id"] for o in c.execute("SELECT id FROM organizations")]
                    for oid in orgs:
                        reports.send_summary(oid, weekly_summary(oid), "weekly")
            except Exception:
                log.exception("maintenance failed")
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="scheduler").start()
