"""CV pipeline, split in two stages.

Stage 1 — `detect_track()` (heavy, runs once per video, GPU-friendly):
  * YOLOv8 detects people (COCO 0) and phones (COCO 67) on frames sampled at `sample_fps`.
  * ByteTrack keeps one id per person across frames.
  * For every person observation it records the box, detection confidence, a motion score
    (pixel change inside the box between sampled frames) and phone evidence. Phone evidence is
    refined with a pose model (phone near a wrist or ear) on the frames where a phone is seen.
  * Saves a reference frame (the frame with the most people) and a thumbnail per track.

Stage 2 — `classify()` (cheap, re-run whenever zones, names, merges or rules change):
  Turns the stored observations into the five activity states:
    working  inside a Work zone and active
    idle     inside a Work zone but inactive for longer than `idle_threshold_s`
    phone    phone use for `phone_threshold_s`+ continuously (gaps up to `phone_gap_s` tolerated), any zone
    break    inside a Break zone
    exclusion inside an Exclusion zone (tracked, flagged, excluded from working time)
  and flags segments for the review queue.

Neither stage touches the database, so stage 1 can run on a remote GPU worker and ship JSON back.
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
PERSON, PHONE = 0, 67
STATES = ("working", "idle", "phone", "break", "exclusion")

DEFAULT_RULES = {
    "phone_threshold_s": 30.0,     # continuous phone use before it counts as "Talking on phone"
    "phone_gap_s": 4.0,            # missed frames / hand movement tolerated inside a phone call
    "idle_threshold_s": 120.0,     # inactive this long inside a work zone -> idle
    "min_segment_s": 3.0,          # shorter segments go to review
    "review_conf": 0.45,           # mean detection confidence below this goes to review
    "short_track_s": 8.0,          # tracks living less than this are flagged (likely ID switch)
    "motion_threshold": 0.011,    # mean |pixel change| inside the box (0-1) that counts as active
    "move_threshold": 0.12,        # or box displacement in box-heights per second
    "outside_zone_state": "idle",  # state for time spent outside every zone: idle | break | exclusion
    "smooth_s": 1.0,
    "max_gap_s": 2.0,
    "labels": {"working": "Working", "idle": "Idle", "phone": "Talking on phone",
               "break": "Break", "exclusion": "Exclusion"},
}


def merged_rules(rules: dict | None) -> dict:
    out = {**DEFAULT_RULES, **(rules or {})}
    out["labels"] = {**DEFAULT_RULES["labels"], **((rules or {}).get("labels") or {})}
    return out


def pick_device(device: str = "") -> str:
    if device:
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


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


def blur_heads(img, boxes_px, frac: float = 0.24):
    """Blur the head region (top `frac` of each person box). Used for the DPDP face-blur setting."""
    h, w = img.shape[:2]
    for x1, y1, x2, y2 in boxes_px:
        x1, x2 = max(0, int(x1)), min(w, int(x2))
        y1 = max(0, int(y1))
        y2 = min(h, int(y1 + (y2 - y1) * frac))
        if x2 - x1 > 2 and y2 - y1 > 2:
            roi = img[y1:y2, x1:x2]
            k = max(3, (min(roi.shape[:2]) // 3) | 1)
            img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
    return img


# ---------------------------------------------------------------- stage 1

def _phone_owner(phone, people):
    """Pick the person a phone box belongs to: phone centre inside the (slightly widened) upper body."""
    px, py = (phone[0] + phone[2]) / 2, (phone[1] + phone[3]) / 2
    best, best_d = None, 1e9
    for tid, (x1, y1, x2, y2) in people.items():
        bw, bh = x2 - x1, y2 - y1
        if x1 - 0.15 * bw <= px <= x2 + 0.15 * bw and y1 - 0.05 * bh <= py <= y1 + 0.7 * bh:
            d = abs(px - (x1 + x2) / 2)
            if d < best_d:
                best, best_d = tid, d
    return best


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def detect_track(
    video_path: str,
    *,
    model_name: str = config.MODEL,
    pose_model: str = config.POSE_MODEL,
    sample_fps: float = config.SAMPLE_FPS,
    det_conf: float = config.DET_CONF,
    phone_conf: float = config.PHONE_CONF,
    imgsz: int = config.IMGSZ,
    device: str = config.DEVICE,
    thumbs_dir: str | None = None,
    ref_path: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> dict:
    from ultralytics import YOLO  # heavy import, only where inference runs

    t0 = time.time()
    meta = probe(video_path)
    fps = meta["fps"]
    stride = max(1, round(fps / sample_fps))
    dev = pick_device(device)
    half = dev.startswith("cuda")

    model = YOLO(model_name)
    pose = YOLO(pose_model) if pose_model else None
    kw = dict(persist=True, classes=[PERSON, PHONE], conf=min(det_conf, phone_conf), imgsz=imgsz,
              tracker=TRACKER_CFG, verbose=False, device=dev, half=half)

    obs: dict[int, list] = defaultdict(list)  # tid -> [t, x1, y1, x2, y2, conf, motion, phone]
    best: dict[int, tuple] = {}
    prev_small = None
    ref = {"count": -1}
    W, H = meta["width"], meta["height"]
    SW = 320
    scale = SW / W
    total = meta["frames"] or 1
    frames_read = idx = 0
    phone_frames = pose_frames = 0

    cap = cv2.VideoCapture(str(video_path))
    try:
        cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY)
    except Exception:
        pass
    while True:
        if not cap.grab():
            break
        frames_read += 1
        if idx % stride:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        if not ok:
            idx += 1
            continue
        t = idx / fps
        small = cv2.cvtColor(cv2.resize(frame, (SW, int(H * scale))), cv2.COLOR_BGR2GRAY)
        small = cv2.GaussianBlur(small, (3, 3), 0)

        res = model.track(frame, **kw)[0]
        people, phones = {}, []
        b = res.boxes
        if b is not None and len(b):
            xyxy, cls, conf = b.xyxy.cpu().tolist(), b.cls.int().cpu().tolist(), b.conf.cpu().tolist()
            ids = b.id.int().cpu().tolist() if b.id is not None else [None] * len(cls)
            for box, c, cf, tid in zip(xyxy, cls, conf, ids):
                if c == PHONE and cf >= phone_conf:
                    phones.append((*box, cf))
                elif c == PERSON and tid is not None and cf >= det_conf:
                    people[tid] = (box, cf)

        phone_by_tid: dict[int, float] = {}
        if phones and people:
            phone_frames += 1
            boxes = {tid: bx for tid, (bx, _) in people.items()}
            for ph in phones:
                owner = _phone_owner(ph, boxes)
                if owner is not None:
                    phone_by_tid[owner] = max(phone_by_tid.get(owner, 0), ph[4])
            if pose is not None and phone_by_tid:
                # Pose only on frames that contain a phone: confirms "phone near ear / hand" cheaply.
                pose_frames += 1
                pr = pose.predict(frame, classes=[PERSON], conf=0.25, imgsz=imgsz, verbose=False, device=dev)[0]
                if pr.keypoints is not None and len(pr.boxes):
                    kps = pr.keypoints.xy.cpu().numpy()
                    kcf = pr.keypoints.conf.cpu().numpy() if pr.keypoints.conf is not None else None
                    pboxes = pr.boxes.xyxy.cpu().tolist()
                    for tid in list(phone_by_tid):
                        bx = boxes[tid]
                        j = max(range(len(pboxes)), key=lambda k: _iou(bx, pboxes[k]))
                        if _iou(bx, pboxes[j]) < 0.4:
                            continue
                        pts = [kps[j][k] for k in (3, 4, 9, 10)  # ears, wrists
                               if kcf is None or kcf[j][k] > 0.3]
                        bh = bx[3] - bx[1]
                        near = any(
                            min(np.hypot((ph[0] + ph[2]) / 2 - p[0], (ph[1] + ph[3]) / 2 - p[1]) for ph in phones)
                            < 0.22 * bh for p in pts)
                        phone_by_tid[tid] *= 1.0 if near else 0.5

        for tid, ((x1, y1, x2, y2), cf) in people.items():
            motion = 0.0
            if prev_small is not None:
                sx1, sy1 = max(0, int(x1 * scale)), max(0, int(y1 * scale))
                sx2, sy2 = int(x2 * scale), int(y2 * scale)
                if sx2 - sx1 > 2 and sy2 - sy1 > 2:
                    motion = float(cv2.absdiff(small[sy1:sy2, sx1:sx2], prev_small[sy1:sy2, sx1:sx2]).mean() / 255)
            obs[tid].append([round(t, 3), x1 / W, y1 / H, x2 / W, y2 / H, cf, motion, phone_by_tid.get(tid, 0.0)])
            if thumbs_dir is not None:
                score = cf * (x2 - x1) * (y2 - y1)
                if score > best.get(tid, (0,))[0]:
                    crop = frame[max(0, int(y1)): int(y2), max(0, int(x1)): int(x2)]
                    if crop.size:
                        best[tid] = (score, crop.copy(), [x1 - max(0, int(x1)), 0, x2 - max(0, int(x1)), y2 - y1])
        if ref_path and len(people) > ref["count"]:
            ref = {"count": len(people), "t": round(t, 3), "frame": frame.copy(),
                   "boxes": [{"track_id": tid, "box": [round(v, 4) for v in (bx[0] / W, bx[1] / H, bx[2] / W, bx[3] / H)]}
                             for tid, (bx, _) in people.items()],
                   "phones": [[round(v, 4) for v in (p[0] / W, p[1] / H, p[2] / W, p[3] / H)] + [round(p[4], 3)] for p in phones]}
        prev_small = small
        if progress and idx % (stride * 10) == 0:
            progress(min(0.99, idx / total))
        idx += 1
    cap.release()

    thumbs = {}
    if thumbs_dir is not None:
        Path(thumbs_dir).mkdir(parents=True, exist_ok=True)
        for tid, (_, crop, _) in best.items():
            thumbs[tid] = f"{tid}.jpg"
            cv2.imwrite(str(Path(thumbs_dir) / thumbs[tid]), crop)
    ref_out = None
    if ref_path and ref["count"] >= 0:
        cv2.imwrite(ref_path, ref["frame"])
        ref_out = {k: ref[k] for k in ("t", "boxes", "phones")}

    tracks = {}
    for tid, s in obs.items():
        s.sort()
        if s[-1][0] - s[0][0] + stride / fps >= 1.0:  # drop one-off false positives
            tracks[tid] = [[round(v, 4) for v in r] for r in s]

    expected = meta["frames"]
    partial = bool(expected and frames_read < expected * 0.97)
    if progress:
        progress(1.0)
    return {
        "version": 2,
        "video": {**meta, "path": str(video_path)},
        "params": {"model": model_name, "pose_model": pose_model or None, "sample_fps": sample_fps,
                   "dt": stride / fps, "det_conf": det_conf, "phone_conf": phone_conf, "imgsz": imgsz, "device": dev},
        "stats": {"processing_s": round(time.time() - t0, 1), "tracks": len(tracks), "frames_read": frames_read,
                  "frames_analysed": idx // stride, "phone_frames": phone_frames, "pose_frames": pose_frames,
                  "realtime_x": round(meta["duration"] / max(0.1, time.time() - t0), 2)},
        "decode": {"expected_frames": expected, "frames_read": frames_read, "partial": partial,
                   "gap_note": f"decoded {frames_read}/{expected} frames — footage ends early or is corrupt"
                   if partial else None},
        "tracks": tracks,
        "thumbs": thumbs,
        "ref": ref_out,
    }


# ---------------------------------------------------------------- stage 2

def _zone_hit(pt, zones):
    hit = {}
    for z in zones:
        if z["type"] not in hit and cv2.pointPolygonTest(z["_np"], pt, False) >= 0:
            hit[z["type"]] = z["name"]
    for typ in ("exclusion", "break", "work"):
        if typ in hit:
            return typ, hit[typ]
    return None, None


def _majority(labels, k):
    if k <= 1 or len(labels) < 3:
        return list(labels)
    half = k // 2
    return [Counter(labels[max(0, i - half): i + half + 1]).most_common(1)[0][0] for i in range(len(labels))]


def _runs(flags, ts, max_gap):
    """Contiguous runs of True (indices), joining across gaps of up to `max_gap` seconds."""
    out, start, last = [], None, None
    for i, (f, t) in enumerate(zip(flags, ts)):
        if f:
            if start is not None and t - ts[last] > max_gap:
                out.append((start, last))
                start = None
            if start is None:
                start = i
            last = i
    if start is not None:
        out.append((start, last))
    return out


def classify(raw: dict, zones: list[dict], rules: dict | None = None, groups: dict[int, list[int]] | None = None) -> dict:
    """Classify tracks into the five states.

    `groups` maps a person (root track id) to the track ids that belong to them (merges);
    tracks absent from `groups` are skipped (removed in annotation). Default: every track alone.
    Returns {root_tid: {"segments": [...], "totals": {state: s}, "zones": {zone: {state: s}}}}.
    """
    r = merged_rules(rules)
    dt = raw["params"].get("dt") or 1 / raw["params"].get("sample_fps", 8)
    sfps = 1 / dt
    duration = raw["video"].get("duration") or 0
    zs = [dict(z, _np=np.array(z["points"], dtype=np.float32).reshape(-1, 1, 2))
          for z in zones if len(z.get("points", [])) >= 3]
    tracks = {int(k): v for k, v in raw["tracks"].items()}
    if groups is None:
        groups = {tid: [tid] for tid in tracks}
    k = max(1, int(round(r["smooth_s"] * sfps)) | 1)
    outside = r["outside_zone_state"] if r["outside_zone_state"] in STATES else "idle"

    result = {}
    for root, members in groups.items():
        rows = sorted((s for m in members for s in tracks.get(m, [])), key=lambda s: s[0])
        # Overlapping merged tracks: one observation per time step, keep the most confident.
        dedup = []
        for s in rows:
            if dedup and s[0] - dedup[-1][0] < dt / 2:
                if s[5] > dedup[-1][5]:
                    dedup[-1] = s
            else:
                dedup.append(s)
        rows = dedup
        if not rows:
            continue
        ts = [s[0] for s in rows]
        lifetime = ts[-1] - ts[0] + dt

        # activity: pixel change inside the box, or the box itself moving
        active = []
        for i, s in enumerate(rows):
            move = 0.0
            if i:
                p = rows[i - 1]
                h = max(1e-3, s[4] - s[2])
                move = np.hypot((s[1] + s[3]) / 2 - (p[1] + p[3]) / 2, s[4] - p[4]) / h / max(dt, s[0] - p[0])
            active.append(s[6] >= r["motion_threshold"] or move >= r["move_threshold"])
        active = _majority(active, k)

        base, znames = [], []
        for s in rows:
            typ, zname = _zone_hit((float((s[1] + s[3]) / 2), float(s[4])), zs)
            base.append({"work": "working", "break": "break", "exclusion": "exclusion"}.get(typ, outside))
            znames.append(zname)
        base = _majority(base, k)

        states = list(base)
        # idle: inactive inside a work zone for longer than the idle threshold
        inactive_work = [b == "working" and not a for b, a in zip(base, active)]
        for a, b in _runs(inactive_work, ts, r["max_gap_s"]):
            if ts[b] - ts[a] + dt >= r["idle_threshold_s"]:
                for i in range(a, b + 1):
                    if states[i] == "working":
                        states[i] = "idle"
        # phone: continuous use (with gap tolerance) of at least the threshold, in any zone
        phone_conf = [s[7] for s in rows]
        for a, b in _runs([p > 0 for p in phone_conf], ts, r["phone_gap_s"]):
            if ts[b] - ts[a] + dt >= r["phone_threshold_s"]:
                for i in range(a, b + 1):
                    states[i] = "phone"

        segs, cur = [], None
        for i, s in enumerate(rows):
            if cur and (cur["state"] != states[i] or s[0] - ts[cur["_last"]] > r["max_gap_s"]):
                segs.append(cur)
                cur = None
            if cur is None:
                cur = {"state": states[i], "_i": [], "_last": i}
            cur["_i"].append(i)
            cur["_last"] = i

        if cur:
            segs.append(cur)

        out, totals, zone_tot = [], {st: 0.0 for st in STATES}, defaultdict(lambda: {st: 0.0 for st in STATES})
        for sg in segs:
            idx = sg["_i"]
            start = ts[idx[0]]
            end = min(ts[idx[-1]] + dt, duration or ts[idx[-1]] + dt)
            st = sg["state"]
            zn = Counter(znames[i] for i in idx).most_common(1)[0][0]
            conf = float(np.mean([rows[i][5] for i in idx]))
            if st == "phone":
                pc = [phone_conf[i] for i in idx if phone_conf[i] > 0]
                conf = float(np.mean(pc)) if pc else conf
            reasons = []
            if end - start < r["min_segment_s"]:
                reasons.append(f"short segment (<{r['min_segment_s']:g}s)")
            if conf < r["review_conf"] or (st == "phone" and conf < r["review_conf"] + 0.2):
                reasons.append(f"low confidence ({conf:.2f})")
            if lifetime < r["short_track_s"]:
                reasons.append("short-lived track — possible ID switch")
            if st == "exclusion":
                reasons.append("inside an exclusion zone")
            dur = end - start
            totals[st] += dur
            zone_tot[zn or "Outside zones"][st] += dur
            out.append({"start": round(start, 3), "end": round(end, 3), "state": st, "zone": zn,
                        "confidence": round(conf, 3), "flagged": bool(reasons),
                        "flag_reason": "; ".join(reasons) or None})
        result[root] = {"segments": out, "totals": {k2: round(v, 2) for k2, v in totals.items()},
                        "zones": {z: {k2: round(v, 2) for k2, v in d.items() if v} for z, d in zone_tot.items()},
                        "first_seen": ts[0], "last_seen": out[-1]["end"] if out else ts[-1]}
    return result
