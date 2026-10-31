"""Cameras (zone templates, shifts, RTSP), edge-agent pairing/heartbeat, camera health."""
from __future__ import annotations

import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

import cv2
from fastapi import APIRouter, Body, Depends, Header, HTTPException

from .. import config, db, jobs
from ..auth import current_user, manager, site_filter
from .common import jpeg
from .org_api import _check_quota
from .videos_api import _check_zones

router = APIRouter(prefix="/api")
OFFLINE_S = 600


def health(cam: dict) -> str:
    if not cam.get("agent_last_seen") and not cam.get("rtsp_url"):
        return "not_connected"
    if cam.get("agent_last_seen"):
        return "online" if time.time() - cam["agent_last_seen"] < OFFLINE_S else "offline"
    return "rtsp"


def _view(cam: dict, show_token=False) -> dict:
    cam = dict(cam)
    cam["health"] = health(cam)
    cam["paired"] = bool(cam.get("agent_token"))
    if not show_token:
        cam.pop("agent_token", None)
    if cam.get("rtsp_url"):  # never echo stored passwords
        cam["rtsp_url"] = _mask(cam["rtsp_url"])
    return cam


def _mask(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        return f"{scheme}://{creds.split(':')[0]}:••••@{host}"
    return url


def _cam(c, user, cid) -> dict:
    cam = db.row(c.execute("SELECT * FROM cameras WHERE id=? AND org_id=?", (cid, user["org_id"])).fetchone())
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@router.get("/cameras")
def list_cameras(user=Depends(current_user)):
    frag, args = site_filter(user, "c")
    with db.tx() as c:
        cams = db.rows(c.execute(
            "SELECT c.*, s.name AS site_name, (SELECT COUNT(*) FROM videos v WHERE v.camera_id=c.id) AS clips "
            "FROM cameras c LEFT JOIN sites s ON s.id=c.site_id WHERE c.org_id=?" + frag + " ORDER BY c.id",
            (user["org_id"], *args)))
    return [_view(cam) for cam in cams]


def _clean(body: dict) -> dict:
    out = {k: (body[k].strip() if isinstance(body[k], str) else body[k])
           for k in ("name", "location", "brand", "rtsp_url", "onvif", "site_id", "auto_slice") if k in body}
    if out.get("rtsp_url") and "••••" in out["rtsp_url"]:
        out.pop("rtsp_url")  # masked value sent back unchanged
    if "shifts" in body:
        for s in body["shifts"]:
            if not (s.get("name") and len(s.get("start", "")) == 5 and len(s.get("end", "")) == 5):
                raise HTTPException(400, "Each shift needs a name, start and end (HH:MM)")
        out["shifts"] = db.dumps(body["shifts"])
    if "zones" in body:
        out["zones"] = db.dumps(_check_zones(body["zones"]))
    return out


@router.post("/cameras")
def add_camera(body: dict = Body(...), user=Depends(manager)):
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "Camera name is required")
    with db.tx() as c:
        _check_quota(c, user["org_id"], "cameras")
        fields = _clean(body)
        fields.setdefault("site_id", c.execute("SELECT id FROM sites WHERE org_id=? ORDER BY id LIMIT 1",
                                               (user["org_id"],)).fetchone()["id"])
        cols = ", ".join(fields)
        cid = c.execute(f"INSERT INTO cameras (org_id, {cols}, created_at) VALUES (?, {', '.join('?' * len(fields))}, ?)",
                        (user["org_id"], *fields.values(), db.now())).lastrowid
        db.audit(c, user, "camera.create", "camera", cid, None, {k: v for k, v in fields.items() if k != "rtsp_url"})
        return _view(_cam(c, user, cid))


