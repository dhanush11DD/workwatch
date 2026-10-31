"""Organization, sites, team & invites, worker list, settings tabs, notifications, privacy (DPDP), audit trail,
billing & usage, and the danger zone. Access follows the settings access matrix: managers edit, reviewers read
the parts they need."""
from __future__ import annotations

import base64
import csv
import io
import json
import secrets
import shutil
import urllib.request
import zipfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, File, HTTPException, Response, UploadFile

from .. import config, db, delivery, settings, store
from ..auth import current_user, manager

router = APIRouter(prefix="/api")

PLANS = {
    "starter": {"name": "Starter", "price": 2999, "cameras": 2, "hours": 200, "users": 3,
                "features": ["2 cameras", "200 analysed hours / month", "Email + WhatsApp reports", "30-day retention"]},
    "growth": {"name": "Growth", "price": 7999, "cameras": 8, "hours": 1000, "users": 10,
               "features": ["8 cameras", "1,000 analysed hours / month", "Payroll exports", "Multiple sites"]},
    "business": {"name": "Business", "price": 19999, "cameras": 25, "hours": 4000, "users": 50,
                 "features": ["25 cameras", "4,000 analysed hours / month", "Priority GPU queue", "90-day retention"]},
}
GST_RATE = 0.18


def _org(c, org_id) -> dict:
    return db.row(c.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone())


# ---------- organization & sites ----------

@router.get("/org")
def get_org(user=Depends(current_user)):
    with db.tx() as c:
        o = _org(c, user["org_id"])
        o.pop("settings", None)
        o["sites"] = db.rows(c.execute("SELECT * FROM sites WHERE org_id=? ORDER BY archived, id", (user["org_id"],)))
    o["data_region"] = config.DATA_REGION
    return o


@router.patch("/org")
def update_org(body: dict = Body(...), user=Depends(manager)):
    fields = ("name", "industry", "address", "logo", "gstin", "pan", "billing_address", "timezone", "date_format",
              "week_start")
    changes = {k: body[k] for k in fields if k in body}
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except Exception:
            raise HTTPException(400, "Unknown timezone")
    if changes.get("logo") and len(changes["logo"]) > 400_000:
        raise HTTPException(400, "Logo must be under 300 KB")
    if changes.get("gstin") and len(changes["gstin"].strip()) != 15:
        raise HTTPException(400, "GSTIN has 15 characters")
    with db.tx() as c:
        before = {k: v for k, v in _org(c, user["org_id"]).items() if k in changes and k != "logo"}
        for k, v in changes.items():
            c.execute(f"UPDATE organizations SET {k}=? WHERE id=?", (v.strip() if isinstance(v, str) else v, user["org_id"]))
        db.audit(c, user, "org.update", "organization", user["org_id"], before,
                 {k: v for k, v in changes.items() if k != "logo"})
    return get_org(user)


