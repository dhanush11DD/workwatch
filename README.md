# WorkWatch

Working and non-working hours per person, counted from video / CCTV footage with **YOLOv8 + ByteTrack + OpenCV**,
with a dashboard for drawing zones, reviewing flagged segments and sending daily timesheets to the manager.

```
 footage (upload · CCTV record · NVR inbox folder)
        │
        ▼
 YOLOv8 person detection ──► ByteTrack ids ──► foot point in zone?  work → working
        (sampled frames)                                           break / none → non-working
        │                                                          exclusion → not counted
        ▼
 smoothing → segments → flags (short · low confidence · short-lived track)
        │
        ▼
 dashboard: timeline · review queue · rename / merge people ──► report CSV ──► email to manager
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                         # optional: model, SMTP, daily schedule

# load the sample clip as the demo (zones included) and analyse it
python -m workwatch seed-demo samples/warehouse_sample.mp4 --zones samples/demo_zones.json

python -m workwatch serve                    # → http://127.0.0.1:8000
```

Open the dashboard and **Sign up**: the first account is the manager. Later sign-ups are viewers until a
manager promotes them on the **Team** page.

## Using the dashboard

| Page | What you do there |
|---|---|
| **Dashboard** | Total working time, people tracked, segments awaiting review, per-person table, recent footage. |
| **Videos** | Upload footage, add CCTV cameras (RTSP/HTTP), take snapshots, record clips, set per-camera zones. |
| **Video page** | Draw *work / break / exclusion* zones on the frame (click points, click first point to close, drag corners), run the pipeline, watch tracked boxes over the video, see each person's timeline, rename people (same name across videos = combined hours), merge two ids that are the same person. |
| **Review queue** | Every flagged segment, playable in a loop with that person highlighted. Confirm it or flip working ↔ non-working. Totals update immediately. |
| **Reports** | Build the daily timesheet (by recording date) or one from all footage, download CSV, email it, run the daily job on demand. |

## How "working" is decided

* Person detected with YOLOv8 (COCO class *person*) on frames sampled at `WW_SAMPLE_FPS`, tracked with ByteTrack.
* Each observation uses the **foot point** (bottom-centre of the box) — it's where the person stands, so zones
  drawn on the floor work even when bodies overlap machines.
* Foot point in a **work** zone → working. In a **break** zone or outside every zone → non-working.
  In an **exclusion** zone (office, corridor you don't care about) → not counted at all.
* A 1-second majority filter removes flicker at zone borders; segments split only when the state changes or the
  person is lost for more than 2 s.
* Flagged for review: segments shorter than `WW_MIN_SEGMENT_S`, mean detection confidence below `WW_LOW_CONF`,
  and anything on a track that lived less than `WW_SHORT_TRACK_S` (typical sign of an ID switch).

Only time a person is **visible** is counted. Someone off-camera is neither working nor idle for that camera —
cover each work area with a camera, and name people consistently so hours from several cameras add up.

## CCTV and daily automation

Each camera gets an inbox folder `data/inbox/<camera id>/`. Anything dropped there is imported by the daily job,
inherits that camera's zones, and is analysed. Two ways to fill it:

```bash
# continuous recording in 1-hour files (run as a service per camera)
ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@192.168.1.20:554/stream1" \
  -c copy -f segment -segment_time 3600 -strftime 1 data/inbox/1/%Y-%m-%d_%H-%M.mp4

# or an on-demand clip from the dashboard ("Record") / CLI
python -m workwatch record 1 --minutes 60 --analyze
```

The **daily job** = ingest inbox → analyse every new video that has zones → build that day's timesheet → email it
to `MANAGER_EMAILS`:

```bash
python -m workwatch daily                    # report for today (or yesterday: WW_DAILY_REPORT_DAY)
python -m workwatch daily --date 2026-10-27 --no-email
```

Schedule it either inside the server (`WW_DAILY_RUN_AT=19:00` in `.env`) or with cron:

```cron
30 19 * * *  cd /path/to/poc-cv && .venv/bin/python -m workwatch daily >> data/daily.log 2>&1
```

Email works with any SMTP provider — fill the `SMTP_*` settings (for Gmail use an App Password).

## Running the pipeline on another machine

The heavy step has no database dependency, so it can run on a GPU box next to the NVR:

```bash
python -m workwatch analyze day.mp4 --zones zones.json --model yolov8m.pt --device cuda:0 -o results.json
```

Then import `results.json` from the video page (**Import results**) or `python -m workwatch import <video id> results.json`.

## Scaling notes

* `yolov8n` runs the 18 s sample in a few seconds on a laptop CPU; `yolov8s`/`m` are more accurate for small or
  crouched workers. `WW_DEVICE=mps` uses the Apple GPU, `cuda:0` an NVIDIA GPU.
* A full 8-hour camera day at 5 fps is ~144k frames: roughly 10–20 min on a mid-range GPU with `yolov8s`.
* Browsers play H.264 MP4. Many CCTV systems record H.265 — the pipeline reads it fine, but for in-browser
  playback transcode with `ffmpeg -i in.mp4 -c:v libx264 -crf 23 out.mp4`.
* Uniforms make re-identification across long occlusions hard; that's what **merge** and **rename** in the
  dashboard are for. Badge/face recognition can be added later as another step in `pipeline.py`.

## Layout

```
workwatch/
  pipeline.py   YOLOv8 + ByteTrack + zones → segments + flags (no DB)
  tracker.yaml  ByteTrack settings for sampled frames
  store.py      save runs, per-person totals with reviews/merges applied
  reports.py    aggregation, CSV, email
  jobs.py       analysis queue, camera record/snapshot, inbox ingestion, daily job + scheduler
  server.py     FastAPI API + serves web/
  auth.py       accounts, manager/viewer roles
web/            dashboard (plain HTML/CSS/JS, no build step)
samples/        sample clip + demo zones
data/           database, videos, runs, reports, inbox (created on first run)
```
