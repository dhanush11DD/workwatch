"""Runtime settings, read from environment variables (or a .env file in the project root)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


DATA_DIR = Path(_env("WW_DATA_DIR", str(ROOT / "data")))
VIDEOS_DIR = DATA_DIR / "videos"
RUNS_DIR = DATA_DIR / "runs"
REPORTS_DIR = DATA_DIR / "reports"
INBOX_DIR = DATA_DIR / "inbox"
DB_PATH = DATA_DIR / "workwatch.db"
WEB_DIR = ROOT / "web"

for _d in (DATA_DIR, VIDEOS_DIR, RUNS_DIR, REPORTS_DIR, INBOX_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Pipeline defaults (all overridable per run)
MODEL = _env("WW_MODEL", "yolov8s.pt")
SAMPLE_FPS = float(_env("WW_SAMPLE_FPS", "8"))
DET_CONF = float(_env("WW_DET_CONF", "0.25"))
IMGSZ = int(_env("WW_IMGSZ", "640"))
DEVICE = _env("WW_DEVICE", "")  # "" = auto (cuda > mps > cpu), or "cpu", "mps", "cuda:0"
# Pose model used to confirm phone-near-ear/hand; only runs on frames where a phone is detected. Empty disables.
POSE_MODEL = _env("WW_POSE_MODEL", "yolov8n-pose.pt")
PHONE_CONF = float(_env("WW_PHONE_CONF", "0.25"))

# Review flagging thresholds
MIN_SEGMENT_S = float(_env("WW_MIN_SEGMENT_S", "3"))
LOW_CONF = float(_env("WW_LOW_CONF", "0.45"))
SHORT_TRACK_S = float(_env("WW_SHORT_TRACK_S", "8"))

# Email delivery
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM", SMTP_USER)
SMTP_TLS = _env("SMTP_TLS", "1") not in ("0", "false", "no")
MANAGER_EMAILS = [e.strip() for e in _env("MANAGER_EMAILS").split(",") if e.strip()]

# Public base URL of this deployment, used in WhatsApp/email links and invite links
PUBLIC_URL = _env("WW_PUBLIC_URL", "http://localhost:8000").rstrip("/")
SECRET_KEY = _env("WW_SECRET_KEY", "")  # signs share links; auto-generated into data/ when empty

# WhatsApp Business API: meta | gupshup | interakt (empty = not configured)
WHATSAPP_PROVIDER = _env("WHATSAPP_PROVIDER")
WHATSAPP_TOKEN = _env("WHATSAPP_TOKEN")            # Meta access token / Gupshup apikey / Interakt API key
WHATSAPP_PHONE_ID = _env("WHATSAPP_PHONE_ID")      # Meta phone-number id
WHATSAPP_SOURCE = _env("WHATSAPP_SOURCE")          # Gupshup source number
WHATSAPP_APP = _env("WHATSAPP_APP")                # Gupshup app name

# SMS for mobile OTP login: msg91 | twilio (empty = dev mode, OTP printed to the server log)
SMS_PROVIDER = _env("SMS_PROVIDER")
SMS_KEY = _env("SMS_KEY")                          # MSG91 authkey / Twilio "SID:TOKEN"
SMS_SENDER = _env("SMS_SENDER")                    # MSG91 template id / Twilio from-number

# Google sign-in (OAuth client for a web application; redirect URI = PUBLIC_URL/api/auth/google/callback)
GOOGLE_CLIENT_ID = _env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET")

# Payments (keys only shown as connected/not connected; checkout not wired yet)
RAZORPAY_KEY_ID = _env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = _env("RAZORPAY_KEY_SECRET")

# Job queue: run an analysis worker inside the server process (set 0 when using separate GPU workers)
INPROCESS_WORKER = _env("WW_INPROCESS_WORKER", "1") not in ("0", "false", "no")
WORKER_TOKEN = _env("WW_WORKER_TOKEN")             # shared secret for remote GPU workers
DATA_REGION = _env("WW_DATA_REGION", "Local machine (deploy to AWS ap-south-1 Mumbai for India residency)")

# Daily automation: "HH:MM" local time, empty disables the in-process scheduler
DAILY_RUN_AT = _env("WW_DAILY_RUN_AT", "")
# Which day the daily report covers: "today" or "yesterday"
DAILY_REPORT_DAY = _env("WW_DAILY_REPORT_DAY", "today")


def email_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)