@router.post("/sites")
def add_site(body: dict = Body(...), user=Depends(manager)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Site name is required")
    with db.tx() as c:
        sid = c.execute("INSERT INTO sites (org_id, name, created_at) VALUES (?,?,?)", (user["org_id"], name, db.now())).lastrowid
        db.audit(c, user, "site.create", "site", sid, None, {"name": name})
    return {"id": sid}


@router.patch("/sites/{sid}")
def update_site(sid: int, body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        s = db.row(c.execute("SELECT * FROM sites WHERE id=? AND org_id=?", (sid, user["org_id"])).fetchone())
        if not s:
            raise HTTPException(404, "Site not found")
        changes = {}
        if "name" in body:
            changes["name"] = body["name"].strip()
        if "archived" in body:
            changes["archived"] = int(bool(body["archived"]))
        for k in ("weekly_off", "holidays"):
            if k in body:
                changes[k] = db.dumps(body[k])
        for k, v in changes.items():
            c.execute(f"UPDATE sites SET {k}=? WHERE id=?", (v, sid))
        db.audit(c, user, "site.update", "site", sid, {k: s[k] for k in changes}, body)
    return {"ok": True}


# ---------- team & invites ----------

@router.get("/team")
def team(user=Depends(current_user)):
    with db.tx() as c:
        users = db.rows(c.execute("SELECT id, name, email, phone, role, status, site_ids, created_at, "
                                  "(SELECT MAX(last_seen) FROM sessions WHERE user_id=users.id) AS last_active "
                                  "FROM users WHERE org_id=? AND status='active' ORDER BY role, name", (user["org_id"],)))
        invites = db.rows(c.execute("SELECT token, email, role, site_ids, created_at FROM invites WHERE org_id=? AND "
                                    "revoked=0 AND accepted_at IS NULL ORDER BY created_at DESC", (user["org_id"],)))
    if user["role"] != "manager":
        invites = []
    for i in invites:
        i["link"] = f"{config.PUBLIC_URL}/#/invite/{i['token']}"
    return {"users": users, "invites": invites}


@router.post("/team/invites")
def invite(body: dict = Body(...), user=Depends(manager)):
    email = (body.get("email") or "").strip().lower()
    role = body.get("role", "reviewer")
    if "@" not in email or role not in ("manager", "reviewer"):
        raise HTTPException(400, "Enter an email and a role (manager or reviewer)")
    with db.tx() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(400, "That email already has an account")
        _check_quota(c, user["org_id"], "users")
        token = secrets.token_urlsafe(24)
        c.execute("INSERT INTO invites (token, org_id, email, role, site_ids, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                  (token, user["org_id"], email, role, db.dumps(body.get("site_ids") or []), user["id"], db.now()))
        db.audit(c, user, "team.invite", "invite", email, None, {"role": role, "site_ids": body.get("site_ids") or []})
        org = _org(c, user["org_id"])["name"]
    link = f"{config.PUBLIC_URL}/#/invite/{token}"
    emailed = False
    if delivery.email_configured():
        try:
            delivery.send_email([email], f"{user['name']} invited you to {org} on WorkWatch",
                                f"You've been invited to {org} on WorkWatch as a {role}.\n\nAccept: {link}")
            emailed = True
        except Exception:
            pass
    return {"link": link, "emailed": emailed}


@router.delete("/team/invites/{token}")
def revoke_invite(token: str, user=Depends(manager)):
    with db.tx() as c:
        c.execute("UPDATE invites SET revoked=1 WHERE token=? AND org_id=?", (token, user["org_id"]))
        db.audit(c, user, "team.invite_revoke", "invite", token[:8])
    return {"ok": True}


def _member(c, user, uid):
    m = db.row(c.execute("SELECT * FROM users WHERE id=? AND org_id=? AND status='active'", (uid, user["org_id"])).fetchone())
    if not m:
        raise HTTPException(404, "Team member not found")
    return m


def _managers(c, org_id):
    return c.execute("SELECT COUNT(*) FROM users WHERE org_id=? AND role='manager' AND status='active'", (org_id,)).fetchone()[0]


@router.patch("/team/{uid}")
def update_member(uid: int, body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        m = _member(c, user, uid)
        changes = {}
        if body.get("role") in ("manager", "reviewer") and body["role"] != m["role"]:
            if m["role"] == "manager" and _managers(c, user["org_id"]) <= 1:
                raise HTTPException(400, "The organization needs at least one manager")
            changes["role"] = body["role"]
        if "site_ids" in body:
            changes["site_ids"] = db.dumps([int(s) for s in body["site_ids"] or []])
        for k, v in changes.items():
            c.execute(f"UPDATE users SET {k}=? WHERE id=?", (v, uid))
        db.audit(c, user, "team.update", "user", uid, {k: m[k] for k in changes}, body)
    return {"ok": True}


@router.delete("/team/{uid}")
def remove_member(uid: int, user=Depends(manager)):
    with db.tx() as c:
        m = _member(c, user, uid)
        if m["role"] == "manager" and _managers(c, user["org_id"]) <= 1:
            raise HTTPException(400, "The organization needs at least one manager")
        # Keep the row (audit references it) but free the identifiers for reuse.
        c.execute("UPDATE users SET status='removed', email=NULL, phone=NULL, google_sub=NULL, pw_hash=NULL WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        db.audit(c, user, "team.remove", "user", uid, {"name": m["name"], "email": m["email"], "role": m["role"]}, None)
    return {"ok": True}


# ---------- worker list (names used to label tracked people) ----------

@router.get("/workers")
def workers(user=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c.execute(
            "SELECT w.*, s.name AS site_name, (SELECT COUNT(*) FROM persons p WHERE p.worker_id=w.id) AS tagged "
            "FROM workers w LEFT JOIN sites s ON s.id=w.site_id WHERE w.org_id=? ORDER BY w.active DESC, w.name",
            (user["org_id"],)))


def _add_worker(c, user, name, employee_id=None, site_id=None):
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Worker name is required")
    if employee_id and c.execute("SELECT 1 FROM workers WHERE org_id=? AND employee_id=?",
                                 (user["org_id"], employee_id)).fetchone():
        return None
    return c.execute("INSERT INTO workers (org_id, name, employee_id, site_id, created_at) VALUES (?,?,?,?,?)",
                     (user["org_id"], name[:80], (employee_id or "").strip() or None, site_id or None, db.now())).lastrowid


@router.post("/workers")
def add_worker(body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        wid = _add_worker(c, user, body.get("name"), body.get("employee_id"), body.get("site_id"))
        if not wid:
            raise HTTPException(400, "A worker with that employee ID already exists")
        db.audit(c, user, "worker.create", "worker", wid, None, body)
    return {"id": wid}


@router.post("/workers/import")
async def import_workers(file: UploadFile = File(...), user=Depends(manager)):
    """CSV with columns name, employee_id (optional), site (optional site name)."""
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    added = skipped = 0
    with db.tx() as c:
        sites = {s["name"].lower(): s["id"] for s in c.execute("SELECT id, name FROM sites WHERE org_id=?", (user["org_id"],))}
        for r in csv.DictReader(io.StringIO(text)):
            r = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in r.items()}
            name = r.get("name") or r.get("employee_name")
            if not name:
                skipped += 1
                continue
            wid = _add_worker(c, user, name, r.get("employee_id") or r.get("employee_no"),
                              sites.get((r.get("site") or "").lower()))
            added += bool(wid)
            skipped += not wid
        db.audit(c, user, "worker.import", "worker", None, None, {"added": added, "skipped": skipped})
    return {"added": added, "skipped": skipped}


@router.patch("/workers/{wid}")
def update_worker(wid: int, body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        w = db.row(c.execute("SELECT * FROM workers WHERE id=? AND org_id=?", (wid, user["org_id"])).fetchone())
        if not w:
            raise HTTPException(404, "Worker not found")
        changes = {k: body[k] for k in ("name", "employee_id", "site_id", "active") if k in body}
        for k, v in changes.items():
            c.execute(f"UPDATE workers SET {k}=? WHERE id=?", (v if v != "" else None, wid))
        if "name" in changes or "employee_id" in changes:
            w2 = c.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone()
            c.execute("UPDATE persons SET label=? WHERE worker_id=?",
                      (w2["name"] + (f" - {w2['employee_id']}" if w2["employee_id"] else ""), wid))
        db.audit(c, user, "worker.update", "worker", wid, {k: w[k] for k in changes}, changes)
    return {"ok": True}


# ---------- settings tabs ----------

READABLE_BY_REVIEWER = {"rules", "review", "privacy"}


@router.get("/settings")
def get_settings(user=Depends(current_user)):
    with db.tx() as c:
        s = settings.get(c, user["org_id"])
    if user["role"] != "manager":
        s = {k: v for k, v in s.items() if k in READABLE_BY_REVIEWER}
    s["_meta"] = {"events": settings.EVENTS, "columns": settings.REPORT_COLUMNS,
                  "integrations": {"email": delivery.email_configured(), "whatsapp": delivery.whatsapp_configured(),
                                   "whatsapp_provider": config.WHATSAPP_PROVIDER or None, "sms": delivery.sms_configured(),
                                   "google": bool(config.GOOGLE_CLIENT_ID), "razorpay": bool(config.RAZORPAY_KEY_ID),
                                   "worker_token": bool(config.WORKER_TOKEN)},
                  "data_region": config.DATA_REGION}
    return s


def _validate(section: str, v):
    if section == "rules":
        num = {"phone_threshold_s": (5, 600), "phone_gap_s": (0, 30), "idle_threshold_s": (10, 3600),
               "min_segment_s": (0, 60), "review_conf": (0, 1), "short_track_s": (0, 120),
               "motion_threshold": (0.001, 0.2), "move_threshold": (0.01, 2)}
        for k, (lo, hi) in num.items():
            if k in v and not (lo <= float(v[k]) <= hi):
                raise HTTPException(400, f"{k} must be between {lo} and {hi}")
        if v.get("outside_zone_state") and v["outside_zone_state"] not in ("idle", "break", "exclusion", "working"):
            raise HTTPException(400, "Unknown outside-zone state")
    if section == "privacy" and "retention_days" in v:
        v["retention_days"] = int(v["retention_days"])
        if v["retention_days"] not in (30, 60, 90):
            raise HTTPException(400, "Retention is 30, 60 or 90 days")
    if section == "review" and "reminder_hours" in v:
        v["reminder_hours"] = max(0, int(v["reminder_hours"]))
    if section == "delivery":
        for r in v.get("whatsapp_recipients", []):
            r["number"] = delivery.normalise_in(r.get("number", ""))
            if len(r["number"]) < 12:
                raise HTTPException(400, f"Invalid WhatsApp number for {r.get('name') or 'recipient'}")
        if "formats" in v and not set(v["formats"]) <= {"xlsx", "pdf", "csv"}:
            raise HTTPException(400, "Formats are xlsx, pdf and csv")
    return v


@router.put("/settings/{section}")
def put_settings(section: str, body: dict = Body(...), user=Depends(manager)):
    if section not in settings.DEFAULTS:
        raise HTTPException(404, "Unknown settings section")
    values = _validate(section, body.get("values", body))
    with db.tx() as c:
        out = settings.update(c, user["org_id"], section, values, user)
        if section == "rules":
            for v in c.execute("SELECT id FROM videos WHERE org_id=?", (user["org_id"],)).fetchall():
                store.classify_video(c, v["id"])
    return out


@router.post("/settings/{section}/reset")
def reset_settings(section: str, user=Depends(manager)):
    if section not in settings.DEFAULTS:
        raise HTTPException(404, "Unknown settings section")
    with db.tx() as c:
        out = settings.reset(c, user["org_id"], section, user)
        if section == "rules":
            for v in c.execute("SELECT id FROM videos WHERE org_id=?", (user["org_id"],)).fetchall():
                store.classify_video(c, v["id"])
    return out


@router.post("/settings/test/{channel}")
def test_channel(channel: str, body: dict = Body(default={}), user=Depends(manager)):
    try:
        if channel == "email":
            delivery.send_email([body.get("to") or user["email"]], "WorkWatch test email", "Email delivery works.")
        elif channel == "whatsapp":
            delivery.send_whatsapp(body.get("to", ""), "WorkWatch test message: WhatsApp delivery works.")
        else:
            raise HTTPException(400, "Unknown channel")
    except delivery.NotConfigured as e:
        raise HTTPException(400, f"Not configured: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Send failed: {e}")
    return {"ok": True}


# ---------- notifications ----------

@router.get("/notifications")
def notifications(user=Depends(current_user)):
    with db.tx() as c:
        ns = db.rows(c.execute("SELECT * FROM notifications WHERE org_id=? ORDER BY id DESC LIMIT 50", (user["org_id"],)))
    for n in ns:
        n["read"] = user["id"] in n.pop("read_by")
    return {"items": ns, "unread": sum(not n["read"] for n in ns)}


@router.post("/notifications/read")
def mark_read(body: dict = Body(default={}), user=Depends(current_user)):
    ids = body.get("ids")
    with db.tx() as c:
        q = "SELECT id, read_by FROM notifications WHERE org_id=?"
        for n in db.rows(c.execute(q, (user["org_id"],))):
            if (ids is None or n["id"] in ids) and user["id"] not in n["read_by"]:
                c.execute("UPDATE notifications SET read_by=? WHERE id=?", (db.dumps(n["read_by"] + [user["id"]]), n["id"]))
    return {"ok": True}


# ---------- privacy: notices, deletion requests, data export ----------

@router.post("/privacy/notice-issued")
def notice_issued(user=Depends(manager)):
    with db.tx() as c:
        settings.update(c, user["org_id"], "privacy", {"notice_issued_on": date.today().isoformat()}, user)
    return {"ok": True}


@router.get("/privacy/requests")
def deletion_requests(user=Depends(manager)):
    with db.tx() as c:
        return db.rows(c.execute("SELECT * FROM deletion_requests WHERE org_id=? ORDER BY id DESC", (user["org_id"],)))


@router.post("/privacy/requests")
def add_request(body: dict = Body(...), user=Depends(manager)):
    if not body.get("subject"):
        raise HTTPException(400, "Who is the request about?")
    with db.tx() as c:
        rid = c.execute("INSERT INTO deletion_requests (org_id, subject, contact, details, created_at) VALUES (?,?,?,?,?)",
                        (user["org_id"], body["subject"], body.get("contact"), body.get("details"), db.now())).lastrowid
        db.audit(c, user, "privacy.request_create", "deletion_request", rid, None, body)
    return {"id": rid}


@router.patch("/privacy/requests/{rid}")
def update_request(rid: int, body: dict = Body(...), user=Depends(manager)):
    status = body.get("status")
    if status not in ("open", "in_progress", "completed", "rejected"):
        raise HTTPException(400, "Unknown status")
    with db.tx() as c:
        r = db.row(c.execute("SELECT * FROM deletion_requests WHERE id=? AND org_id=?", (rid, user["org_id"])).fetchone())
        if not r:
            raise HTTPException(404, "Request not found")
        c.execute("UPDATE deletion_requests SET status=?, resolution=?, resolved_at=? WHERE id=?",
                  (status, body.get("resolution"), db.now() if status in ("completed", "rejected") else None, rid))
        db.audit(c, user, "privacy.request_update", "deletion_request", rid, {"status": r["status"]},
                 {"status": status, "resolution": body.get("resolution")})
    return {"ok": True}


@router.get("/privacy/export")
def data_export(user=Depends(manager)):
    """Everything WorkWatch holds about this organization except footage files, as JSON in a zip."""
    tables = {"organization": "SELECT * FROM organizations WHERE id=?", "sites": "SELECT * FROM sites WHERE org_id=?",
              "users": "SELECT id, name, email, phone, role, status, site_ids, created_at FROM users WHERE org_id=?",
              "workers": "SELECT * FROM workers WHERE org_id=?", "cameras":
              "SELECT id, site_id, name, location, brand, shifts, zones, created_at FROM cameras WHERE org_id=?",
              "videos": "SELECT * FROM videos WHERE org_id=?",
              "persons": "SELECT p.* FROM persons p JOIN runs r ON r.id=p.run_id WHERE r.org_id=?",
              "segments": "SELECT s.* FROM segments s JOIN runs r ON r.id=s.run_id WHERE r.org_id=?",
              "reports": "SELECT * FROM reports WHERE org_id=?", "deliveries": "SELECT * FROM deliveries WHERE org_id=?",
              "deletion_requests": "SELECT * FROM deletion_requests WHERE org_id=?",
              "audit": "SELECT * FROM audit WHERE org_id=?"}
    buf = io.BytesIO()
    with db.tx() as c, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, q in tables.items():
            z.writestr(f"{name}.json", json.dumps(db.rows(c.execute(q, (user["org_id"],))), indent=1, default=str))
        db.audit(c, user, "privacy.export", "organization", user["org_id"])
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="workwatch_export_{date.today()}.zip"'})


# ---------- audit trail ----------

@router.get("/audit")
def audit_list(q: str = "", action: str = "", limit: int = 200, fmt: str = "", user=Depends(manager)):
    sql, args = "SELECT * FROM audit WHERE org_id=?", [user["org_id"]]
    if action:
        sql += " AND action LIKE ?"
        args.append(f"{action}%")
    if q:
        sql += " AND (user_label LIKE ? OR action LIKE ? OR before LIKE ? OR after LIKE ?)"
        args += [f"%{q}%"] * 4
    with db.tx() as c:
        tz = ZoneInfo(_org(c, user["org_id"])["timezone"])
        items = db.rows(c.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 5000) if not fmt else 100000)))
    if fmt != "csv":
        return items
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Time (IST)", "User", "Action", "Entity", "Entity ID", "Before", "After"])
    for a in items:
        w.writerow([datetime.fromtimestamp(a["created_at"], tz).strftime("%Y-%m-%d %H:%M:%S"), a["user_label"],
                    a["action"], a["entity"], a["entity_id"], json.dumps(a["before"]) if a["before"] else "",
                    json.dumps(a["after"]) if a["after"] else ""])
    return Response(out.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="workwatch_audit.csv"'})


# ---------- billing & usage ----------

def _usage(c, org_id) -> dict:
    month = date.today().replace(day=1)
    start = datetime(month.year, month.month, 1).timestamp()
    hours = c.execute("SELECT COALESCE(SUM(v.duration),0) FROM runs r JOIN videos v ON v.id=r.video_id "
                      "WHERE r.org_id=? AND r.created_at>=? AND v.is_demo=0", (org_id, start)).fetchone()[0] / 3600
    return {"hours": round(hours, 2),
            "cameras": c.execute("SELECT COUNT(*) FROM cameras WHERE org_id=?", (org_id,)).fetchone()[0],
            "users": c.execute("SELECT COUNT(*) FROM users WHERE org_id=? AND status='active'", (org_id,)).fetchone()[0],
            "storage_gb": round(sum((config.VIDEOS_DIR / v["filename"]).stat().st_size
                                    for v in c.execute("SELECT filename FROM videos WHERE org_id=? AND footage_deleted=0",
                                                       (org_id,))
                                    if (config.VIDEOS_DIR / v["filename"]).exists()) / 1024 ** 3, 2),
            "period": month.strftime("%B %Y")}


def _limits(org: dict) -> dict:
    return PLANS.get(org["plan"], PLANS["growth"] if org["plan"] == "trial" else PLANS["starter"])


def _check_quota(c, org_id, key):
    org = _org(c, org_id)
    if _usage(c, org_id)[key] >= _limits(org)[key]:
        raise HTTPException(402, f"Your {PLANS.get(org['plan'], {'name': 'trial'})['name']} plan allows "
                                 f"{_limits(org)[key]} {key}. Upgrade in Settings → Billing.")


@router.get("/billing")
def billing(user=Depends(manager)):
    with db.tx() as c:
        org = _org(c, user["org_id"])
        invoices = db.rows(c.execute("SELECT * FROM invoices WHERE org_id=? ORDER BY id DESC", (user["org_id"],)))
        usage = _usage(c, user["org_id"])
    return {"plan": org["plan"], "trial_ends": org["trial_ends"], "plans": PLANS, "usage": usage, "limits": _limits(org),
            "invoices": invoices, "gst_rate": GST_RATE, "gstin": org["gstin"],
            "gateway": {"razorpay": bool(config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET),
                        "key_id": config.RAZORPAY_KEY_ID or None}}


@router.post("/billing/checkout")
def checkout(body: dict = Body(...), user=Depends(manager)):
    """Create a Razorpay order for a plan. The payment itself happens in Razorpay Checkout in the browser."""
    plan = PLANS.get(body.get("plan"))
    if not plan:
        raise HTTPException(400, "Unknown plan")
    if not (config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET):
        raise HTTPException(400, "Payments are not configured: set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env")
    total = round(plan["price"] * (1 + GST_RATE))
    auth = base64.b64encode(f"{config.RAZORPAY_KEY_ID}:{config.RAZORPAY_KEY_SECRET}".encode()).decode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", method="POST",
                                 data=json.dumps({"amount": total * 100, "currency": "INR",
                                                  "notes": {"org_id": user["org_id"], "plan": body["plan"]}}).encode(),
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            order = json.loads(r.read())
    except Exception as e:
        raise HTTPException(502, f"Razorpay error: {e}")
    return {"order_id": order["id"], "amount": total * 100, "currency": "INR", "key_id": config.RAZORPAY_KEY_ID}


@router.post("/billing/verify")
def verify_payment(body: dict = Body(...), user=Depends(manager)):
    import hashlib
    import hmac
    if not config.RAZORPAY_KEY_SECRET:
        raise HTTPException(400, "Payments are not configured")
    msg = f"{body.get('razorpay_order_id')}|{body.get('razorpay_payment_id')}".encode()
    sig = hmac.new(config.RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, body.get("razorpay_signature", "")):
        raise HTTPException(400, "Payment signature did not verify")
    plan_key = body.get("plan")
    plan = PLANS.get(plan_key)
    if not plan:
        raise HTTPException(400, "Unknown plan")
    with db.tx() as c:
        n = c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] + 1
        gst = round(plan["price"] * GST_RATE, 2)
        c.execute("INSERT INTO invoices (org_id, number, period, plan, amount, gst, total, status, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (user["org_id"], f"WW/{date.today():%Y-%m}/{n:05d}",
                                                 date.today().strftime("%B %Y"), plan["name"], plan["price"], gst,
                                                 plan["price"] + gst, "paid", db.now()))
        c.execute("UPDATE organizations SET plan=? WHERE id=?", (plan_key, user["org_id"]))
        db.audit(c, user, "billing.upgrade", "organization", user["org_id"], None,
                 {"plan": plan_key, "payment": body.get("razorpay_payment_id")})
    return {"ok": True}


@router.get("/billing/invoices/{iid}")
def invoice_pdf(iid: int, user=Depends(manager)):
    from fpdf import FPDF
    with db.tx() as c:
        inv = db.row(c.execute("SELECT * FROM invoices WHERE id=? AND org_id=?", (iid, user["org_id"])).fetchone())
        org = _org(c, user["org_id"])
    if not inv:
        raise HTTPException(404, "Invoice not found")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Tax Invoice", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for line in (f"Invoice no: {inv['number']}", f"Date: {datetime.fromtimestamp(inv['created_at']):%d-%m-%Y}",
                 f"Billed to: {org['name']}", f"GSTIN: {org['gstin'] or '-'}", f"Address: {org['billing_address'] or '-'}",
                 "", f"WorkWatch {inv['plan']} plan - {inv['period']}", f"Amount: INR {inv['amount']:,.2f}",
                 f"GST @ 18%: INR {inv['gst']:,.2f}", f"Total: INR {inv['total']:,.2f}", f"Status: {inv['status']}"):
        pdf.cell(0, 7, line.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
    return Response(bytes(pdf.output()), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="invoice_{inv["number"].replace("/", "-")}.pdf"'})


# ---------- danger zone ----------

@router.post("/danger/delete-footage")
def delete_all_footage(body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        org = _org(c, user["org_id"])
        if body.get("confirm") != org["name"]:
            raise HTTPException(400, "Type the organization name to confirm")
        vs = c.execute("SELECT id, filename FROM videos WHERE org_id=? AND footage_deleted=0", (user["org_id"],)).fetchall()
        for v in vs:
            (config.VIDEOS_DIR / v["filename"]).unlink(missing_ok=True)
        c.execute("UPDATE videos SET footage_deleted=1 WHERE org_id=?", (user["org_id"],))
        db.audit(c, user, "danger.delete_footage", "organization", user["org_id"], None, {"videos": len(vs)})
    return {"deleted": len(vs)}


@router.post("/danger/delete-org")
def delete_org(body: dict = Body(...), user=Depends(manager)):
    with db.tx() as c:
        org = _org(c, user["org_id"])
        if body.get("confirm") != org["name"]:
            raise HTTPException(400, "Type the organization name to confirm")
        vids = c.execute("SELECT filename FROM videos WHERE org_id=?", (user["org_id"],)).fetchall()
        runs = [r["id"] for r in c.execute("SELECT id FROM runs WHERE org_id=?", (user["org_id"],))]
        db.audit(c, user, "danger.delete_org", "organization", user["org_id"], {"name": org["name"]}, None)
        c.execute("DELETE FROM organizations WHERE id=?", (user["org_id"],))
    for v in vids:
        (config.VIDEOS_DIR / v["filename"]).unlink(missing_ok=True)
    for r in runs:
        shutil.rmtree(store.run_dir(r), ignore_errors=True)
    return {"ok": True}
