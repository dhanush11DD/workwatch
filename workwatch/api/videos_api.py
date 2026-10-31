"""Footage: TUS resumable uploads, catalog, playback, zones, annotation, analysis jobs, pipeline kit."""
from __future__ import annotations

import base64
import io
import json
import re
import secrets
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import cv2
from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import config, db, jobs, pipeline, settings, store
from ..auth import current_user, manager, site_filter
from .common import boxes_at, jpeg, not_found, person_or_404, run_or_404, video_or_404

router = APIRouter()
UPLOADS = config.DATA_DIR / "uploads"
UPLOADS.mkdir(exist_ok=True)
MAX_UPLOAD = 50 * 1024 ** 3  # 50 GB
TUS_HEADERS = {"Tus-Resumable": "1.0.0", "Tus-Version": "1.0.0", "Tus-Extension": "creation,termination",
               "Tus-Max-Size": str(MAX_UPLOAD)}


def _check_zones(zones) -> list:
    if not isinstance(zones, list):
        raise HTTPException(400, "zones must be a list")
    out = []
    for z in zones:
        pts = z.get("points") or []
        if z.get("type") not in ("work", "break", "exclusion") or len(pts) < 3:
            raise HTTPException(400, "Each zone needs a type (work/break/exclusion) and at least 3 points")
        out.append({"name": str(z.get("name") or "Zone")[:60], "type": z["type"],
                    "color": z.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(z.get("color", ""))) else None,
                    "points": [[round(min(1, max(0, float(x))), 4), round(min(1, max(0, float(y))), 4)] for x, y in pts]})
    return out


# ---------- TUS resumable upload (also used by the edge agent with X-Agent-Token) ----------

def _uploader(request: Request) -> dict:
    tok = request.headers.get("x-agent-token")
    if tok:
        with db.tx() as c:
            cam = c.execute("SELECT * FROM cameras WHERE agent_token=?", (tok,)).fetchone()
        if not cam:
            raise HTTPException(401, "Unknown agent token")
        return {"org_id": cam["org_id"], "id": None, "agent_camera": cam["id"], "email": f"agent:{cam['name']}",
                "role": "agent", "site_ids": []}
    return manager(current_user(request))


def _meta(header: str) -> dict:
    out = {}
    for part in (header or "").split(","):
        k, _, v = part.strip().partition(" ")
        if k:
            out[k] = base64.b64decode(v).decode() if v else ""
    return out


@router.options("/api/tus/{path:path}")
def tus_options(path: str = ""):
    return Response(status_code=204, headers=TUS_HEADERS)


@router.post("/api/tus/")
def tus_create(request: Request):
    user = _uploader(request)
    length = int(request.headers.get("upload-length", "0"))
    if not 0 < length <= MAX_UPLOAD:
        raise HTTPException(413, "File too large or empty")
    meta = _meta(request.headers.get("upload-metadata", ""))
    if Path(meta.get("filename", "x.mp4")).suffix.lower() not in jobs.VIDEO_EXTS:
        raise HTTPException(400, "Unsupported file type — upload MP4, MOV, MKV, AVI or TS")
    if user.get("agent_camera"):
        meta["camera_id"], meta["source"] = str(user["agent_camera"]), "camera"
    uid = secrets.token_hex(12)
    (UPLOADS / f"{uid}.part").touch()
    with db.tx() as c:
        c.execute("INSERT INTO uploads (id, org_id, user_id, length, metadata, created_at) VALUES (?,?,?,?,?,?)",
                  (uid, user["org_id"], user["id"], length, db.dumps(meta), db.now()))
    return Response(status_code=201, headers={**TUS_HEADERS, "Location": f"/api/tus/{uid}", "Upload-Offset": "0"})


def _upload(c, uid: str, user: dict) -> dict:
    u = db.row(c.execute("SELECT * FROM uploads WHERE id=? AND org_id=?", (uid, user["org_id"])).fetchone())
    if not u:
        raise HTTPException(404, "Upload not found", headers=TUS_HEADERS)
    return u


