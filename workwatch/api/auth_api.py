"""Sign-up / sign-in (email, mobile OTP, Google), sessions, invites and the profile tab."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .. import auth, config, db, delivery, settings
from ..auth import current_user

router = APIRouter(prefix="/api/auth")


def _set_cookie(response: Response, token: str):
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400,
                        secure=config.PUBLIC_URL.startswith("https"))


def _bad(e: Exception):
    raise HTTPException(400, str(e))


@router.get("/config")
def auth_config():
    return {"google": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
            "sms": delivery.sms_configured()}


@router.post("/signup")
def signup(request: Request, response: Response, body: dict = Body(...)):
    """Self sign-up creates a new organization with the caller as its manager."""
    try:
        with db.tx() as c:
            org_id = auth.create_org(c, (body.get("company") or "").strip())
            u = auth.create_user(c, org_id, email=body.get("email", ""), password=body.get("password", ""),
                                 name=body.get("name", ""), role="manager")
            db.audit(c, auth.public(u), "org.create", "organization", org_id, None, {"name": body.get("company")})
            _set_cookie(response, auth.start_session(c, u["id"], request.headers.get("user-agent", "")))
            return auth.public(u)
    except ValueError as e:
        _bad(e)


@router.post("/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    try:
        with db.tx() as c:
            u = auth.login_password(c, body.get("email", ""), body.get("password", ""))
            _set_cookie(response, auth.start_session(c, u["id"], request.headers.get("user-agent", "")))
    except ValueError as e:
        _bad(e)
    return {"ok": True}


@router.post("/otp/send")
def otp_send(body: dict = Body(...)):
    try:
        with db.tx() as c:
            sent = auth.send_otp(c, body.get("phone", ""))
    except ValueError as e:
        _bad(e)
    return {"ok": True, "dev": not sent}


@router.post("/otp/verify")
def otp_verify(request: Request, response: Response, body: dict = Body(...)):
    """Signs in an existing mobile user; a new number creates a new organization (needs `company`)."""
    try:
        with db.tx() as c:
            phone = auth.verify_otp(c, body.get("phone", ""), body.get("code", ""))
            u = c.execute("SELECT * FROM users WHERE phone=? AND status='active'", (phone,)).fetchone()
            if u:
                u = dict(u)
            elif body.get("invite"):
                u = _accept_invite(c, body["invite"], phone=phone, name=body.get("name", ""))
            else:
                org_id = auth.create_org(c, (body.get("company") or "").strip())
                u = auth.create_user(c, org_id, phone=phone, name=body.get("name", ""), role="manager")
            _set_cookie(response, auth.start_session(c, u["id"], request.headers.get("user-agent", "")))
            return auth.public(u)
    except ValueError as e:
        _bad(e)


@router.get("/google/start")
def google_start(invite: str = ""):
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(400, "Google sign-in is not configured")
    state = delivery.sign({"n": secrets.token_hex(8), "invite": invite}, ttl_s=600)
    return RedirectResponse(auth.google_auth_url(state))


@router.get("/google/callback")
def google_callback(request: Request, code: str = "", state: str = ""):
    st = delivery.verify(state)
    if not st or not code:
        return RedirectResponse("/#/login?error=google")
    try:
        info = auth.google_exchange(code)
        with db.tx() as c:
            u = c.execute("SELECT * FROM users WHERE (google_sub=? OR email=?) AND status='active'",
                          (info["sub"], info.get("email", "").lower())).fetchone()
            if u:
                u = dict(u)
                if not u["google_sub"]:
                    c.execute("UPDATE users SET google_sub=? WHERE id=?", (info["sub"], u["id"]))
            elif st.get("invite"):
                u = _accept_invite(c, st["invite"], email=info.get("email"), name=info.get("name", ""),
                                   google_sub=info["sub"])
            else:
                org_id = auth.create_org(c, f"{info.get('name', 'My')}'s company")
                u = auth.create_user(c, org_id, email=info.get("email"), name=info.get("name", ""),
                                     google_sub=info["sub"], role="manager")
            token = auth.start_session(c, u["id"], request.headers.get("user-agent", ""))
    except Exception:
        return RedirectResponse("/#/login?error=google")
    resp = RedirectResponse("/#/dashboard")
    _set_cookie(resp, token)
    return resp


@router.post("/logout")
def logout(request: Request, response: Response):
    if t := request.cookies.get(auth.COOKIE):
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (t,))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    with db.tx() as c:
        org = db.row(c.execute("SELECT id, name, logo, timezone, date_format, plan, trial_ends FROM organizations "
                               "WHERE id=?", (user["org_id"],)).fetchone())
        s = settings.get(c, user["org_id"])
        sites = db.rows(c.execute("SELECT id, name FROM sites WHERE org_id=? AND archived=0 ORDER BY id", (user["org_id"],)))
        pending = c.execute(
            "SELECT COUNT(*) FROM segments s JOIN runs r ON r.id=s.run_id JOIN videos v ON v.id=r.video_id "
            "WHERE v.org_id=? AND v.annotated=1 AND s.review_status='pending' AND r.id=(SELECT MAX(id) FROM runs "
            "WHERE video_id=v.id)", (user["org_id"],)).fetchone()[0]
    return {**user, "org": org, "sites": sites, "review_pending": pending,
            "can_review": user["role"] == "manager" or s["review"]["reviewers_can_clear"],
            "labels": s["rules"]["labels"], "face_blur": s["privacy"]["face_blur"],
            "notice_issued": bool(s["privacy"]["notice_issued_on"])}


# ---------- invites ----------

def _accept_invite(c, token: str, **fields) -> dict:
    inv = c.execute("SELECT * FROM invites WHERE token=? AND revoked=0 AND accepted_at IS NULL", (token,)).fetchone()
    if not inv:
        raise ValueError("This invite link is invalid or has already been used")
    if fields.get("email") and fields["email"].lower() != inv["email"].lower():
        raise ValueError(f"This invite is for {inv['email']}")
    if not fields.get("email"):
        fields["email"] = inv["email"]
    u = auth.create_user(c, inv["org_id"], role=inv["role"], site_ids=db.row(inv)["site_ids"], **fields)
    c.execute("UPDATE invites SET accepted_at=? WHERE token=?", (db.now(), token))
    db.audit(c, auth.public(u), "team.invite_accept", "user", u["id"], None, {"role": inv["role"]})
    return u


@router.get("/invite/{token}")
def invite_info(token: str):
    with db.tx() as c:
        inv = c.execute("SELECT i.email, i.role, o.name AS org FROM invites i JOIN organizations o ON o.id=i.org_id "
                        "WHERE token=? AND revoked=0 AND accepted_at IS NULL", (token,)).fetchone()
    if not inv:
        raise HTTPException(404, "This invite link is invalid or has already been used")
    return dict(inv)


@router.post("/invite/{token}/accept")
def invite_accept(token: str, request: Request, response: Response, body: dict = Body(...)):
    try:
        with db.tx() as c:
            inv = c.execute("SELECT email FROM invites WHERE token=?", (token,)).fetchone()
            u = _accept_invite(c, token, email=inv["email"] if inv else None, password=body.get("password", ""),
                               name=body.get("name", ""))
            _set_cookie(response, auth.start_session(c, u["id"], request.headers.get("user-agent", "")))
            return auth.public(u)
    except ValueError as e:
        _bad(e)


# ---------- profile & account (all users) ----------

@router.patch("/profile")
def update_profile(body: dict = Body(...), user=Depends(current_user)):
    allowed = {k: body[k] for k in ("name", "language") if k in body}
    if "language" in allowed and allowed["language"] not in ("en", "hi"):
        raise HTTPException(400, "Unsupported language")
    with db.tx() as c:
        before = {k: user.get(k) for k in allowed}
        for k, v in allowed.items():
            c.execute(f"UPDATE users SET {k}=? WHERE id=?", (v, user["id"]))
        if "email" in body:  # change email: re-verify with the current password
            u = c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if u["pw_hash"] and not auth.check_pw(body.get("password", ""), u["pw_hash"]):
                raise HTTPException(400, "Enter your current password to change the email")
            email = body["email"].strip().lower()
            if c.execute("SELECT 1 FROM users WHERE email=? AND id<>?", (email, user["id"])).fetchone():
                raise HTTPException(400, "That email is already in use")
            c.execute("UPDATE users SET email=? WHERE id=?", (email, user["id"]))
            before["email"], allowed["email"] = user["email"], email
        if "phone" in body:  # change mobile: needs an OTP sent to the new number
            try:
                phone = auth.verify_otp(c, body["phone"], body.get("code", ""))
            except ValueError as e:
                raise HTTPException(400, str(e))
            c.execute("UPDATE users SET phone=? WHERE id=?", (phone, user["id"]))
            before["phone"], allowed["phone"] = user["phone"], phone
        if body.get("new_password"):
            u = c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if u["pw_hash"] and not auth.check_pw(body.get("password", ""), u["pw_hash"]):
                raise HTTPException(400, "Current password is wrong")
            if len(body["new_password"]) < 8:
                raise HTTPException(400, "Use at least 8 characters")
            c.execute("UPDATE users SET pw_hash=? WHERE id=?", (auth.hash_pw(body["new_password"]), user["id"]))
            allowed["password"] = "changed"
        db.audit(c, user, "profile.update", "user", user["id"], before, allowed)
    return {"ok": True}


@router.get("/sessions")
def sessions(request: Request, user=Depends(current_user)):
    cur = request.cookies.get(auth.COOKIE)
    with db.tx() as c:
        rs = db.rows(c.execute("SELECT token, user_agent, created_at, last_seen FROM sessions WHERE user_id=? "
                               "ORDER BY last_seen DESC", (user["id"],)))
    return [{"id": r["token"][:8], "current": r["token"] == cur, "user_agent": r["user_agent"],
             "created_at": r["created_at"], "last_seen": r["last_seen"]} for r in rs]


@router.post("/sessions/signout-all")
def signout_all(request: Request, user=Depends(current_user)):
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE user_id=? AND token<>?", (user["id"], request.cookies.get(auth.COOKIE)))
        db.audit(c, user, "profile.signout_all", "user", user["id"])
    return {"ok": True}


@router.post("/delete-request")
def delete_account_request(user=Depends(current_user)):
    with db.tx() as c:
        c.execute("UPDATE users SET deletion_requested_at=? WHERE id=?", (db.now(), user["id"]))
        c.execute("INSERT INTO deletion_requests (org_id, subject, contact, details, created_at) VALUES (?,?,?,?,?)",
                  (user["org_id"], f"Account deletion: {user['name']}", user["email"] or user["phone"],
                   "Requested from Profile settings", db.now()))
        db.audit(c, user, "profile.delete_request", "user", user["id"])
    return {"ok": True}
