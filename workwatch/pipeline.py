"""YOLOv8 + ByteTrack + zone logic.

Turns a video and a list of zones into per-person working / non-working segments:

  1. Detect people (COCO class 0) on frames sampled at `sample_fps` and track them with ByteTrack,
     so each person keeps one track id across frames.
  2. For every observation take the person's foot point (bottom-centre of the box) and test it
     against the zones. Inside a `work` zone -> working. Inside an `exclusion` zone -> not counted.
     Anywhere else (a `break` zone or no zone) -> idle (non-working).
  3. Smooth the per-sample states with a majority filter, then cut them into segments.
  4. Flag segments a human should look at: very short ones, low detection confidence, and
     segments on short-lived tracks (usually an ID switch or occlusion).

This module has no database dependency: `analyze()` returns a plain dict that can be written to
JSON and imported later, so the heavy step can run on a different machine from the dashboard.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import config

TRACKER_CFG = str(Path(__file__).with_name("tracker.yaml"))

WORK, IDLE, EXCLUDED = "working", "idle", "excluded"


def probe(video_path: str) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"fps": fps, "frames": frames, "width": w, "height": h, "duration": frames / fps if fps else 0}


def read_frame(video_path: str, t: float = 0.0):
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def _zone_of(pt, zones):
    """Return (state, zone_name) for a normalised point. Exclusion beats work beats break."""
    hit = {"exclusion": None, "work": None, "break": None}
    for z in zones:
        poly = z["_np"]
        if cv2.pointPolygonTest(poly, pt, False) >= 0 and hit.get(z["type"]) is None:
            hit[z["type"]] = z["name"]
    if hit["exclusion"]:
        return EXCLUDED, hit["exclusion"]
    if hit["work"]:
        return WORK, hit["work"]
    return IDLE, hit["break"]


def _majority_smooth(labels: list, k: int) -> list:
    if k <= 1 or len(labels) < 3:
        return labels
    half = k // 2
    out = []
    for i in range(len(labels)):
        window = labels[max(0, i - half): i + half + 1]
        out.append(Counter(window).most_common(1)[0][0])
    return out


def analyze(
    video_path: str,
    zones: list[dict],
    *,
    model_name: str = config.MODEL,
    sample_fps: float = config.SAMPLE_FPS,
    det_conf: float = config.DET_CONF,
    imgsz: int = config.IMGSZ,
    device: str = config.DEVICE,
    max_gap_s: float = 2.0,
    smooth_s: float = 1.0,
    min_track_s: float = 1.0,
    min_segment_s: float = config.MIN_SEGMENT_S,
    low_conf: float = config.LOW_CONF,
    short_track_s: float = config.SHORT_TRACK_S,
    thumbs_dir: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> dict:
    from ultralytics import YOLO  # imported lazily: heavy, and not needed by the web server itself

    t0 = time.time()
    meta = probe(video_path)
    fps = meta["fps"]
    stride = max(1, round(fps / sample_fps))
    dt = stride / fps

    zones = [dict(z) for z in zones if len(z.get("points", [])) >= 3]
    for z in zones:
        z["_np"] = np.array(z["points"], dtype=np.float32).reshape(-1, 1, 2)

    model = YOLO(model_name)
    track_kw = dict(persist=True, classes=[0], conf=det_conf, imgsz=imgsz, tracker=TRACKER_CFG, verbose=False)
    if device:
        track_kw["device"] = device

    obs: dict[int, list] = defaultdict(list)  # tid -> [(t, x1, y1, x2, y2, conf)] normalised coords
    best: dict[int, tuple] = {}              # tid -> (score, crop)
    cap = cv2.VideoCapture(str(video_path))
    W, H = meta["width"], meta["height"]
    idx = 0
    total = meta["frames"] or 1
    while True:
        if not cap.grab():
            break
        if idx % stride == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            res = model.track(frame, **track_kw)[0]
            boxes = res.boxes
            if boxes is not None and boxes.id is not None:
                for (x1, y1, x2, y2), tid, c in zip(
                    boxes.xyxy.cpu().tolist(), boxes.id.int().cpu().tolist(), boxes.conf.cpu().tolist()
                ):
                    obs[tid].append((t, x1 / W, y1 / H, x2 / W, y2 / H, c))
                    if thumbs_dir is not None:
                        score = c * (x2 - x1) * (y2 - y1)
                        if score > best.get(tid, (0,))[0]:
                            crop = frame[max(0, int(y1)): int(y2), max(0, int(x1)): int(x2)]
                            if crop.size:
                                best[tid] = (score, crop.copy())
            if progress and idx % (stride * 10) == 0:
                progress(min(0.99, idx / total))
        idx += 1
    cap.release()

    k = max(1, int(round(smooth_s * sample_fps)) | 1)  # odd window
    people, tracks = [], {}
    for tid, samples in sorted(obs.items()):
        samples.sort()
        lifetime = samples[-1][0] - samples[0][0] + dt
        if lifetime < min_track_s:
            continue  # one-off false positive
        raw = [_zone_of((float((s[1] + s[3]) / 2), float(s[4])), zones) for s in samples]
        labels = _majority_smooth(raw, k)

        # Cut on state changes (or tracking gaps) only; moving between two work zones stays one segment.
        segs, cur = [], None
        for s, (state, zname) in zip(samples, labels):
            t = s[0]
            if cur and (cur["state"] != state or t - cur["_last"] > max_gap_s):
                segs.append(cur)
                cur = None
            if cur is None:
                cur = {"start": t, "state": state, "_zones": [], "_confs": [], "_last": t}
            cur["_zones"].append(zname)
            cur["_confs"].append(s[5])
            cur["_last"] = t
        if cur:
            segs.append(cur)

        out_segs = []
        for sg in segs:
            if sg["state"] == EXCLUDED:
                continue
            sg["zone"] = Counter(sg["_zones"]).most_common(1)[0][0]
            end = min(sg["_last"] + dt, meta["duration"] or sg["_last"] + dt)
            conf = float(np.mean(sg["_confs"]))
            reasons = []
            if end - sg["start"] < min_segment_s:
                reasons.append(f"short segment (<{min_segment_s:g}s)")
            if conf < low_conf:
                reasons.append(f"low detection confidence ({conf:.2f})")
            if lifetime < short_track_s:
                reasons.append("short-lived track — possible ID switch")
            out_segs.append({
                "start": round(sg["start"], 3), "end": round(end, 3),
                "state": sg["state"], "zone": sg["zone"], "confidence": round(conf, 3),
                "flagged": bool(reasons), "flag_reason": "; ".join(reasons) or None,
            })
        if not out_segs:
            continue

        thumb = None
        if thumbs_dir is not None and tid in best:
            Path(thumbs_dir).mkdir(parents=True, exist_ok=True)
            thumb = f"{tid}.jpg"
            cv2.imwrite(str(Path(thumbs_dir) / thumb), best[tid][1])

        working = sum(s["end"] - s["start"] for s in out_segs if s["state"] == WORK)
        idle = sum(s["end"] - s["start"] for s in out_segs if s["state"] == IDLE)
        people.append({
            "track_id": tid, "label": f"Worker {tid}", "thumb": thumb,
            "first_seen": round(samples[0][0], 3), "last_seen": out_segs[-1]["end"],
            "working_s": round(working, 2), "idle_s": round(idle, 2), "segments": out_segs,
        })
        code = {WORK: 1, IDLE: 0, EXCLUDED: 2}
        tracks[tid] = [
            [round(s[0], 2), round(s[1], 4), round(s[2], 4), round(s[3], 4), round(s[4], 4), code[l[0]]]
            for s, l in zip(samples, labels)
        ]

    if progress:
        progress(1.0)
    return {
        "video": {**meta, "path": str(video_path)},
        "zones": [{k: v for k, v in z.items() if k != "_np"} for z in zones],
        "params": {
            "model": model_name, "sample_fps": sample_fps, "det_conf": det_conf, "imgsz": imgsz,
            "max_gap_s": max_gap_s, "smooth_s": smooth_s, "min_segment_s": min_segment_s,
            "low_conf": low_conf, "short_track_s": short_track_s,
        },
        "stats": {
            "processing_s": round(time.time() - t0, 1), "people": len(people),
            "flagged": sum(s["flagged"] for p in people for s in p["segments"]),
            "working_s": round(sum(p["working_s"] for p in people), 2),
            "idle_s": round(sum(p["idle_s"] for p in people), 2),
        },
        "people": people,
        "tracks": tracks,
    }
