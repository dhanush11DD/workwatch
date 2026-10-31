"""Remote GPU worker endpoints (X-Worker-Token = WW_WORKER_TOKEN) and the job queue view for managers."""
from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from .. import config, db, jobs
from ..auth import current_user, manager

router = APIRouter(prefix="/api")


def _worker(x_worker_token: str | None = Header(None)):
    if not config.WORKER_TOKEN or not hmac.compare_digest(config.WORKER_TOKEN, x_worker_token or ""):
        raise HTTPException(401, "Bad worker token")


def _job(jid: int) -> dict:
    with db.tx() as c:
        j = db.row(c.execute("SELECT j.*, v.filename FROM jobs j JOIN videos v ON v.id=j.video_id WHERE j.id=?",
                             (jid,)).fetchone())
    if not j or j["status"] != "analysing":
        raise HTTPException(409, "Job is not running")
    return j


@router.post("/worker/claim", dependencies=[Depends(_worker)])
def claim(body: dict = Body(default={})):
    job = jobs.claim(f"remote:{str(body.get('worker', 'gpu'))[:60]}")
    if not job:
        return None
    with db.tx() as c:
        v = c.execute("SELECT filename FROM videos WHERE id=?", (job["video_id"],)).fetchone()
    return {"id": job["id"], "video_id": job["video_id"], "suffix": Path(v["filename"]).suffix}


@router.get("/worker/jobs/{jid}/video", dependencies=[Depends(_worker)])
def video(jid: int):
    return FileResponse(config.VIDEOS_DIR / _job(jid)["filename"])


@router.post("/worker/jobs/{jid}/progress", dependencies=[Depends(_worker)])
def progress(jid: int, body: dict = Body(...)):
    _job(jid)
    jobs.progress(jid, float(body.get("progress", 0)))
    return {"ok": True}


@router.post("/worker/jobs/{jid}/result", dependencies=[Depends(_worker)])
async def result(jid: int, request: Request):
    _job(jid)
    return {"run_id": jobs.import_result_zip(jid, await request.body())}


@router.post("/worker/jobs/{jid}/fail", dependencies=[Depends(_worker)])
def fail(jid: int, body: dict = Body(default={})):
    _job(jid)
    jobs.fail(jid, str(body.get("error", "remote worker error")))
    return {"ok": True}


@router.get("/jobs")
def job_list(user=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c.execute(
            "SELECT j.id, j.video_id, j.status, j.progress, j.worker, j.attempts, j.error, j.created_at, j.started_at, "
            "j.finished_at, v.name AS video_name, v.duration FROM jobs j JOIN videos v ON v.id=j.video_id "
            "WHERE j.org_id=? ORDER BY j.id DESC LIMIT 100", (user["org_id"],)))


@router.post("/jobs/{jid}/retry")
def retry(jid: int, user=Depends(manager)):
    with db.tx() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=? AND org_id=?", (jid, user["org_id"])).fetchone()
        if not j or j["status"] != "failed":
            raise HTTPException(400, "Only failed jobs can be retried")
        c.execute("UPDATE jobs SET status='queued', attempts=0, error=NULL, finished_at=NULL WHERE id=?", (jid,))
        db.audit(c, user, "analysis.retry", "video", j["video_id"], None, {"job": jid})
    return {"ok": True}
