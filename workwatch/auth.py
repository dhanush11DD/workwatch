"""Email + password accounts with two roles. The first account created becomes a manager."""
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request

from . import db

COOKIE = "ww_session"


def hash_pw(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def check_pw(password: str, stored: str) -> bool:
    salt, _, digest = stored.partition("$")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return hmac.compare_digest(dk.hex(), digest)


def create_user(email: str, password: str, name: str = "", role: str | None = None) -> dict:
    email = email.strip().lower()
    if "@" not in email or len(password) < 8:
        raise ValueError("Enter a valid email and a password of at least 8 characters")
    with db.tx() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise ValueError("An account with this email already exists")
        if role is None:
            role = "manager" if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 else "viewer"
        uid = c.execute("INSERT INTO users (email, name, pw_hash, role, created_at) VALUES (?,?,?,?,?)",
                        (email, name or email.split("@")[0], hash_pw(password), role, db.now())).lastrowid
        return public(db.row(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()))


def public(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "role")}


def login(email: str, password: str) -> str:
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        if not u or not check_pw(password, u["pw_hash"]):
            raise ValueError("Wrong email or password")
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)", (token, u["id"], db.now()))
        return token


def logout(token: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        with db.tx() as c:
            u = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                          (token,)).fetchone()
            if u:
                return public(dict(u))
    raise HTTPException(401, "Sign in required")


def manager(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "manager":
        raise HTTPException(403, "Only managers can do this")
    return user
