"""Helpers shared by the API routers. Every lookup takes the caller's org_id — the tenant boundary."""
from __future__ import annotations

import cv2
from fastapi import HTTPException, Response

from .. import db, store


def not_found(what: str = "Not found"):
    raise HTTPException(404, what)


def video_or_404(c, user: dict, vid: int) -> dict:
    v = db.row(c.execute("SELECT * FROM videos WHERE id=? AND org_id=?", (vid, user["org_id"])).fetchone())
    if not v:
        not_found("Video not found")
    if user["site_ids"] and v["site_id"] and v["site_id"] not in user["site_ids"]:
        not_found("Video not found")
    return v


def run_or_404(c, user: dict, run_id: int) -> dict:
    r = db.row(c.execute("SELECT * FROM runs WHERE id=? AND org_id=?", (run_id, user["org_id"])).fetchone())
    return r or not_found("Run not found")


def person_or_404(c, user: dict, pid: int) -> dict:
    p = db.row(c.execute("SELECT p.*, r.video_id FROM persons p JOIN runs r ON r.id=p.run_id "
                         "WHERE p.id=? AND r.org_id=?", (pid, user["org_id"])).fetchone())
    return p or not_found("Person not found")


def jpeg(img, cache: bool = True) -> Response:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "Could not encode image")
    return Response(buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=600" if cache else "no-store"})


def boxes_at(run_id: int, t: float, W: int, H: int) -> list:
    raw = store.raw(run_id)
    out = []
    for samples in raw["tracks"].values():
        if not samples or t < samples[0][0] - 0.5 or t > samples[-1][0] + 0.5:
            continue
        s = min(samples, key=lambda r: abs(r[0] - t))
        if abs(s[0] - t) <= 0.5:
            out.append((s[1] * W, s[2] * H, s[3] * W, s[4] * H))
    return out
