"""WorkWatch web API + dashboard.  Run:  python -m workwatch serve"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import cv2
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, db, jobs, pipeline, reports, store
from .auth import current_user, manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    jobs.resume_interrupted()
    jobs.start_scheduler()
    yield


app = FastAPI(title="WorkWatch", lifespan=lifespan)


@app.middleware("http")
async def _no_stale_ui(request: Request, call_next):
    # The dashboard has no build step / hashed filenames, so make browsers revalidate it.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _404(what="Not found"):
    raise HTTPException(404, what)


# ---------- auth ----------

@app.post("/api/auth/signup")
def signup(response: Response, body: dict = Body(...)):
    try:
        u = auth.create_user(body.get("email", ""), body.get("password", ""), body.get("name", ""))
        token = auth.login(body["email"], body["password"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400)
    return u


@app.post("/api/auth/login")
def login(response: Response, body: dict = Body(...)):
    try:
        token = auth.login(body.get("email", ""), body.get("password", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    if t := request.cookies.get(auth.COOKIE):
        auth.logout(t)
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/users")
def list_users(_=Depends(manager)):
    with db.tx() as c:
        return [auth.public(dict(u)) for u in c.execute("SELECT * FROM users ORDER BY id")]


@app.patch("/api/users/{uid}")
def set_role(uid: int, body: dict = Body(...), user=Depends(manager)):
    role = body.get("role")
    if role not in ("manager", "viewer"):
        raise HTTPException(400, "role must be manager or viewer")
    if uid == user["id"] and role != "manager":
        raise HTTPException(400, "You can't remove your own manager role")
    with db.tx() as c:
        c.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
    return {"ok": True}


# ---------- dashboard ----------

@app.get("/api/stats")
def stats(_=Depends(current_user)):
    with db.tx() as c:
        working, people = 0.0, 0
        for rid in db.latest_run_ids(c):
            ps = store.run_people(c, rid)
            people += len(ps)
            working += sum(p["working_s"] for p in ps)
        pending = c.execute("SELECT COUNT(*) FROM segments WHERE review_status='pending' AND run_id IN "
                            "(SELECT MAX(id) FROM runs GROUP BY video_id)").fetchone()[0]
        n_videos = c.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    return {"working_s": working, "people": people, "pending": pending, "videos": n_videos,
            "email_configured": config.email_configured(), "manager_emails": config.MANAGER_EMAILS,
            "daily_run_at": config.DAILY_RUN_AT}


@app.get("/api/people")
def people(_=Depends(current_user)):
    with db.tx() as c:
        rows, totals, _used = reports.aggregate(c)
    return {"rows": rows, "totals": totals}


# ---------- videos ----------

@app.get("/api/videos")
def list_videos(_=Depends(current_user)):
    with db.tx() as c:
        out = []
        for r in c.execute("SELECT id FROM videos ORDER BY is_demo DESC, created_at DESC"):
            v = store.video_with_status(c, r["id"])
            if v["run_id"]:
                ps = store.run_people(c, v["run_id"])
                v["summary"] = {"people": len(ps), "working_s": sum(p["working_s"] for p in ps),
                                "idle_s": sum(p["idle_s"] for p in ps), "pending": sum(p["pending"] for p in ps)}
            out.append(v)
        return out


@app.post("/api/videos")
async def upload_video(file: UploadFile = File(...), name: str = Form(""), recorded_on: str = Form(""),
                       camera_id: str = Form(""), _=Depends(manager)):
    suffix = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if suffix not in jobs.VIDEO_EXTS:
        raise HTTPException(400, f"Unsupported file type {suffix}")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=config.DATA_DIR) as tmp:
        while chunk := await file.read(4 << 20):
            tmp.write(chunk)
    try:
        vid = jobs.register_video(Path(tmp.name), name or Path(file.filename or "video").stem,
                                  camera_id=int(camera_id) if camera_id else None,
                                  recorded_on=recorded_on or None, move=True)
    except ValueError as e:
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    with db.tx() as c:
        return store.video_with_status(c, vid)


@app.get("/api/videos/{vid}")
def get_video(vid: int, _=Depends(current_user)):
    with db.tx() as c:
        return store.video_with_status(c, vid) or _404()


@app.patch("/api/videos/{vid}")
def update_video(vid: int, body: dict = Body(...), _=Depends(manager)):
    with db.tx() as c:
        for key in ("name", "recorded_on"):
            if key in body:
                c.execute(f"UPDATE videos SET {key}=? WHERE id=?", (body[key], vid))
        return store.video_with_status(c, vid) or _404()


@app.delete("/api/videos/{vid}")
def delete_video(vid: int, _=Depends(manager)):
    with db.tx() as c:
        v = c.execute("SELECT filename FROM videos WHERE id=?", (vid,)).fetchone() or _404()
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
    (config.VIDEOS_DIR / v["filename"]).unlink(missing_ok=True)
    return {"ok": True}


def _video_path(vid: int) -> Path:
    with db.tx() as c:
        v = c.execute("SELECT filename FROM videos WHERE id=?", (vid,)).fetchone() or _404()
    return config.VIDEOS_DIR / v["filename"]


@app.get("/api/videos/{vid}/stream")
def stream_video(vid: int, request: Request, _=Depends(current_user)):
    """Serve the file with HTTP range support so the browser can seek to flagged segments."""
    path = _video_path(vid)
    size = path.stat().st_size
    ctype = "video/mp4" if path.suffix in (".mp4", ".m4v", ".mov") else "video/webm"
    rng = request.headers.get("range")
    m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
    if not m:
        return FileResponse(path, media_type=ctype, headers={"Accept-Ranges": "bytes"})
    start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
    end = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
    end = min(end, size - 1)

    def chunks():
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                data = f.read(min(1 << 20, left))
                if not data:
                    break
                left -= len(data)
                yield data

    return StreamingResponse(chunks(), status_code=206, media_type=ctype, headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1)})


def _jpeg(frame) -> Response:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "Could not encode frame")
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/videos/{vid}/frame.jpg")
def video_frame(vid: int, t: float = 0.0, _=Depends(current_user)):
    frame = pipeline.read_frame(str(_video_path(vid)), t)
    if frame is None:
        _404("No frame at that time")
    return _jpeg(frame)


def _check_zones(zones) -> list:
    if not isinstance(zones, list):
        raise HTTPException(400, "zones must be a list")
    out = []
    for z in zones:
        pts = z.get("points") or []
        if z.get("type") not in ("work", "break", "exclusion") or len(pts) < 3:
            raise HTTPException(400, "each zone needs a type (work/break/exclusion) and at least 3 points")
        out.append({"name": str(z.get("name") or "Zone")[:60], "type": z["type"],
                    "points": [[round(float(x), 4), round(float(y), 4)] for x, y in pts]})
    return out


@app.put("/api/videos/{vid}/zones")
def save_zones(vid: int, zones: list = Body(...), _=Depends(manager)):
    zones = _check_zones(zones)
    with db.tx() as c:
        c.execute("UPDATE videos SET zones=? WHERE id=?", (json.dumps(zones), vid))
    return {"ok": True, "zones": zones}


@app.post("/api/videos/{vid}/analyze")
def analyze(vid: int, _=Depends(manager)):
    with db.tx() as c:
        v = db.row(c.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()) or _404()
    if not any(z["type"] == "work" for z in v["zones"]):
        raise HTTPException(400, "Draw at least one work zone before running the pipeline")
    if v["status"] in ("queued", "processing"):
        raise HTTPException(409, "Already in the queue")
    jobs.enqueue(vid)
    return {"ok": True}


@app.post("/api/videos/{vid}/import-results")
async def import_results(vid: int, file: UploadFile = File(...), _=Depends(manager)):
    """Import a results.json produced by `python -m workwatch analyze` on another machine."""
    try:
        result = json.loads(await file.read())
        assert isinstance(result.get("people"), list)
    except Exception:
        raise HTTPException(400, "Not a WorkWatch results file")
    _video_path(vid)
    run_id = store.import_results(vid, result)
    return {"ok": True, "run_id": run_id}


@app.get("/api/videos/{vid}/results")
def results(vid: int, _=Depends(current_user)):
    with db.tx() as c:
        v = store.video_with_status(c, vid) or _404()
        if not v["run_id"]:
            return {"video": v, "run": None, "people": []}
        run = db.row(c.execute("SELECT * FROM runs WHERE id=?", (v["run_id"],)).fetchone())
        return {"video": v, "run": run, "people": store.run_people(c, v["run_id"])}


@app.get("/api/runs/{rid}/tracks")
def run_tracks(rid: int, _=Depends(current_user)):
    p = store.run_dir(rid) / "tracks.json"
    return FileResponse(p, media_type="application/json") if p.exists() else JSONResponse({})


@app.get("/api/runs/{rid}/thumbs/{name}")
def run_thumb(rid: int, name: str, _=Depends(current_user)):
    p = store.run_dir(rid) / "thumbs" / Path(name).name
    return FileResponse(p) if p.exists() else _404()


@app.patch("/api/persons/{pid}")
def rename_person(pid: int, body: dict = Body(...), _=Depends(manager)):
    label = (body.get("label") or "").strip()[:60]
    if not label:
        raise HTTPException(400, "Name can't be empty")
    with db.tx() as c:
        c.execute("UPDATE persons SET label=? WHERE id=?", (label, pid))
    return {"ok": True}


@app.post("/api/persons/{pid}/merge")
def merge_person(pid: int, body: dict = Body(...), _=Depends(manager)):
    """Fold one track into another (same person got two ids after an occlusion)."""
    into = int(body.get("into", 0))
    with db.tx() as c:
        a = c.execute("SELECT run_id FROM persons WHERE id=?", (pid,)).fetchone() or _404()
        b = c.execute("SELECT run_id FROM persons WHERE id=?", (into,)).fetchone() or _404()
        if pid == into or a["run_id"] != b["run_id"]:
            raise HTTPException(400, "Pick another person from the same video")
        c.execute("UPDATE persons SET merged_into=? WHERE id=?", (into, pid))
    return {"ok": True}


@app.post("/api/persons/{pid}/unmerge")
def unmerge_person(pid: int, _=Depends(manager)):
    with db.tx() as c:
        c.execute("UPDATE persons SET merged_into=NULL WHERE id=?", (pid,))
    return {"ok": True}


# ---------- review ----------

@app.get("/api/review")
def review_queue(status: str = "pending", _=Depends(current_user)):
    with db.tx() as c:
        q = ('SELECT s.*, p.label, p.thumb, p.track_id, r.video_id, v.name AS video_name '
             "FROM segments s JOIN persons p ON p.id=s.person_id JOIN runs r ON r.id=s.run_id "
             "JOIN videos v ON v.id=r.video_id WHERE s.run_id IN (SELECT MAX(id) FROM runs GROUP BY video_id) ")
        if status == "pending":
            q += "AND s.review_status='pending' ORDER BY v.id, s.start"
        else:
            q += "AND s.review_status IN ('confirmed','corrected') ORDER BY s.reviewed_at DESC LIMIT 100"
        return db.rows(c.execute(q))


@app.post("/api/segments/{sid}/review")
def review_segment(sid: int, body: dict = Body(...), user=Depends(manager)):
    action = body.get("action")
    with db.tx() as c:
        s = c.execute("SELECT * FROM segments WHERE id=?", (sid,)).fetchone() or _404()
        if action == "confirm":
            c.execute("UPDATE segments SET review_status='confirmed', reviewed_state=NULL, reviewed_by=?, "
                      "reviewed_at=? WHERE id=?", (user["email"], db.now(), sid))
        elif action == "set_state" and body.get("state") in ("working", "idle"):
            st = body["state"]
            status = "confirmed" if st == s["state"] else "corrected"
            c.execute("UPDATE segments SET review_status=?, reviewed_state=?, reviewed_by=?, reviewed_at=? "
                      "WHERE id=?", (status, st if status == "corrected" else None, user["email"], db.now(), sid))
        elif action == "reopen":
            c.execute("UPDATE segments SET review_status='pending', reviewed_state=NULL, reviewed_by=NULL, "
                      "reviewed_at=NULL WHERE id=?", (sid,))
        else:
            raise HTTPException(400, "action must be confirm, set_state (working|idle) or reopen")
    return {"ok": True}


# ---------- cameras ----------

@app.get("/api/cameras")
def list_cameras(_=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c.execute("SELECT * FROM cameras ORDER BY id"))


@app.post("/api/cameras")
def add_camera(body: dict = Body(...), _=Depends(manager)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Give the camera a name")
    with db.tx() as c:
        cid = c.execute("INSERT INTO cameras (name, rtsp_url, created_at) VALUES (?,?,?)",
                        (name, (body.get("rtsp_url") or "").strip(), db.now())).lastrowid
        (config.INBOX_DIR / str(cid)).mkdir(exist_ok=True)
        return db.row(c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone())


@app.patch("/api/cameras/{cid}")
def update_camera(cid: int, body: dict = Body(...), _=Depends(manager)):
    with db.tx() as c:
        if "name" in body:
            c.execute("UPDATE cameras SET name=? WHERE id=?", (body["name"], cid))
        if "rtsp_url" in body:
            c.execute("UPDATE cameras SET rtsp_url=? WHERE id=?", (body["rtsp_url"], cid))
        if "zones" in body:
            c.execute("UPDATE cameras SET zones=? WHERE id=?", (json.dumps(_check_zones(body["zones"])), cid))
        return db.row(c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()) or _404()


@app.delete("/api/cameras/{cid}")
def delete_camera(cid: int, _=Depends(manager)):
    with db.tx() as c:
        c.execute("DELETE FROM cameras WHERE id=?", (cid,))
    return {"ok": True}


@app.get("/api/cameras/{cid}/snapshot.jpg")
def camera_snapshot(cid: int, _=Depends(current_user)):
    with db.tx() as c:
        cam = c.execute("SELECT rtsp_url FROM cameras WHERE id=?", (cid,)).fetchone() or _404()
    try:
        return _jpeg(jobs.snapshot(cam["rtsp_url"]))
    except Exception as e:
        raise HTTPException(502, str(e))


@app.post("/api/cameras/{cid}/record")
def camera_record(cid: int, body: dict = Body(...), _=Depends(manager)):
    import threading
    minutes = float(body.get("minutes", 5))
    if not 0 < minutes <= 24 * 60:
        raise HTTPException(400, "minutes must be between 0 and 1440")
    analyze_after = bool(body.get("analyze", True))

    def go():
        vid = jobs.record_camera(cid, minutes)
        with db.tx() as c:
            z = c.execute("SELECT zones FROM videos WHERE id=?", (vid,)).fetchone()["zones"]
        if analyze_after and z != "[]":
            jobs.enqueue(vid)

    threading.Thread(target=go, daemon=True).start()
    return {"ok": True, "message": f"Recording {minutes:g} min; the clip appears in Videos when done."}


# ---------- reports ----------

@app.get("/api/reports")
def list_reports(_=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 100"))


@app.post("/api/reports")
def create_report(body: dict = Body(...), user=Depends(manager)):
    rep = reports.build(video_ids=body.get("video_ids") or None,
                        report_date=body.get("date") or None, created_by=user["email"])
    if not rep["rows"]:
        with db.tx() as c:
            c.execute("DELETE FROM reports WHERE id=?", (rep["id"],))
        Path(rep["csv_path"]).unlink(missing_ok=True)
        raise HTTPException(400, "No analysed footage for that selection")
    return rep


@app.get("/api/reports/{rid}/csv")
def report_csv(rid: int, _=Depends(current_user)):
    with db.tx() as c:
        r = c.execute("SELECT csv_path FROM reports WHERE id=?", (rid,)).fetchone() or _404()
    return FileResponse(r["csv_path"], media_type="text/csv", filename=Path(r["csv_path"]).name)


@app.post("/api/reports/{rid}/email")
def report_email(rid: int, body: dict = Body(default={}), user=Depends(manager)):
    with db.tx() as c:
        rep = db.row(c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()) or _404()
    to = body.get("to") or config.MANAGER_EMAILS or [user["email"]]
    try:
        reports.email(rep, to if isinstance(to, list) else [to])
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "to": to}


@app.delete("/api/reports/{rid}")
def delete_report(rid: int, _=Depends(manager)):
    with db.tx() as c:
        r = c.execute("SELECT csv_path FROM reports WHERE id=?", (rid,)).fetchone() or _404()
        c.execute("DELETE FROM reports WHERE id=?", (rid,))
    Path(r["csv_path"]).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/daily/run")
def run_daily(body: dict = Body(default={}), _=Depends(manager)):
    import threading
    day = body.get("date") or date.today().isoformat()
    threading.Thread(target=jobs.daily, kwargs={"report_day": day}, daemon=True).start()
    return {"ok": True, "message": f"Daily job started for {day}"}


# ---------- static dashboard ----------

app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
