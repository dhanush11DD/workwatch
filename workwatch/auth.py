"""Accounts, sessions, roles and the organization boundary.

Sign-in: email + password, mobile number + OTP, or Google. A new sign-up creates a new organization and
becomes its manager; everyone else joins through an invite link with the role chosen by a manager.
Every API dependency here returns a user dict that carries `org_id`; queries must filter by it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import urllib.parse
import urllib.request

from fastapi import Depends, HTTPException, Request

from . import config, db, delivery

COOKIE = "ww_session"
TRIAL_DAYS = 14


def hash_pw(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def check_pw(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    salt, _, digest = stored.partition("$")
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex(), digest)


def public(u: dict) -> dict:
    out = {k: u.get(k) for k in ("id", "org_id", "email", "phone", "name", "role", "status", "language", "photo")}
    out["site_ids"] = json.loads(u["site_ids"]) if isinstance(u.get("site_ids"), str) else u.get("site_ids") or []
    out["methods"] = [m for m, ok in (("password", u.get("pw_hash")), ("phone", u.get("phone")),
                                      ("google", u.get("google_sub"))) if ok]
    return out


def normalise_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 11:
        raise ValueError("Enter a 10-digit mobile number")
    return "+" + digits


def create_org(c, name: str) -> int:
    org_id = c.execute("INSERT INTO organizations (name, trial_ends, created_at) VALUES (?,?,?)",
                       (name or "My company", time.time() + TRIAL_DAYS * 86400, db.now())).lastrowid
    c.execute("INSERT INTO sites (org_id, name, created_at) VALUES (?,?,?)", (org_id, "Main site", db.now()))
    # The demo clip is added once this transaction commits (its writes wait on SQLite's busy timeout).
    threading.Timer(0.5, _demo, args=(org_id,)).start()
    return org_id


def _demo(org_id: int):
    from . import jobs
    try:
        jobs.clone_demo(org_id)
    except Exception:
        logging.getLogger("workwatch.auth").exception("could not add the demo clip to org %s", org_id)


def create_user(c, org_id: int, *, email=None, phone=None, password=None, name="", role="manager",
                google_sub=None, site_ids=None) -> dict:
    email = email.strip().lower() if email else None
    if email and c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ValueError("An account with this email already exists")
    if phone and c.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
        raise ValueError("An account with this mobile number already exists")
    if password is not None and len(password) < 8:
        raise ValueError("Use a password of at least 8 characters")
    uid = c.execute(
        "INSERT INTO users (org_id, email, phone, name, pw_hash, google_sub, role, site_ids, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (org_id, email, phone, name or (email.split("@")[0] if email else phone), hash_pw(password) if password else None,
         google_sub, role, db.dumps(site_ids or []), db.now())).lastrowid
    return dict(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def start_session(c, user_id: int, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sessions (token, user_id, user_agent, created_at, last_seen) VALUES (?,?,?,?,?)",
              (token, user_id, user_agent[:200], db.now(), db.now()))
    return token


def login_password(c, email: str, password: str) -> dict:
    u = c.execute("SELECT * FROM users WHERE email=? AND status='active'", (email.strip().lower(),)).fetchone()
    if not u or not check_pw(password, u["pw_hash"]):
        raise ValueError("Wrong email or password")
    return dict(u)


# ---------- mobile OTP ----------

def send_otp(c, phone: str) -> bool:
    phone = normalise_phone(phone)
    prev = c.execute("SELECT expires FROM otps WHERE phone=?", (phone,)).fetchone()
    if prev and prev["expires"] - 270 > time.time():  # one code per 30 s
        raise ValueError("Please wait a few seconds before requesting another code")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    c.execute("INSERT OR REPLACE INTO otps (phone, code_hash, expires, attempts) VALUES (?,?,?,0)",
              (phone, hashlib.sha256(code.encode()).hexdigest(), time.time() + 300))
    return delivery.send_sms_otp(phone, code)


def verify_otp(c, phone: str, code: str) -> str:
    phone = normalise_phone(phone)
    r = c.execute("SELECT * FROM otps WHERE phone=?", (phone,)).fetchone()
    if not r or r["expires"] < time.time():
        raise ValueError("The code has expired — request a new one")
    if r["attempts"] >= 5:
        raise ValueError("Too many attempts — request a new code")
    c.execute("UPDATE otps SET attempts=attempts+1 WHERE phone=?", (phone,))
    if not hmac.compare_digest(hashlib.sha256(code.strip().encode()).hexdigest(), r["code_hash"]):
        raise ValueError("Wrong code")
    c.execute("DELETE FROM otps WHERE phone=?", (phone,))
    return phone


# ---------- Google ----------

def google_auth_url(state: str) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": config.GOOGLE_CLIENT_ID, "redirect_uri": f"{config.PUBLIC_URL}/api/auth/google/callback",
        "response_type": "code", "scope": "openid email profile", "state": state, "prompt": "select_account"})


def google_exchange(code: str) -> dict:
    body = urllib.parse.urlencode({
        "code": code, "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{config.PUBLIC_URL}/api/auth/google/callback", "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=20) as r:
        tok = json.loads(r.read())
    req = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo",
                                 headers={"Authorization": f"Bearer {tok['access_token']}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())  # sub, email, email_verified, name, picture


# ---------- request dependencies ----------

def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        with db.tx() as c:
            u = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
                          "WHERE s.token=? AND u.status='active'", (token,)).fetchone()
            if u:
                c.execute("UPDATE sessions SET last_seen=? WHERE token=?", (db.now(), token))
                return public(dict(u))
    raise HTTPException(401, "Sign in required")


def manager(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "manager":
        raise HTTPException(403, "Only managers can do this")
    return user


def reviewer(user: dict = Depends(current_user)) -> dict:
    """Can clear review items: managers always; reviewers when the org allows it (deputy setting)."""
    if user["role"] == "manager":
        return user
    from . import settings
    with db.tx() as c:
        if settings.get(c, user["org_id"])["review"]["reviewers_can_clear"]:
            return user
    raise HTTPException(403, "Your organization only lets managers clear the review queue")


def site_filter(user: dict, alias: str = "") -> tuple[str, list]:
    """SQL fragment restricting rows to the user's assigned sites (empty assignment = all sites)."""
    if not user["site_ids"]:
        return "", []
    col = f"{alias}.site_id" if alias else "site_id"
    return f" AND ({col} IS NULL OR {col} IN ({','.join('?' * len(user['site_ids']))}))", list(user["site_ids"])