@router.head("/api/tus/{uid}")
def tus_head(uid: str, request: Request):
    user = _uploader(request)
    with db.tx() as c:
        u = _upload(c, uid, user)
    return Response(headers={**TUS_HEADERS, "Upload-Offset": str(u["offset"]), "Upload-Length": str(u["length"]),
                             "Cache-Control": "no-store"})


@router.patch("/api/tus/{uid}")
async def tus_patch(uid: str, request: Request):
    user = _uploader(request)
    with db.tx() as c:
        u = _upload(c, uid, user)
    offset = int(request.headers.get("upload-offset", "-1"))
    if offset != u["offset"]:
        raise HTTPException(409, "Offset mismatch", headers=TUS_HEADERS)
    path = UPLOADS / f"{uid}.part"
    written = 0
    try:
        with open(path, "r+b") as f:
            f.seek(offset)
            f.truncate()
            async for chunk in request.stream():
                if offset + written + len(chunk) > u["length"]:
                    raise HTTPException(413, "More data than declared", headers=TUS_HEADERS)
                f.write(chunk)
                written += len(chunk)
    finally:
        # Keep whatever arrived so the client can resume after a dropped connection.
        with db.tx() as c:
            c.execute("UPDATE uploads SET offset=? WHERE id=?", (offset + written, uid))
    new_offset = offset + written
    if new_offset == u["length"]:
        _finalize(uid, user)
    return Response(status_code=204, headers={**TUS_HEADERS, "Upload-Offset": str(new_offset)})


@router.delete("/api/tus/{uid}")
def tus_delete(uid: str, request: Request):
    user = _uploader(request)
    with db.tx() as c:
        _upload(c, uid, user)
        c.execute("DELETE FROM uploads WHERE id=?", (uid,))
    (UPLOADS / f"{uid}.part").unlink(missing_ok=True)
    return Response(status_code=204, headers=TUS_HEADERS)


def _finalize(uid: str, user: dict):
    with db.tx() as c:
        u = db.row(c.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone())
    m = u["metadata"]
    src = UPLOADS / f"{uid}{Path(m.get('filename', 'video.mp4')).suffix.lower() or '.mp4'}"
    shutil.move(UPLOADS / f"{uid}.part", src)
    partial = m.get("partial") in ("1", "true")
    try:
        vid = jobs.register_video(
            u["org_id"], src, m.get("name") or Path(m.get("filename", "video")).stem,
            camera_id=int(m["camera_id"]) if m.get("camera_id") else None,
            site_id=int(m["site_id"]) if m.get("site_id") else None, shift=m.get("shift") or None,
            recorded_on=m.get("recorded_on") or None, source=m.get("source", "upload"), partial=partial,
            gap_note=m.get("gap_note") or None, created_by=user.get("id"))
    except ValueError as e:
        src.unlink(missing_ok=True)
        raise HTTPException(400, f"Not a readable video: {e}", headers=TUS_HEADERS)
    with db.tx() as c:
        c.execute("UPDATE uploads SET video_id=? WHERE id=?", (vid, uid))
        db.audit(c, user, "video.upload", "video", vid, None, {"name": m.get("name"), "bytes": u["length"],
                                                               "source": m.get("source", "upload")})


@router.get("/api/uploads/{uid}")
def upload_status(uid: str, user=Depends(manager)):
    with db.tx() as c:
        u = _upload(c, uid, user)
    return {"offset": u["offset"], "length": u["length"], "video_id": u["video_id"]}


# ---------- catalog ----------

