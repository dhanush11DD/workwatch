"""WorkWatch edge agent — records a camera's RTSP stream per shift and uploads each shift to WorkWatch.

Runs on any small box on the site LAN (Raspberry Pi 4/5, NUC, old laptop) next to the NVR. Needs Python 3.9+
and ffmpeg; nothing else (standard library only).

    python edge_agent/agent.py --server https://app.example.com --token wwa_xxx

What it does
  * Heartbeats every minute (camera health on the dashboard; managers are alerted after 10 min of silence).
  * Pulls its config from the server: RTSP URL, shifts and timezone — edit them in Settings → Cameras.
  * Records each shift with `ffmpeg -c copy` (no re-encode, ~1% CPU). If the stream drops it reconnects and
    keeps recording; the pieces are joined and the clip is flagged "partial" with the gaps listed.
  * Uploads over TUS in 8 MB chunks. Uploads resume after a network or power cut (state lives in the spool dir)
    and the local file is deleted only after the server has it.

Test without waiting for a shift:  --record-now 2   (records 2 minutes immediately, uploads, exits)
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

VERSION = "2.0.0"
CHUNK = 8 * 1024 * 1024
HEARTBEAT_S = 60
RECONNECT_WAIT_S = 10
GAP_TOLERANCE_S = 30  # missing less than this per shift is not worth flagging

log = logging.getLogger("ww-agent")
stop = threading.Event()


# ---------------- HTTP ----------------

class Api:
    def __init__(self, server: str, token: str):
        self.server, self.token = server.rstrip("/"), token

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                timeout: float = 60) -> tuple[int, dict, bytes]:
        url = path if path.startswith("http") else self.server + path
        req = urllib.request.Request(url, data=body, method=method,
                                     headers={"X-Agent-Token": self.token, "Tus-Resumable": "1.0.0",
                                              "User-Agent": f"workwatch-agent/{VERSION}", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()

    def heartbeat(self, extra: dict) -> dict | None:
        try:
            status, _, data = self.request("POST", "/api/agent/heartbeat",
                                           json.dumps({"version": VERSION, **extra}).encode(),
                                           {"Content-Type": "application/json"}, timeout=20)
        except OSError as e:
            log.warning("heartbeat failed: %s", e)
            return None
        if status == 401:
            log.error("Server rejected the agent token — re-pair this camera in Settings → Cameras.")
            return None
        if status != 200:
            log.warning("heartbeat HTTP %s", status)
            return None
        return json.loads(data)


# ---------------- TUS upload (resumable) ----------------

def upload(api: Api, clip: Path, meta: dict) -> bool:
    """Upload clip with TUS. Progress is kept in <clip>.upload.json so a restart resumes instead of re-sending."""
    state_file = clip.with_suffix(clip.suffix + ".upload.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    size = clip.stat().st_size
    if not state.get("location"):
        enc = ",".join(f"{k} {base64.b64encode(str(v).encode()).decode()}" for k, v in meta.items() if v not in (None, ""))
        status, headers, body = api.request("POST", "/api/tus/", b"",
                                            {"Upload-Length": str(size), "Upload-Metadata": enc})
        if status != 201:
            log.error("upload create failed (HTTP %s): %s", status, body[:200])
            return False
        state = {"location": headers["location"]}
        state_file.write_text(json.dumps(state))

    status, headers, _ = api.request("HEAD", state["location"])
    if status == 404:  # server forgot it (expired) — start over
        state_file.unlink(missing_ok=True)
        return upload(api, clip, meta)
    if status != 200:
        log.error("upload HEAD failed (HTTP %s)", status)
        return False
    offset = int(headers.get("upload-offset", "0"))

    with open(clip, "rb") as f:
        while offset < size and not stop.is_set():
            f.seek(offset)
            chunk = f.read(CHUNK)
            status, headers, body = api.request("PATCH", state["location"], chunk,
                                                {"Upload-Offset": str(offset),
                                                 "Content-Type": "application/offset+octet-stream"}, timeout=300)
            if status == 409:  # offset mismatch: ask the server where it is
                _, headers, _ = api.request("HEAD", state["location"])
                offset = int(headers.get("upload-offset", offset))
                continue
            if status != 204:
                log.error("upload PATCH failed (HTTP %s): %s", status, body[:200])
                return False
            offset = int(headers["upload-offset"])
            log.info("uploading %s: %.0f%%", clip.name, 100 * offset / size)
    if offset < size:
        return False
    state_file.unlink(missing_ok=True)
    return True


# ---------------- recording ----------------

def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg not found. Install it: sudo apt install ffmpeg  |  brew install ffmpeg")
    return exe


def record(rtsp: str, end_at: float, work: Path) -> tuple[list[Path], list[tuple[float, float]]]:
    """Record until end_at, reconnecting on drops. Returns the pieces and the (start, end) epoch of every gap."""
    pieces, gaps = [], []
    last_end = time.time()
    while not stop.is_set():
        remaining = end_at - time.time()
        if remaining < 5:
            break
        piece = work / f"part{len(pieces):03d}.mp4"
        started = time.time()
        if started - last_end > GAP_TOLERANCE_S / 3 and pieces:
            gaps.append((last_end, started))
        cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
               "-i", rtsp, "-t", f"{remaining:.0f}", "-c", "copy", "-an", "-movflags", "+faststart", "-y", str(piece)]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while proc.poll() is None:
            if stop.wait(1):
                proc.send_signal(signal.SIGINT)  # lets ffmpeg finalise the mp4
                proc.wait(15)
        err = (proc.stderr.read() or b"").decode(errors="ignore").strip()
        last_end = time.time()
        if piece.exists() and piece.stat().st_size > 100_000:
            pieces.append(piece)
        if end_at - time.time() > 5 and not stop.is_set():
            log.warning("stream dropped (%s) — reconnecting in %ss", err[-200:] or f"exit {proc.returncode}",
                        RECONNECT_WAIT_S)
            stop.wait(RECONNECT_WAIT_S)
    if end_at - last_end > GAP_TOLERANCE_S / 3 and pieces:
        gaps.append((last_end, end_at))
    return pieces, gaps


def join(pieces: list[Path], out: Path) -> None:
    if len(pieces) == 1:
        pieces[0].replace(out)
        return
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces))
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", "-y", str(out)], check=True)
    lst.unlink(missing_ok=True)


def capture_shift(api: Api, cfg: dict, shift: dict, start: datetime, end: datetime, spool: Path) -> None:
    tz = start.tzinfo
    label = f"{cfg['name']} · {shift['name']} · {start:%d %b %Y}"
    log.info("recording %s until %s", label, end.strftime("%H:%M"))
    work = Path(tempfile.mkdtemp(prefix="shift_", dir=spool))
    pieces, gaps = record(cfg["rtsp_url"], end.timestamp(), work)
    if not pieces:
        log.error("nothing recorded for %s — camera unreachable for the whole shift", label)
        shutil.rmtree(work, ignore_errors=True)
        return
    clip = spool / f"{start:%Y%m%d}_{shift['name'].replace(' ', '_')}_{int(start.timestamp())}.mp4"
    join(pieces, clip)
    shutil.rmtree(work, ignore_errors=True)
    missing = sum(b - a for a, b in gaps)
    meta = {"filename": clip.name, "name": label, "shift": shift["name"], "recorded_on": start.date().isoformat()}
    if missing > GAP_TOLERANCE_S or stop.is_set():
        meta["partial"] = "1"
        meta["gap_note"] = "; ".join(
            f"{datetime.fromtimestamp(a, tz):%H:%M}–{datetime.fromtimestamp(b, tz):%H:%M}" for a, b in gaps
        ) or "recording stopped early"
    clip.with_suffix(".meta.json").write_text(json.dumps(meta))
    log.info("recorded %s (%.1f MB%s)", clip.name, clip.stat().st_size / 1e6,
             f", partial: {meta['gap_note']}" if meta.get("partial") else "")


def flush_spool(api: Api, spool: Path) -> None:
    """Upload every finished clip in the spool (oldest first); delete each once the server has it."""
    for meta_file in sorted(spool.glob("*.meta.json")):
        clip = meta_file.with_name(meta_file.name.replace(".meta.json", ".mp4"))
        if not clip.exists():
            meta_file.unlink()
            continue
        if stop.is_set():
            return
        if upload(api, clip, json.loads(meta_file.read_text())):
            log.info("uploaded %s — WorkWatch will analyse it now", clip.name)
            clip.unlink()
            meta_file.unlink()
        else:
            return  # keep order; retry next loop


# ---------------- schedule ----------------

def shift_windows(shifts: list[dict], now: datetime) -> list[tuple[dict, datetime, datetime]]:
    """Today's and yesterday's shift windows (overnight shifts end the next day)."""
    out = []
    for day in (now.date() - timedelta(days=1), now.date()):
        for s in shifts:
            h1, m1 = map(int, s["start"].split(":"))
            h2, m2 = map(int, s["end"].split(":"))
            start = datetime(day.year, day.month, day.day, h1, m1, tzinfo=now.tzinfo)
            end = datetime(day.year, day.month, day.day, h2, m2, tzinfo=now.tzinfo)
            if end <= start:
                end += timedelta(days=1)
            out.append((s, start, end))
    return out


def run(args) -> None:
    api = Api(args.server, args.token)
    spool = Path(args.spool).expanduser()
    spool.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin()

    cfg = api.heartbeat({"state": "starting"})
    if not cfg:
        sys.exit("Could not reach the server with this token.")
    log.info("paired with camera '%s' (id %s)", cfg["name"], cfg["camera_id"])

    recording = threading.Event()

    def heartbeats():
        nonlocal cfg
        while not stop.wait(HEARTBEAT_S):
            cfg = api.heartbeat({"state": "recording" if recording.is_set() else "idle",
                                 "spool_mb": round(sum(p.stat().st_size for p in spool.glob("*.mp4")) / 1e6, 1)}) or cfg

    threading.Thread(target=heartbeats, daemon=True).start()

    if args.record_now:
        if not cfg.get("rtsp_url"):
            sys.exit("This camera has no RTSP URL — add it in Settings → Cameras.")
        tz = ZoneInfo(cfg.get("timezone") or "Asia/Kolkata") if ZoneInfo else None
        start = datetime.now(tz)
        recording.set()
        capture_shift(api, cfg, {"name": "Test"}, start, start + timedelta(minutes=args.record_now), spool)
        recording.clear()
        flush_spool(api, spool)
        return

    done: set[str] = set()
    while not stop.is_set():
        flush_spool(api, spool)
        if not cfg.get("auto_slice", True) or not cfg.get("rtsp_url"):
            stop.wait(30)
            continue
        tz = ZoneInfo(cfg.get("timezone") or "Asia/Kolkata") if ZoneInfo else None
        now = datetime.now(tz)
        shifts = cfg.get("shifts") or []
        if isinstance(shifts, str):
            shifts = json.loads(shifts)
        for shift, start, end in shift_windows(shifts, now):
            key = f"{shift['name']}@{start.isoformat()}"
            if key in done or not (start <= now < end - timedelta(minutes=1)):
                continue
            done.add(key)
            recording.set()
            # Joining late (agent restarted mid-shift) records the rest and flags the missed start as a gap.
            capture_shift(api, cfg, shift, start, end, spool)
            recording.clear()
            break
        stop.wait(20)


def main() -> None:
    p = argparse.ArgumentParser(description="WorkWatch edge agent: RTSP shift recorder + resumable uploader")
    p.add_argument("--server", default=os.environ.get("WW_SERVER", "http://localhost:8000"))
    p.add_argument("--token", default=os.environ.get("WW_AGENT_TOKEN"), help="wwa_… token from Settings → Cameras → Pair")
    p.add_argument("--spool", default=os.environ.get("WW_SPOOL", "~/.workwatch-agent"),
                   help="where clips wait until uploaded (needs ~1 GB per camera-hour at 1080p)")
    p.add_argument("--record-now", type=float, metavar="MINUTES", help="record N minutes now, upload, exit")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    if not args.token:
        p.error("--token is required (Settings → Cameras → Pair agent)")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(args)


if __name__ == "__main__":
    main()