@router.patch("/cameras/{cid}")
def update_camera(cid: int, body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        before = _cam(c, user, cid)
        fields = _clean(body)
        for k, v in fields.items():
            c.execute(f"UPDATE cameras SET {k}=? WHERE id=?", (v, cid))
        db.audit(c, user, "camera.update", "camera", cid, {k: before[k] for k in fields if k != "rtsp_url"},
                 {k: v for k, v in fields.items() if k != "rtsp_url"})
        return _view(_cam(c, user, cid))


@router.delete("/cameras/{cid}")
def delete_camera(cid: int, user=Depends(manager)):
    with db.tx() as c:
        cam = _cam(c, user, cid)
        c.execute("DELETE FROM cameras WHERE id=?", (cid,))
        db.audit(c, user, "camera.delete", "camera", cid, {"name": cam["name"]}, None)
    return {"ok": True}


@router.post("/cameras/{cid}/pair")
def pair_agent(cid: int, user=Depends(manager)):
    """Issue (or rotate) the edge agent token for this camera. Shown once."""
    token = "wwa_" + secrets.token_urlsafe(24)
    with db.tx() as c:
        _cam(c, user, cid)
        c.execute("UPDATE cameras SET agent_token=?, offline_notified=0 WHERE id=?", (token, cid))
        db.audit(c, user, "camera.pair_agent", "camera", cid)
    return {"token": token, "server": config.PUBLIC_URL,
            "command": f"python edge_agent/agent.py --server {config.PUBLIC_URL} --token {token}"}


def _rtsp(cam: dict) -> str:
    if not cam.get("rtsp_url"):
        raise HTTPException(400, "No RTSP URL set for this camera")
    return cam["rtsp_url"]


@router.get("/cameras/{cid}/snapshot.jpg")
def snapshot(cid: int, user=Depends(manager)):
    with db.tx() as c:
        cam = _cam(c, user, cid)
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
    cap = cv2.VideoCapture(_rtsp(cam))
    ok, img = cap.read() if cap.isOpened() else (False, None)
    cap.release()
    if not ok:
        raise HTTPException(502, "Could not read a frame from the camera — check the URL, credentials and network")
    return jpeg(img, cache=False)


@router.post("/cameras/{cid}/record")
def record(cid: int, body: dict = Body(default={}), user=Depends(manager)):
    """Server-side capture of N minutes from RTSP into a new clip (for quick tests; use the edge agent for shifts)."""
    minutes = max(0.25, min(float(body.get("minutes", 1)), 60))
    with db.tx() as c:
        cam = _cam(c, user, cid)
    url = _rtsp(cam)

    def run():
        cap = cv2.VideoCapture(url)
        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        tmp = Path(tempfile.mkdtemp(dir=config.DATA_DIR)) / f"cam{cid}.mp4"
        out = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        end, dropped = time.time() + minutes * 60, 0
        while time.time() < end:
            ok, f = cap.read()
            if not ok:
                dropped += 1
                if dropped > 50:
                    break
                time.sleep(0.2)
                continue
            out.write(f)
        cap.release()
        out.release()
        if tmp.exists() and tmp.stat().st_size > 10_000:
            jobs.register_video(cam["org_id"], tmp, f"{cam['name']} · {time.strftime('%d %b %H:%M')}", camera_id=cid,
                                source="camera", partial=dropped > 50,
                                gap_note="Feed dropped during capture" if dropped > 50 else None, created_by=user["id"])

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "minutes": minutes}


# ---------- edge agent (X-Agent-Token) ----------

def _agent(token: str | None) -> dict:
    with db.tx() as c:
        cam = db.row(c.execute("SELECT * FROM cameras WHERE agent_token=?", (token or "",)).fetchone())
    if not cam or not token:
        raise HTTPException(401, "Unknown agent token")
    return cam


@router.post("/agent/heartbeat")
def heartbeat(body: dict = Body(default={}), x_agent_token: str | None = Header(None)):
    cam = _agent(x_agent_token)
    with db.tx() as c:
        c.execute("UPDATE cameras SET agent_last_seen=?, agent_version=?, offline_notified=0 WHERE id=?",
                  (db.now(), str(body.get("version", ""))[:20], cam["id"]))
        tz = c.execute("SELECT timezone FROM organizations WHERE id=?", (cam["org_id"],)).fetchone()["timezone"]
    return {"camera_id": cam["id"], "name": cam["name"], "rtsp_url": cam["rtsp_url"], "shifts": cam["shifts"],
            "auto_slice": bool(cam["auto_slice"]), "timezone": tz, "upload_url": "/api/tus/"}