@router.get("/api/videos")
def list_videos(status: str = "", camera_id: int = 0, site_id: int = 0, q: str = "", user=Depends(current_user)):
    frag, args = site_filter(user)
    sql = "SELECT * FROM videos WHERE org_id=?" + frag
    params = [user["org_id"], *args]
    if camera_id:
        sql += " AND camera_id=?"
        params.append(camera_id)
    if site_id:
        sql += " AND site_id=?"
        params.append(site_id)
    if q:
        sql += " AND name LIKE ?"
        params.append(f"%{q}%")
    with db.tx() as c:
        out = [store.video_view(c, v) for v in db.rows(c.execute(sql + " ORDER BY is_demo DESC, created_at DESC", params))]
    return [v for v in out if not status or v["status"] == status]


@router.get("/api/videos/{vid}")
def get_video(vid: int, user=Depends(current_user)):
    with db.tx() as c:
        return store.video_view(c, video_or_404(c, user, vid))


@router.patch("/api/videos/{vid}")
def update_video(vid: int, body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        changes = {k: body[k] for k in ("name", "recorded_on", "shift", "camera_id", "site_id") if k in body}
        for k, val in changes.items():
            c.execute(f"UPDATE videos SET {k}=? WHERE id=?", (val or None, vid))
        db.audit(c, user, "video.update", "video", vid, {k: v[k] for k in changes}, changes)
        return store.video_view(c, video_or_404(c, user, vid))


@router.delete("/api/videos/{vid}")
def delete_video(vid: int, user=Depends(manager)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        runs = [r["id"] for r in c.execute("SELECT id FROM runs WHERE video_id=?", (vid,))]
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
        db.audit(c, user, "video.delete", "video", vid, {"name": v["name"]}, None)
    (config.VIDEOS_DIR / v["filename"]).unlink(missing_ok=True)
    for r in runs:
        shutil.rmtree(store.run_dir(r), ignore_errors=True)
    return {"ok": True}


def _path(v: dict) -> Path:
    if v["footage_deleted"]:
        raise HTTPException(410, "Footage was deleted by the retention policy")
    return config.VIDEOS_DIR / v["filename"]


@router.get("/api/videos/{vid}/stream")
def stream(vid: int, request: Request, download: int = 0, user=Depends(current_user)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
    path = _path(v)
    size = path.stat().st_size
    ctype = "video/mp4" if path.suffix in (".mp4", ".m4v", ".mov") else "video/x-matroska"
    if download:
        return FileResponse(path, media_type=ctype, filename=f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', v['name'])}{path.suffix}")
    m = re.match(r"bytes=(\d*)-(\d*)", request.headers.get("range") or "")
    if not m:
        return FileResponse(path, media_type=ctype, headers={"Accept-Ranges": "bytes"})
    start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
    end = min(int(m.group(2)) if m.group(1) and m.group(2) else size - 1, size - 1)

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
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)})


def _blur_on(c, org_id) -> bool:
    return settings.get(c, org_id)["privacy"]["face_blur"]


@router.get("/api/videos/{vid}/frame.jpg")
def frame(vid: int, t: float = 0.0, user=Depends(current_user)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        blur = _blur_on(c, user["org_id"])
        run_id = db.latest_run_id(c, vid)
    if v["footage_deleted"]:
        run = run_id and store.run_dir(run_id) / "ref.jpg"
        if run and run.exists():
            img = cv2.imread(str(run))
        else:
            raise HTTPException(410, "Footage deleted")
    else:
        img = pipeline.read_frame(str(_path(v)), t)
        if img is None:
            not_found("No frame at that time")
    if blur and run_id:
        img = pipeline.blur_heads(img, boxes_at(run_id, t, img.shape[1], img.shape[0]))
    return jpeg(img, cache=not blur)


@router.get("/api/runs/{rid}/ref.jpg")
def ref_frame(rid: int, user=Depends(current_user)):
    with db.tx() as c:
        run = run_or_404(c, user, rid)
        blur = _blur_on(c, user["org_id"])
    p = store.run_dir(rid) / "ref.jpg"
    if not p.exists():
        not_found()
    img = cv2.imread(str(p))
    if blur and run["ref"]:
        H, W = img.shape[:2]
        img = pipeline.blur_heads(img, [(b["box"][0] * W, b["box"][1] * H, b["box"][2] * W, b["box"][3] * H)
                                        for b in run["ref"]["boxes"]])
    return jpeg(img, cache=False)


@router.get("/api/runs/{rid}/thumbs/{name}")
def thumb(rid: int, name: str, user=Depends(current_user)):
    with db.tx() as c:
        run_or_404(c, user, rid)
        blur = _blur_on(c, user["org_id"])
    p = store.run_dir(rid) / "thumbs" / Path(name).name
    if not p.exists():
        not_found()
    img = cv2.imread(str(p))
    if blur:
        img = pipeline.blur_heads(img, [(0, 0, img.shape[1], img.shape[0])])
    return jpeg(img, cache=False)


@router.get("/api/runs/{rid}/tracks")
def tracks(rid: int, user=Depends(current_user)):
    """Compact per-track boxes + state codes for the player overlay."""
    with db.tx() as c:
        run_or_404(c, user, rid)
        segs = db.rows(c.execute('SELECT p.track_id, s.start, s."end", s.state, s.review_status, s.reviewed_state, '
                                 "p.merged_into FROM segments s JOIN persons p ON p.id=s.person_id WHERE s.run_id=?", (rid,)))
        members = {}
        for p in db.rows(c.execute("SELECT id, track_id, merged_into, removed FROM persons WHERE run_id=?", (rid,))):
            members[p["id"]] = p
    raw = store.raw(rid)
    root_tid = {}
    for p in members.values():
        q = p
        while q["merged_into"] and q["merged_into"] in members:
            q = members[q["merged_into"]]
        root_tid[p["track_id"]] = (q["track_id"], bool(q["removed"]))
    by_root = {}
    for s in segs:
        by_root.setdefault(s["track_id"], []).append((s["start"], s["end"], db.effective_state(s)))
    out = {}
    for tid_s, samples in raw["tracks"].items():
        root, removed = root_tid.get(int(tid_s), (int(tid_s), False))
        spans = by_root.get(root, [])
        rows = []
        for r in samples:
            st = next((x[2] for x in spans if x[0] <= r[0] < x[1] + 0.01), None)
            rows.append([r[0], round(r[1], 4), round(r[2], 4), round(r[3], 4), round(r[4], 4), st, int(r[7] > 0)])
        out[tid_s] = {"root": root, "removed": removed, "s": rows}
    return out


# ---------- zones, analysis, annotation ----------

@router.put("/api/videos/{vid}/zones")
def save_zones(vid: int, body: dict = Body(...), user=Depends(manager)):
    zones = _check_zones(body.get("zones"))
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        c.execute("UPDATE videos SET zones=? WHERE id=?", (db.dumps(zones), vid))
        db.audit(c, user, "zones.update", "video", vid, v["zones"], zones)
        if body.get("save_template") and v["camera_id"]:
            c.execute("UPDATE cameras SET zones=? WHERE id=? AND org_id=?", (db.dumps(zones), v["camera_id"], user["org_id"]))
            db.audit(c, user, "zone_template.update", "camera", v["camera_id"], None, zones)
        store.classify_video(c, vid)
    return {"ok": True, "zones": zones}


@router.post("/api/videos/{vid}/analyze")
def analyze(vid: int, user=Depends(manager)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        _path(v)
        jid = jobs.enqueue(c, vid)
        db.audit(c, user, "analysis.queue", "video", vid, None, {"job": jid})
    return {"ok": True, "job_id": jid}


@router.get("/api/videos/{vid}/results")
def results(vid: int, user=Depends(current_user)):
    with db.tx() as c:
        v = store.video_view(c, video_or_404(c, user, vid))
        if not v["run_id"]:
            return {"video": v, "run": None, "people": []}
        run = db.row(c.execute("SELECT * FROM runs WHERE id=?", (v["run_id"],)).fetchone())
        people = store.run_people(c, v["run_id"])
        workers = db.rows(c.execute("SELECT id, name, employee_id FROM workers WHERE org_id=? AND active=1 ORDER BY name",
                                    (user["org_id"],)))
    return {"video": v, "run": run, "people": people, "workers": workers}


@router.patch("/api/persons/{pid}")
def update_person(pid: int, body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        p = person_or_404(c, user, pid)
        changes = {}
        if "worker_id" in body:
            wid = body["worker_id"]
            if wid:
                w = c.execute("SELECT * FROM workers WHERE id=? AND org_id=?", (wid, user["org_id"])).fetchone()
                if not w:
                    not_found("Worker not found")
                changes.update(worker_id=w["id"], label=f"{w['name']}" + (f" - {w['employee_id']}" if w["employee_id"] else ""))
            else:
                changes["worker_id"] = None
        if body.get("label"):
            changes["label"] = str(body["label"]).strip()[:80]
        if "removed" in body:
            changes["removed"] = int(bool(body["removed"]))
        for k, val in changes.items():
            c.execute(f"UPDATE persons SET {k}=? WHERE id=?", (val, pid))
        db.audit(c, user, "annotation.person", "person", pid, {k: p[k] for k in changes}, changes)
        if "removed" in changes:
            store.classify_video(c, p["video_id"])
    return {"ok": True}


@router.post("/api/persons/{pid}/merge")
def merge(pid: int, body: dict = Body(...), user=Depends(manager)):
    into = int(body.get("into", 0))
    with db.tx() as c:
        a, b = person_or_404(c, user, pid), person_or_404(c, user, into)
        if pid == into or a["run_id"] != b["run_id"]:
            raise HTTPException(400, "Pick another person from the same video")
        c.execute("UPDATE persons SET merged_into=? WHERE id=?", (into, pid))
        db.audit(c, user, "annotation.merge", "person", pid, None, {"into": into, "label": b["label"]})
        store.classify_video(c, a["video_id"])
    return {"ok": True}


@router.post("/api/persons/{pid}/unmerge")
def unmerge(pid: int, user=Depends(manager)):
    with db.tx() as c:
        p = person_or_404(c, user, pid)
        c.execute("UPDATE persons SET merged_into=NULL WHERE id=?", (pid,))
        db.audit(c, user, "annotation.unmerge", "person", pid, {"into": p["merged_into"]}, None)
        store.classify_video(c, p["video_id"])
    return {"ok": True}


@router.post("/api/videos/{vid}/annotation/finish")
def finish_annotation(vid: int, user=Depends(manager)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        if not any(z["type"] == "work" for z in v["zones"]):
            raise HTTPException(400, "Draw at least one Work zone before finishing annotation")
        if not db.latest_run_id(c, vid):
            raise HTTPException(400, "Analysis has not finished yet")
        store.classify_video(c, vid)
        c.execute("UPDATE videos SET annotated=1 WHERE id=?", (vid,))
        db.audit(c, user, "annotation.finish", "video", vid)
        return store.video_view(c, video_or_404(c, user, vid))


@router.post("/api/videos/{vid}/annotation/reopen")
def reopen_annotation(vid: int, user=Depends(manager)):
    with db.tx() as c:
        video_or_404(c, user, vid)
        c.execute("UPDATE videos SET annotated=0 WHERE id=?", (vid,))
        db.audit(c, user, "annotation.reopen", "video", vid)
    return {"ok": True}


# ---------- pipeline kit + results import (interim path before the cloud GPU queue) ----------

@router.get("/api/videos/{vid}/kit")
def pipeline_kit(vid: int, user=Depends(manager)):
    with db.tx() as c:
        v = video_or_404(c, user, vid)
        rules = settings.get(c, user["org_id"])["rules"]
    pkg = Path(pipeline.__file__).parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("__init__.py", "pipeline.py", "config.py", "tracker.yaml"):
            z.write(pkg / name, f"workwatch_kit/workwatch/{name}")
        z.writestr("workwatch_kit/zones.json", json.dumps(v["zones"], indent=2))
        z.writestr("workwatch_kit/rules.json", json.dumps(rules, indent=2))
        z.writestr("workwatch_kit/requirements.txt", "ultralytics>=8.3\nlap>=0.5.12\nopencv-python-headless>=4.9\nnumpy\n")
        z.writestr("workwatch_kit/analyze_video.py", KIT_SCRIPT)
        z.writestr("workwatch_kit/README.txt", KIT_README.format(name=v["name"]))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="workwatch_kit_video{vid}.zip"'})


@router.post("/api/videos/{vid}/import-results")
async def import_results(vid: int, file: UploadFile = File(...), user=Depends(manager)):
    data = await file.read()
    with db.tx() as c:
        video_or_404(c, user, vid)
    tmp = Path(tempfile.mkdtemp(dir=config.DATA_DIR))
    try:
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(n.startswith("/") or ".." in n for n in z.namelist()):
                    raise HTTPException(400, "Bad archive")
                z.extractall(tmp)
            result = json.loads((tmp / "result.json").read_text())
        else:
            result = json.loads(data)
        run_id = store.import_raw(vid, result, thumbs_src=tmp / "thumbs", ref_src=tmp / "ref.jpg")
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Not a WorkWatch results file: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='complete', finished_at=? WHERE video_id=? AND status IN ('queued','failed')",
                  (db.now(), vid))
        db.audit(c, user, "analysis.import", "video", vid, None, {"run": run_id})
    return {"ok": True, "run_id": run_id}


KIT_SCRIPT = '''"""Run the WorkWatch pipeline locally and produce results.zip to import on the video page.

    pip install -r requirements.txt
    python analyze_video.py footage.mp4            # add --device cuda:0 on an NVIDIA GPU
"""
import argparse, json, shutil, tempfile, zipfile
from pathlib import Path
from workwatch import pipeline

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("-o", "--out", default="results.zip")
ap.add_argument("--model", default="yolov8s.pt")
ap.add_argument("--device", default="")
a = ap.parse_args()
tmp = Path(tempfile.mkdtemp())
res = pipeline.detect_track(a.video, model_name=a.model, device=a.device, thumbs_dir=str(tmp / "thumbs"),
                            ref_path=str(tmp / "ref.jpg"),
                            progress=lambda p: print(f"\\r{p * 100:5.1f}%", end="", flush=True))
print()
with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("result.json", json.dumps(res))
    for f in (tmp / "thumbs").glob("*.jpg"):
        z.write(f, f"thumbs/{f.name}")
    if (tmp / "ref.jpg").exists():
        z.write(tmp / "ref.jpg", "ref.jpg")
shutil.rmtree(tmp)
zones = json.loads(Path(__file__).with_name("zones.json").read_text())
rules = json.loads(Path(__file__).with_name("rules.json").read_text())
for tid, p in pipeline.classify(res, zones, rules).items():
    print(f"Person {tid}: " + ", ".join(f"{k} {v:.0f}s" for k, v in p["totals"].items() if v))
print(f"wrote {a.out} — import it on the video page ({res['stats']['realtime_x']}x real time)")
'''

KIT_README = """WorkWatch pipeline kit — {name}

1. Python 3.10+:  pip install -r requirements.txt
2. Put the footage next to this file and run:  python analyze_video.py footage.mp4
   (first run downloads the YOLOv8 models; add --device cuda:0 to use an NVIDIA GPU)
3. On the video page click "Import results" and choose results.zip.

zones.json and rules.json are this video's zones and your organization's analysis rules, used only for the
preview printed at the end. Classification is redone in the app after import.
"""
