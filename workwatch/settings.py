"""Per-organization settings with defaults. Stored as JSON on organizations.settings, deep-merged on read."""
import copy

from . import db
from .pipeline import DEFAULT_RULES

EVENTS = {
    "slice_ready": "Slice ready for annotation",
    "analysis_failed": "Analysis failed",
    "review_pending": "Review items pending",
    "report_ready": "Report ready",
    "camera_offline": "Camera offline",
    "quota_near": "Quota nearing limit",
    "payment_failed": "Payment failed",
}

REPORT_COLUMNS = ["present", "working", "idle", "phone", "break", "exclusion", "efficiency", "flagged"]

DEFAULTS = {
    "rules": {k: v for k, v in DEFAULT_RULES.items()},
    "review": {
        "notify": ["manager", "reviewer"],
        "reminder_hours": 24,
        "bulk_similar": True,
        "reviewers_can_clear": True,  # open decision in the spec: deputy / backup reviewer
    },
    "delivery": {
        "whatsapp_recipients": [],     # [{name, number, language, opted_in}]
        "email_recipients": [],
        "on_ready": True,
        "daily": True,
        "weekly": True,
        "formats": ["xlsx", "pdf"],
        "columns": REPORT_COLUMNS,
        "zone_breakdown": True,
        "show_formula": True,
        "payroll_format": "greytHR",
        "pdf_footer": "",
    },
    "notifications": {e: {"in_app": True, "email": e in ("analysis_failed", "report_ready", "camera_offline"),
                          "whatsapp": e in ("slice_ready", "report_ready")} for e in EVENTS},
    "quiet_hours": {"enabled": False, "start": "21:00", "end": "08:00"},
    "privacy": {
        "face_blur": False,
        "retention_days": 90,
        "consent_text": ("This workplace uses CCTV video analytics to measure working time at workstations. "
                         "Footage is processed only for attendance and productivity reporting, retained for a limited "
                         "period, and never used for face recognition. Contact the grievance officer for questions, "
                         "corrections or deletion requests."),
        "awareness_text": ("Notice to employees: cameras in work areas are analysed to record time spent working, idle, "
                           "on phone calls, on breaks and in restricted zones. Reports are reviewed by a manager before "
                           "use. You may request access to or correction of your records."),
        "notice_issued_on": None,
        "grievance_name": "",
        "grievance_contact": "",
    },
    "upload_defaults": {"camera_id": None, "shift": ""},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def get(conn, org_id: int) -> dict:
    r = conn.execute("SELECT settings FROM organizations WHERE id=?", (org_id,)).fetchone()
    return _merge(DEFAULTS, db.row(r)["settings"] if r else {})


def update(conn, org_id: int, section: str, values, user) -> dict:
    current = get(conn, org_id)
    if section not in DEFAULTS:
        raise KeyError(section)
    before = current[section]
    after = _merge(before, values) if isinstance(before, dict) and isinstance(values, dict) else values
    stored = db.row(conn.execute("SELECT settings FROM organizations WHERE id=?", (org_id,)).fetchone())["settings"] or {}
    stored[section] = after
    conn.execute("UPDATE organizations SET settings=? WHERE id=?", (db.dumps(stored), org_id))
    db.audit(conn, user, f"settings.{section}.update", "organization", org_id, before, after)
    return after


def reset(conn, org_id: int, section: str, user) -> dict:
    stored = db.row(conn.execute("SELECT settings FROM organizations WHERE id=?", (org_id,)).fetchone())["settings"] or {}
    before = get(conn, org_id)[section]
    stored.pop(section, None)
    conn.execute("UPDATE organizations SET settings=? WHERE id=?", (db.dumps(stored), org_id))
    db.audit(conn, user, f"settings.{section}.reset", "organization", org_id, before, DEFAULTS[section])
    return copy.deepcopy(DEFAULTS[section])
