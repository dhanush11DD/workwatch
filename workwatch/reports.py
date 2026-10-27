"""Timesheet reports: aggregate per person, write CSV, email to managers."""
from __future__ import annotations

import csv
import json
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

from . import config, db, store


def hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def aggregate(c, video_ids: list[int] | None = None, report_date: str | None = None):
    """Per-person totals over the latest run of each selected video. Returns (rows, totals, used_video_ids).

    `report_date` selects videos recorded on that day; `video_ids` selects explicitly;
    neither means every analysed video.
    """
    if video_ids:
        vids = db.rows(c.execute(
            f"SELECT * FROM videos WHERE id IN ({','.join('?' * len(video_ids))})", video_ids))
    elif report_date:
        vids = db.rows(c.execute("SELECT * FROM videos WHERE recorded_on=?", (report_date,)))
    else:
        vids = db.rows(c.execute("SELECT * FROM videos"))

    agg: dict[str, dict] = {}
    used = []
    for v in vids:
        run_id = db.latest_run_id(c, v["id"])
        if not run_id:
            continue
        used.append(v["id"])
        for p in store.run_people(c, run_id):
            # Named people are merged across videos/cameras; unnamed tracks stay per video.
            key = p["label"] if not p["label"].startswith("Worker ") else f"{v['name']} · {p['label']}"
            a = agg.setdefault(key, {"person": key, "videos": [], "working_s": 0.0, "idle_s": 0.0,
                                     "flagged": 0, "pending": 0})
            a["videos"].append(v["name"])
            a["working_s"] += p["working_s"]
            a["idle_s"] += p["idle_s"]
            a["flagged"] += p["flagged"]
            a["pending"] += p["pending"]

    rows = []
    for a in sorted(agg.values(), key=lambda a: -a["working_s"]):
        obs = a["working_s"] + a["idle_s"]
        rows.append({**a, "videos": sorted(set(a["videos"])), "observed_s": obs,
                     "efficiency": round(100 * a["working_s"] / obs, 1) if obs else 0.0})
    tw = sum(r["working_s"] for r in rows)
    ti = sum(r["idle_s"] for r in rows)
    totals = {"people": len(rows), "working_s": tw, "idle_s": ti,
              "efficiency": round(100 * tw / (tw + ti), 1) if tw + ti else 0.0,
              "pending": sum(r["pending"] for r in rows)}
    return rows, totals, used


def build(video_ids: list[int] | None = None, report_date: str | None = None, created_by: str | None = None) -> dict:
    """Create and store a report (with its CSV) from the latest run of each selected video."""
    with db.tx() as c:
        rows, totals, used = aggregate(c, video_ids, report_date)
        title = f"Daily timesheet — {report_date}" if report_date else (
            "Timesheet — selected footage" if video_ids else "Timesheet — all footage")
        cur = c.execute(
            "INSERT INTO reports (title, report_date, video_ids, rows, totals, csv_path, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (title, report_date, json.dumps(used), json.dumps(rows), json.dumps(totals), "", created_by, db.now()),
        )
        rid = cur.lastrowid
        path = config.REPORTS_DIR / f"workwatch_report_{rid}_{report_date or f'{datetime.now():%Y-%m-%d}'}.csv"
        write_csv(path, rows, totals)
        c.execute("UPDATE reports SET csv_path=? WHERE id=?", (str(path), rid))
        return db.row(c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone())


def write_csv(path, rows, totals):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Person", "Footage", "Working (h:mm:ss)", "Non-working (h:mm:ss)", "Observed (h:mm:ss)",
                    "Working hours", "Efficiency %", "Flagged segments", "Pending review"])
        for r in rows:
            w.writerow([r["person"], " | ".join(r["videos"]), hms(r["working_s"]), hms(r["idle_s"]),
                        hms(r["observed_s"]), f"{r['working_s'] / 3600:.3f}", r["efficiency"],
                        r["flagged"], r["pending"]])
        w.writerow([])
        w.writerow(["TOTAL", "", hms(totals["working_s"]), hms(totals["idle_s"]),
                    hms(totals["working_s"] + totals["idle_s"]), f"{totals['working_s'] / 3600:.3f}",
                    totals["efficiency"], "", totals["pending"]])


def email(report: dict, recipients: list[str]) -> None:
    if not config.email_configured():
        raise RuntimeError("Email is not configured: set SMTP_HOST, SMTP_FROM (and SMTP_USER/SMTP_PASSWORD) in .env")
    if not recipients:
        raise RuntimeError("No recipients: set MANAGER_EMAILS in .env")
    t = report["totals"]
    body_rows = "".join(
        f"<tr><td>{escape(r['person'])}</td><td>{hms(r['working_s'])}</td><td>{hms(r['idle_s'])}</td>"
        f"<td>{r['efficiency']}%</td><td>{r['pending']}</td></tr>" for r in report["rows"])
    pending_note = (f"<p><b>{t['pending']} flagged segment(s) still await review</b> — totals may change.</p>"
                    if t["pending"] else "")
    html = f"""<div style="font-family:system-ui,sans-serif">
<h2>{escape(report['title'])}</h2>
<p>{t['people']} people · {hms(t['working_s'])} working · {hms(t['idle_s'])} non-working · {t['efficiency']}% efficiency</p>
{pending_note}
<table cellpadding="6" style="border-collapse:collapse" border="1">
<tr><th>Person</th><th>Working</th><th>Non-working</th><th>Efficiency</th><th>Pending review</th></tr>
{body_rows}</table><p>CSV attached. Generated by WorkWatch.</p></div>"""

    msg = EmailMessage()
    msg["Subject"] = f"WorkWatch: {report['title']}"
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(f"{report['title']}\nWorking: {hms(t['working_s'])}  Non-working: {hms(t['idle_s'])}\nCSV attached.")
    msg.add_alternative(html, subtype="html")
    with open(report["csv_path"], "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="csv", filename=report["csv_path"].split("/")[-1])

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        if config.SMTP_TLS:
            s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)

    with db.tx() as c:
        c.execute("UPDATE reports SET emailed_to=?, emailed_at=? WHERE id=?",
                  (", ".join(recipients), db.now(), report["id"]))
