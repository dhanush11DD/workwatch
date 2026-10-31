"""Reports: preview with gate blockers, generate (hard gate), list, Excel/PDF/CSV/payroll export, delivery, share links."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response

from .. import db, delivery, reports
from ..auth import current_user, manager

router = APIRouter()


def _filters(body: dict) -> dict:
    keys = ("date_from", "date_to", "site_id", "camera_id", "shift", "worker", "zone", "video_ids", "reviewed_only")
    return {k: body[k] for k in keys if body.get(k) not in (None, "", [])}


def _report(c, user, rid: int) -> dict:
    r = db.row(c.execute("SELECT * FROM reports WHERE id=? AND org_id=?", (rid, user["org_id"])).fetchone())
    if not r:
        raise HTTPException(404, "Report not found")
    return r


@router.post("/api/reports/preview")
def preview(body: dict = Body(default={}), user=Depends(current_user)):
    with db.tx() as c:
        rows, totals, zones, ctx = reports.aggregate(c, user["org_id"], _filters(body))
    return {"rows": rows, "totals": totals, "zones": zones, **ctx}


@router.post("/api/reports")
def create(body: dict = Body(default={}), user=Depends(manager)):
    try:
        rep = reports.build(user["org_id"], _filters(body), user)
    except reports.GateError as e:
        raise HTTPException(409, {"message": str(e), "blockers": e.blockers})
    return {k: rep[k] for k in ("id", "title", "status", "totals", "created_at")}


@router.get("/api/reports")
def list_reports(user=Depends(current_user)):
    with db.tx() as c:
        rs = db.rows(c.execute("SELECT id, title, report_date, date_to, filters, totals, notes, status, created_by, "
                               "created_at FROM reports WHERE org_id=? ORDER BY id DESC LIMIT 200", (user["org_id"],)))
        for r in rs:
            r["deliveries"] = db.rows(c.execute("SELECT channel, status, COUNT(*) AS n FROM deliveries WHERE report_id=? "
                                                "GROUP BY channel, status", (r["id"],)))
    return rs


@router.get("/api/reports/{rid}")
def get_report(rid: int, user=Depends(current_user)):
    with db.tx() as c:
        r = _report(c, user, rid)
        r["deliveries"] = db.rows(c.execute("SELECT * FROM deliveries WHERE report_id=? ORDER BY id DESC", (rid,)))
    return r


@router.get("/api/reports/{rid}/export")
def export(rid: int, fmt: str = "xlsx", payroll: str = "", user=Depends(current_user)):
    if fmt not in ("xlsx", "pdf", "csv", "payroll"):
        raise HTTPException(400, "Format must be xlsx, pdf, csv or payroll")
    if fmt == "payroll" and payroll and payroll not in reports.PAYROLL:
        raise HTTPException(400, f"Payroll format must be one of {', '.join(reports.PAYROLL)}")
    with db.tx() as c:
        rep = _report(c, user, rid)
        db.audit(c, user, "report.download", "report", rid, None, {"format": fmt, "payroll": payroll or None})
    data, name, mime = reports.export(rep, fmt, payroll or None)
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/api/reports/{rid}/deliver")
def deliver(rid: int, body: dict = Body(default={}), user=Depends(manager)):
    with db.tx() as c:
        _report(c, user, rid)
    channels = [ch for ch in body.get("channels") or ["email", "whatsapp"] if ch in ("email", "whatsapp")]
    return {"results": reports.deliver(rid, user["org_id"], user, channels)}


@router.get("/api/deliveries")
def delivery_log(user=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c.execute(
            "SELECT d.*, r.title FROM deliveries d LEFT JOIN reports r ON r.id=d.report_id WHERE d.org_id=? "
            "ORDER BY d.id DESC LIMIT 300", (user["org_id"],)))


@router.get("/api/payroll-formats")
def payroll_formats(user=Depends(current_user)):
    return list(reports.PAYROLL)


@router.get("/r/{token}")
def shared(token: str):
    """Signed, expiring link used as the WhatsApp document URL (providers fetch it without a session)."""
    p = delivery.verify(token)
    if not p:
        raise HTTPException(404, "This link has expired")
    with db.tx() as c:
        rep = db.row(c.execute("SELECT * FROM reports WHERE id=?", (p["r"],)).fetchone())
    if not rep:
        raise HTTPException(404, "Report not found")
    data, name, mime = reports.export(rep, p.get("f", "pdf"))
    return Response(data, media_type=mime, headers={"Content-Disposition": f'inline; filename="{name}"'})
