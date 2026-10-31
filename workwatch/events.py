"""Notification events: always stored in-app, and sent by email / WhatsApp per the org's notification settings."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, db, delivery, settings

log = logging.getLogger("workwatch.events")


def _quiet(org_tz: str, quiet: dict) -> bool:
    if not quiet.get("enabled"):
        return False
    now = datetime.now(ZoneInfo(org_tz or "Asia/Kolkata")).strftime("%H:%M")
    a, b = quiet["start"], quiet["end"]
    return (a <= now or now < b) if a > b else (a <= now < b)


def emit(c, org_id: int, event: str, title: str, body: str = "", link: str = "") -> None:
    db.notify(c, org_id, event, title, body, link)
    s = settings.get(c, org_id)
    prefs = s["notifications"].get(event, {})
    org = c.execute("SELECT timezone FROM organizations WHERE id=?", (org_id,)).fetchone()
    if _quiet(org["timezone"] if org else "Asia/Kolkata", s["quiet_hours"]):
        return
    url = f"{config.PUBLIC_URL}/#{link}" if link else config.PUBLIC_URL
    if prefs.get("email") and delivery.email_configured():
        to = [r["email"] for r in c.execute(
            "SELECT email FROM users WHERE org_id=? AND role='manager' AND status='active' AND email IS NOT NULL", (org_id,))]
        to += [e for e in s["delivery"]["email_recipients"] if e not in to] if event == "report_ready" else []
        if to:
            _send(c, org_id, "email", ", ".join(to), event,
                  lambda: delivery.send_email(to, f"WorkWatch: {title}", f"{body}\n\n{url}"))
    if prefs.get("whatsapp") and delivery.whatsapp_configured():
        for rcp in s["delivery"]["whatsapp_recipients"]:
            if rcp.get("opted_in"):
                _send(c, org_id, "whatsapp", rcp["number"], event,
                      lambda n=rcp["number"]: delivery.send_whatsapp(n, f"*{title}*\n{body}\n{url}"))


def _send(c, org_id, channel, recipient, kind, fn):
    try:
        pid = fn()
        status, err = "sent", None
    except Exception as e:  # never let a notification failure break the main action
        log.warning("%s notification to %s failed: %s", channel, recipient, e)
        status, err, pid = "failed", str(e)[:300], None
    c.execute("INSERT INTO deliveries (org_id, channel, recipient, kind, status, error, provider_id, created_at) "
              "VALUES (?,?,?,?,?,?,?,?)", (org_id, channel, recipient, kind, status, err, pid or None, db.now()))
