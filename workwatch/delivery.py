"""Outbound channels: email (SMTP), WhatsApp Business API, SMS (OTP), plus signed share links."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage

from . import config

log = logging.getLogger("workwatch.delivery")


class NotConfigured(RuntimeError):
    pass


def email_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_FROM)


def whatsapp_configured() -> bool:
    return config.WHATSAPP_PROVIDER in ("meta", "gupshup", "interakt") and bool(config.WHATSAPP_TOKEN)


def sms_configured() -> bool:
    return config.SMS_PROVIDER in ("msg91", "twilio") and bool(config.SMS_KEY)


# ---------- signed links (report downloads from WhatsApp/email without logging in) ----------

def _secret() -> bytes:
    if config.SECRET_KEY:
        return config.SECRET_KEY.encode()
    p = config.DATA_DIR / ".secret_key"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
    return p.read_text().strip().encode()


def sign(payload: dict, ttl_s: int = 14 * 86400) -> str:
    body = base64.urlsafe_b64encode(json.dumps({**payload, "exp": int(time.time() + ttl_s)}).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def verify(token: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return data if data.get("exp", 0) > time.time() else None
    except Exception:
        return None


# ---------- email ----------

def send_email(to: list[str], subject: str, text: str, html: str | None = None,
               attachments: list[tuple[str, bytes, str]] = ()) -> None:
    if not email_configured():
        raise NotConfigured("Email is not configured: set SMTP_HOST and SMTP_FROM in .env")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, config.SMTP_FROM, ", ".join(to)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        if config.SMTP_TLS:
            s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


# ---------- WhatsApp ----------

def _post(url: str, data, headers: dict, form: bool = False) -> dict:
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json", **headers}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw.decode(errors="replace")}


def normalise_in(number: str) -> str:
    """+91 format for Indian mobile numbers; leaves other international numbers alone."""
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def send_whatsapp(number: str, text: str, document_url: str | None = None, filename: str | None = None) -> str:
    """Send a text (plus optional document link). Returns the provider message id.

    Note: outside a 24h customer-service window Meta requires an approved template message;
    configure one with the same wording and replace the text payload when going live.
    """
    if not whatsapp_configured():
        raise NotConfigured("WhatsApp is not configured: set WHATSAPP_PROVIDER and WHATSAPP_TOKEN in .env")
    to = normalise_in(number)
    p = config.WHATSAPP_PROVIDER
    if p == "meta":
        url = f"https://graph.facebook.com/v20.0/{config.WHATSAPP_PHONE_ID}/messages"
        payload = ({"messaging_product": "whatsapp", "to": to, "type": "document",
                    "document": {"link": document_url, "filename": filename or "report", "caption": text}}
                   if document_url else
                   {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})
        res = _post(url, payload, {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"})
        return (res.get("messages") or [{}])[0].get("id", "")
    if p == "gupshup":
        msg = ({"type": "file", "url": document_url, "filename": filename or "report", "caption": text}
               if document_url else {"type": "text", "text": text})
        res = _post("https://api.gupshup.io/wa/api/v1/msg",
                    {"channel": "whatsapp", "source": config.WHATSAPP_SOURCE, "destination": to,
                     "src.name": config.WHATSAPP_APP, "message": json.dumps(msg)},
                    {"apikey": config.WHATSAPP_TOKEN}, form=True)
        return res.get("messageId", "")
    # interakt
    res = _post("https://api.interakt.ai/v1/public/message/",
                {"countryCode": "+" + to[:-10], "phoneNumber": to[-10:], "type": "Text",
                 "data": {"message": text + (f"\n{document_url}" if document_url else "")}},
                {"Authorization": f"Basic {config.WHATSAPP_TOKEN}"})
    return str(res.get("id", ""))


# ---------- SMS (OTP) ----------

def send_sms_otp(phone: str, code: str) -> bool:
    """Returns True if sent through a provider, False in dev mode (code written to the server log)."""
    if not sms_configured():
        log.warning("DEV OTP for %s: %s  (set SMS_PROVIDER to send real SMS)", phone, code)
        return False
    to = normalise_in(phone)
    if config.SMS_PROVIDER == "msg91":
        _post("https://control.msg91.com/api/v5/otp", {"template_id": config.SMS_SENDER, "mobile": to, "otp": code},
              {"authkey": config.SMS_KEY})
    else:
        sid, _, token = config.SMS_KEY.partition(":")
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        _post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
              {"To": "+" + to, "From": config.SMS_SENDER, "Body": f"Your WorkWatch login code is {code}"},
              {"Authorization": f"Basic {auth}"}, form=True)
    return True
