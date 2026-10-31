# WorkWatch

Worker productivity analytics from CCTV, built for Indian factories, warehouses and workshops. A manager uploads
footage or connects a camera, draws zones once, and gets per-worker **working · idle · phone · break · excluded**
hours. A reviewer checks the doubtful parts. Approved timesheets go out as Excel, PDF or CSV, or in greytHR, Keka,
Zoho Payroll or Tally format, by email or WhatsApp.

```
 footage: browser upload (TUS, resumable) · edge agent per camera (RTSP → shift clips) · NVR inbox folder
        │
        ▼
 job queue ── in-process worker  or  remote GPU workers (python -m workwatch worker --server … --token …)
        │
        ▼
 stage 1  YOLOv8 people + phones ─► ByteTrack ids ─► motion score ─► pose check for phone near wrist/ear
        │       (heavy, once per video, raw.json)
        ▼
 stage 2  zones + rules ─► working / idle / phone / break / exclusion segments + review flags
        │       (cheap, re-run instantly when zones, names, merges or rules change)
        ▼
 Uploaded → Analysing → Annotate (keep/remove detections, name workers, merge ids)
          → Review pending (hard gate) → Report ready → Sent
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                         # optional: every external service is off until its keys are set

# analyse the sample clip once; every new organization gets it as its demo
python -m workwatch seed-demo samples/warehouse_sample.mp4 --zones samples/demo_zones.json

python -m workwatch serve                    # → http://127.0.0.1:8000
```

Open the app and **Sign up**. Each sign-up creates its own organization (multi-tenant, data scoped by `org_id`),
and its first user is the **manager**. Invite reviewers from **Settings → Team**.

## The app

| Area | What it does |
|---|---|
| **Dashboard** | Working hours, efficiency, daily state chart, top workers, zone time, pipeline counts, camera health. |
| **Videos** | Library by pipeline status, resumable upload. Each video has three tabs: **Annotate** (detection preview: click a box to keep, remove, name or merge it), **Timeline** (playback with state-coloured boxes plus per-worker segments), and **Details**. |
| **Cameras** | Zone template per camera (drag vertices), shifts, RTSP, edge-agent pairing, snapshot, health. |
| **Processing queue** | Jobs, progress, retry. Works the same with in-process or remote workers. |
| **Review queue** | Flagged segments, playable. Approve, reclassify or add a note. Bulk-approve similar ones. Reports stay blocked until the queue is clear. |
| **Reports** | Preview, generate, export (xlsx/pdf/csv/payroll), deliver (email, WhatsApp), delivery log. |
| **Workers** | Saved worker list (names, codes, departments), CSV import. |
| **Settings** | Profile, organization and sites, team and invites (with the access matrix), workers, cameras, zones, five-state rules, review, delivery, notifications, privacy (DPDP), audit trail, billing (Razorpay, GST invoices), integrations, danger zone. |

Hindi/English toggle in the user menu. All times are shown in IST.

## Five states

| State | Rule (defaults, editable in Settings → Rules) |
|---|---|
| working | inside a Work zone and moving |
| idle | inside a Work zone, no motion for longer than the idle threshold |
| phone | phone detected (and confirmed by pose) for 30 s+ continuously, any zone |
| break | inside a Break zone |
| exclusion | inside an Exclusion zone. Tracked and flagged, but not counted. |

Efficiency = working ÷ (present − excluded). Only visible time is counted: someone off-camera counts as neither
working nor idle for that camera.

## Scaling the pipeline

**GPU workers.** Run the API on a small server and the heavy work on GPU boxes:

```bash
# on the API server (.env)
WW_INPROCESS_WORKER=0
WW_WORKER_TOKEN=some-long-secret

# on each GPU box (as many as you like — jobs are claimed atomically)
python -m workwatch worker --server https://app.example.com --token some-long-secret
```

A worker downloads the video, runs stage 1 with `WW_DEVICE=cuda:0`, and posts `raw.json` back. Stage 2 runs on the
server. A crashed job can be retried from the Processing queue.

**Offline.** `python -m workwatch analyze day.mp4 -o results.zip` on any machine, then upload the zip on the video
page (**Import results**) or run `python -m workwatch import <video id> results.zip`.

**Throughput.** An 8-hour camera day at 8 fps is about 230k frames. With `yolov8s` that is roughly 15–25 min on
a mid-range NVIDIA GPU, or 2–3× faster with `yolov8n`. Lower `WW_SAMPLE_FPS` to 5 for long shifts.

## Cameras: edge agent

The agent runs on a small box on the site LAN (a Raspberry Pi, a NUC or an old laptop). It needs Python 3.9+ and ffmpeg, and nothing
from `pip`.

1. **Settings → Cameras → Add camera**: set the RTSP URL and shifts.
2. **Pair agent**: copy the command shown. It is displayed once.
3. On the site box:

```bash
sudo apt install ffmpeg
python3 edge_agent/agent.py --server https://app.example.com --token wwa_…
python3 edge_agent/agent.py --server … --token … --record-now 2     # 2-minute test right away
```

The agent heartbeats every minute (camera health on the dashboard, alert after 10 min offline) and records each
shift with `ffmpeg -c copy`. It reconnects when the stream drops and marks the clip *partial* with the gap times.
It uploads over TUS, which resumes after network or power cuts, and deletes a clip only once the server has it.
Run it as a systemd service per camera.

No agent? Drop NVR exports into `data/inbox/<camera id>/`. `python -m workwatch maintenance` (also run hourly
inside the server) imports them with that camera's zones.

## Integrations (all optional, `.env`)

| Service | Keys |
|---|---|
| Email reports and invites | `SMTP_*` |
| WhatsApp reports | `WHATSAPP_PROVIDER` = meta / gupshup / interakt plus its token |
| Mobile OTP login | `SMS_PROVIDER` = msg91 / twilio, plus `SMS_KEY` and `SMS_SENDER` |
| Google login | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (redirect: `/api/auth/google/callback`) |
| Billing | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` |

Without keys, the feature shows **not configured** in Settings → Integrations, and deliveries are logged as such.
Nothing is faked.

## Privacy (DPDP Act 2023)

Faces are blurred in every frame the app serves. Footage retention is 30, 60 or 90 days. The app tracks issuance
of the CCTV awareness notice and has a grievance officer field. It keeps a log of worker access and deletion
requests, offers a full data export, and keeps an immutable audit trail (enforced with database triggers).
For India data residency, deploy in AWS ap-south-1 (Mumbai) and set `WW_DATA_REGION`.

## Layout

```
workwatch/
  pipeline.py    stage 1 detect+track (YOLOv8, ByteTrack, pose) and stage 2 classify (five states, flags)
  jobs.py        job queue, workers, register/ingest video, demo cloning, maintenance scheduler
  store.py       runs, per-person totals with reviews/merges applied
  reports.py     aggregation, xlsx/pdf/csv/payroll exports
  delivery.py    email, WhatsApp, SMS adapters
  db.py          SQLite (WAL) schema, org scoping, immutable audit
  auth.py        orgs, users, sessions, OTP, Google, invites, roles
  api/           FastAPI routers: videos+TUS, review, reports, org/settings/billing, cameras+agent, workers, dashboard
edge_agent/      RTSP shift recorder + resumable uploader (stdlib only)
web/             app (General Sans, vanilla ES modules, no build step)
samples/         sample clip + demo zones
data/            database, videos, runs, reports, inbox (created on first run)
```
