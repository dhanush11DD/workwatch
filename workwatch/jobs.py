"""Background work: the analysis queue, CCTV capture, inbox ingestion and the daily job."""
from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2

from . import config, db, pipeline, reports, store

log = logging.getLogger("workwatch")
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts"}

_q: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None


# ---------- analysis queue ----------

def _set(video_id, **fields):
    with db.tx() as c:
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE videos SET {sets} WHERE id=?", (*fields.values(), video_id))


def analyze_video(video_id: int) -> int:
    """Run the pipeline on one video synchronously and store the result."""
    with db.tx() as c:
        v = db.row(c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    if not v:
        raise ValueError(f"No video {video_id}")
    _set(video_id, status="processing", progress=0, error=None)
    tmp_thumbs = config.RUNS_DIR / f"_tmp_{video_id}"
    try:
        last = [0.0]

        def progress(p):
            if p - last[0] >= 0.02 or p >= 1:
                last[0] = p
                _set(video_id, progress=round(p, 3))

        result = pipeline.analyze(str(config.VIDEOS_DIR / v["filename"]), v["zones"],
                                  thumbs_dir=str(tmp_thumbs), progress=progress)
        run_id = store.import_results(video_id, result, thumbs_src=tmp_thumbs)
        log.info("video %s analysed: run %s, %s", video_id, run_id, result["stats"])
        return run_id
    except Exception as e:  # surface the error on the video row
        log.exception("analysis failed for video %s", video_id)
        _set(video_id, status="error", error=str(e)[:500])
        raise
    finally:
        shutil.rmtree(tmp_thumbs, ignore_errors=True)


def _work():
    while True:
        vid = _q.get()
        try:
            analyze_video(vid)
        except Exception:
            pass
        finally:
            _q.task_done()


def enqueue(video_id: int):
    global _worker
    _set(video_id, status="queued", progress=0, error=None)
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, daemon=True, name="analysis-worker")
        _worker.start()
    _q.put(video_id)


def resume_interrupted():
    """Re-queue videos left queued/processing when the server stopped."""
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM videos WHERE status IN ('queued','processing')")]
    for i in ids:
        enqueue(i)


# ---------- videos / cameras ----------

def register_video(src: Path, name: str, camera_id: int | None = None, recorded_on: str | None = None,
                   zones: list | None = None, move: bool = False, is_demo: bool = False) -> int:
    meta = pipeline.probe(str(src))
    if zones is None and camera_id:
        with db.tx() as c:
            cam = db.row(c.execute("SELECT zones FROM cameras WHERE id=?", (camera_id,)).fetchone())
            zones = cam["zones"] if cam else []
    with db.tx() as c:
        vid = c.execute(
            "INSERT INTO videos (name, filename, camera_id, recorded_on, duration, fps, width, height, zones, "
            "is_demo, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, "", camera_id, recorded_on or date.today().isoformat(), meta["duration"], meta["fps"],
             meta["width"], meta["height"], json.dumps(zones or []), int(is_demo), db.now()),
        ).lastrowid
        filename = f"{vid}{src.suffix.lower() or '.mp4'}"
        dst = config.VIDEOS_DIR / filename
        (shutil.move if move else shutil.copy)(str(src), str(dst))
        c.execute("UPDATE videos SET filename=? WHERE id=?", (filename, vid))
    return vid


def snapshot(rtsp_url: str):
    cap = cv2.VideoCapture(rtsp_url)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Could not read a frame from the camera stream")
    return frame


def record_camera(camera_id: int, minutes: float) -> int:
    """Record `minutes` of a camera's stream into a new video. Uses ffmpeg (stream copy) if present."""
    with db.tx() as c:
        cam = db.row(c.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone())
    if not cam or not cam["rtsp_url"]:
        raise ValueError("Camera has no stream URL")
    stamp = datetime.now()
    out = config.INBOX_DIR / f"_rec_{camera_id}_{stamp:%Y%m%d_%H%M%S}.mp4"
    secs = int(minutes * 60)
    if shutil.which("ffmpeg"):
        args = ["ffmpeg", "-y", "-loglevel", "error"]
        if cam["rtsp_url"].startswith("rtsp"):
            args += ["-rtsp_transport", "tcp"]
        args += ["-i", cam["rtsp_url"], "-t", str(secs), "-c:v", "copy", "-an", "-movflags", "+faststart", str(out)]
        subprocess.run(args, check=True, timeout=secs + 120)
    else:
        cap = cv2.VideoCapture(cam["rtsp_url"])
        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"avc1"), fps, (w, h))
        end = time.time() + secs
        while time.time() < end:
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
        writer.release()
        cap.release()
    return register_video(out, f"{cam['name']} {stamp:%Y-%m-%d %H:%M}", camera_id=camera_id,
                          recorded_on=stamp.date().isoformat(), move=True)


def ingest_inbox() -> list[int]:
    """Import video files dropped into data/inbox/ (or data/inbox/<camera_id>/ to inherit that camera's zones).

    Point an NVR export or an ffmpeg segmenter at these folders, e.g.
      ffmpeg -rtsp_transport tcp -i rtsp://... -c copy -f segment -segment_time 3600 -strftime 1 \
             data/inbox/1/%Y-%m-%d_%H-%M.mp4
    Files still being written (modified in the last 2 minutes) are skipped until the next pass.
    """
    new = []
    for f in sorted(config.INBOX_DIR.rglob("*")):
        if f.suffix.lower() not in VIDEO_EXTS or f.name.startswith("_rec_") or time.time() - f.stat().st_mtime < 120:
            continue
        cam_id = int(f.parent.name) if f.parent != config.INBOX_DIR and f.parent.name.isdigit() else None
        recorded = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
        try:
            new.append(register_video(f, f.stem, camera_id=cam_id, recorded_on=recorded, move=True))
        except Exception:
            log.exception("could not ingest %s", f)
    return new


# ---------- daily job ----------

def daily(report_day: str | None = None, send_email: bool = True) -> dict:
    """Ingest new footage, analyse everything not yet analysed, build the day's report, email it."""
    day = report_day or (date.today() - timedelta(days=1) if config.DAILY_REPORT_DAY == "yesterday"
                         else date.today()).isoformat()
    ingested = ingest_inbox()
    with db.tx() as c:
        pending = [r["id"] for r in c.execute(
            "SELECT id FROM videos WHERE status='new' AND zones != '[]'")]
    analysed = []
    for vid in pending:
        try:
            analyze_video(vid)
            analysed.append(vid)
        except Exception:
            pass
    rep = reports.build(report_date=day, created_by="daily job")
    emailed = False
    if send_email and config.email_configured() and config.MANAGER_EMAILS and rep["rows"]:
        try:
            reports.email(rep, config.MANAGER_EMAILS)
            emailed = True
        except Exception:
            log.exception("emailing daily report failed")
    summary = {"day": day, "ingested": ingested, "analysed": analysed, "report_id": rep["id"],
               "people": rep["totals"]["people"], "emailed": emailed}
    log.info("daily job: %s", summary)
    return summary


def start_scheduler():
    """Run `daily()` every day at WW_DAILY_RUN_AT (HH:MM local) inside the server process."""
    if not config.DAILY_RUN_AT:
        return
    hh, mm = map(int, config.DAILY_RUN_AT.split(":"))

    def loop():
        while True:
            now = datetime.now()
            nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            time.sleep((nxt - now).total_seconds())
            try:
                daily()
            except Exception:
                log.exception("daily job failed")

    threading.Thread(target=loop, daemon=True, name="daily-scheduler").start()
    log.info("daily job scheduled at %s", config.DAILY_RUN_AT)
