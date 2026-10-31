"""Review queue: approve, reclassify to any of the five states, notes, bulk approve. Every decision is audited."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db, settings, store
from ..auth import current_user, reviewer, site_filter
from ..pipeline import STATES

router = APIRouter(prefix="/api/review")

BASE = ('SELECT s.*, p.label, p.track_id, p.thumb, p.worker_id, w.name AS worker_name, v.id AS video_id, '
        'v.name AS video_name, v.recorded_on, v.shift, v.camera_id, v.site_id, r.id AS run_id '
        'FROM segments s JOIN persons p ON p.id=s.person_id JOIN runs r ON r.id=s.run_id '
        'JOIN videos v ON v.id=r.video_id LEFT JOIN workers w ON w.id=p.worker_id '
        'WHERE v.org_id=? AND r.id=(SELECT MAX(id) FROM runs WHERE video_id=v.id)')


def _segment(c, user, sid: int) -> dict:
    frag, args = site_filter(user, "v")
    s = db.row(c.execute(BASE + " AND s.id=?" + frag, (user["org_id"], sid, *args)).fetchone())
    if not s:
        raise HTTPException(404, "Review item not found")
    return s


@router.get("")
def queue(status: str = "pending", video_id: int = 0, state: str = "", camera_id: int = 0, reason: str = "",
          user=Depends(current_user)):
    frag, args = site_filter(user, "v")
    sql, params = BASE + frag, [user["org_id"], *args]
    if status == "pending":
        sql += " AND s.review_status='pending' AND v.annotated=1"
    elif status == "awaiting_annotation":
        sql += " AND s.review_status='pending' AND v.annotated=0"
    elif status == "done":
        sql += " AND s.review_status IN ('approved','reclassified')"
    if video_id:
        sql += " AND v.id=?"
        params.append(video_id)
    if state:
        sql += " AND s.state=?"
        params.append(state)
    if camera_id:
        sql += " AND v.camera_id=?"
        params.append(camera_id)
    if reason:
        sql += " AND s.flag_reason LIKE ?"
        params.append(f"%{reason}%")
    with db.tx() as c:
        items = db.rows(c.execute(sql + " ORDER BY v.recorded_on DESC, v.id, s.start LIMIT 1000", params))
        waiting = c.execute(BASE.replace("SELECT s.*, p.label", "SELECT COUNT(*), p.label", 1) + frag +
                            " AND s.review_status='pending' AND v.annotated=0", (user["org_id"], *args)).fetchone()[0]
    for s in items:
        s["effective_state"] = db.effective_state(s)
        s["person"] = s["worker_name"] or s["label"]
    return {"items": items, "awaiting_annotation": waiting}


def _decide(c, user, s: dict, action: str, state: str | None = None, note: str | None = None):
    before = {k: s[k] for k in ("review_status", "reviewed_state", "note")}
    if action == "approve":
        c.execute("UPDATE segments SET review_status='approved', reviewed_state=NULL, reviewed_by=?, reviewed_at=?, "
                  "note=COALESCE(?, note) WHERE id=?", (user["email"] or user["phone"], db.now(), note, s["id"]))
    elif action == "reclassify":
        if state not in STATES:
            raise HTTPException(400, f"State must be one of {', '.join(STATES)}")
        status = "approved" if state == s["state"] else "reclassified"
        c.execute("UPDATE segments SET review_status=?, reviewed_state=?, reviewed_by=?, reviewed_at=?, "
                  "note=COALESCE(?, note) WHERE id=?",
                  (status, None if status == "approved" else state, user["email"] or user["phone"], db.now(), note,
                   s["id"]))
    elif action == "note":
        c.execute("UPDATE segments SET note=? WHERE id=?", (note or "", s["id"]))
    elif action == "reopen":
        c.execute("UPDATE segments SET review_status='pending', reviewed_state=NULL, reviewed_by=NULL, reviewed_at=NULL "
                  "WHERE id=?", (s["id"],))
    else:
        raise HTTPException(400, "Unknown action")
    after = db.row(c.execute("SELECT review_status, reviewed_state, note FROM segments WHERE id=?", (s["id"],)).fetchone())
    db.audit(c, user, f"review.{action}", "segment", s["id"], before,
             {**after, "video": s["video_name"], "person": s["worker_name"] or s["label"],
              "span": [round(s["start"], 1), round(s["end"], 1)], "detected": s["state"]})


@router.post("/{sid:int}")
def decide(sid: int, body: dict = Body(...), user=Depends(reviewer)):
    with db.tx() as c:
        s = _segment(c, user, sid)
        _decide(c, user, s, body.get("action", ""), body.get("state"), body.get("note"))
        s = _segment(c, user, sid)
    s["effective_state"] = db.effective_state(s)
    return s


@router.post("/bulk")
def bulk(body: dict = Body(...), user=Depends(reviewer)):
    """Bulk approve (or reclassify) a list of ids. With `similar`, also every pending item sharing a selected
    item's flag reason and detected state on the same video (if the org allows it)."""
    ids = [int(i) for i in body.get("ids") or []]
    action = body.get("action", "approve")
    if action not in ("approve", "reclassify"):
        raise HTTPException(400, "Bulk supports approve or reclassify")
    with db.tx() as c:
        chosen = [_segment(c, user, i) for i in ids]
        if body.get("similar") and settings.get(c, user["org_id"])["review"]["bulk_similar"]:
            seen = {s["id"] for s in chosen}
            for s in list(chosen):
                for o in db.rows(c.execute(BASE + " AND s.review_status='pending' AND v.id=? AND s.state=? AND "
                                           "COALESCE(s.flag_reason,'')=COALESCE(?, '')",
                                           (user["org_id"], s["video_id"], s["state"], s["flag_reason"]))):
                    if o["id"] not in seen:
                        seen.add(o["id"])
                        chosen.append(o)
        for s in chosen:
            _decide(c, user, s, action, body.get("state"), body.get("note"))
    return {"ok": True, "count": len(chosen)}


@router.get("/{sid}/history")
def history(sid: int, user=Depends(current_user)):
    with db.tx() as c:
        _segment(c, user, sid)
        return db.rows(c.execute("SELECT * FROM audit WHERE org_id=? AND entity='segment' AND entity_id=? ORDER BY id DESC",
                                 (user["org_id"], str(sid))))


@router.get("/summary")
def summary(user=Depends(current_user)):
    """Gate banner numbers: pending per video."""
    frag, args = site_filter(user, "v")
    with db.tx() as c:
        return db.rows(c.execute(
            "SELECT v.id, v.name, v.recorded_on, COUNT(*) AS pending FROM segments s JOIN runs r ON r.id=s.run_id "
            "JOIN videos v ON v.id=r.video_id WHERE v.org_id=? AND v.annotated=1 AND s.review_status='pending' "
            "AND r.id=(SELECT MAX(id) FROM runs WHERE video_id=v.id)" + frag + " GROUP BY v.id ORDER BY v.recorded_on DESC",
            (user["org_id"], *args)))
