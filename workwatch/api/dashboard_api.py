"""Dashboard numbers: state totals, daily trend, top people, footage pipeline, camera health."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from .. import db, store
from ..auth import current_user, site_filter
from ..pipeline import STATES
from .cameras_api import health

router = APIRouter(prefix="/api")


@router.get("/dashboard")
def dashboard(days: int = 14, site_id: int = 0, user=Depends(current_user)):
    days = max(1, min(days, 90))
    start = date.today() - timedelta(days=days - 1)
    frag, args = site_filter(user)
    sql, params = "SELECT * FROM videos WHERE org_id=?" + frag, [user["org_id"], *args]
    if site_id:
        sql += " AND site_id=?"
        params.append(site_id)
    with db.tx() as c:
        videos = [store.video_view(c, v) for v in db.rows(c.execute(sql + " ORDER BY recorded_on", params))]
        pipeline = defaultdict(int)
        for v in videos:
            pipeline[v["status"]] += 1
        totals = {s: 0.0 for s in STATES}
        trend = {(start + timedelta(days=i)).isoformat(): {s: 0.0 for s in STATES} for i in range(days)}
        people: dict[str, dict] = {}
        zones = defaultdict(lambda: {s: 0.0 for s in STATES})
        in_range = [v for v in videos if v["run_id"] and (v["is_demo"] or (v["recorded_on"] or "") >= start.isoformat())]
        for v in in_range:
            day = v["recorded_on"] if v["recorded_on"] in trend else None
            for p in store.run_people(c, v["run_id"], include_removed=False):
                name = p["worker_name"] or p["label"]
                agg = people.setdefault(name, {"person": name, **{s: 0.0 for s in STATES}, "flagged": 0})
                for s, d in p["totals"].items():
                    totals[s] += d
                    agg[s] += d
                    if day:
                        trend[day][s] += d
                agg["flagged"] += p["pending"]
                for z, d in p["zone_totals"].items():
                    for s, x in d.items():
                        zones[z][s] += x
        cams = db.rows(c.execute("SELECT * FROM cameras WHERE org_id=?", (user["org_id"],)))
        pending = sum(v["pending"] for v in videos if v["annotated"])
        recent = db.rows(c.execute("SELECT * FROM notifications WHERE org_id=? ORDER BY id DESC LIMIT 8", (user["org_id"],)))
    top = sorted(people.values(), key=lambda p: -p["working"])
    for p in top:
        p["efficiency"] = store.efficiency({s: p[s] for s in STATES})
        p["present"] = sum(p[s] for s in STATES)
    camera_health = defaultdict(int)
    for cam in cams:
        camera_health[health(cam)] += 1
    return {
        "range": {"from": start.isoformat(), "to": date.today().isoformat(), "days": days},
        "totals": totals, "present": sum(totals.values()), "efficiency": store.efficiency(totals),
        "people": len(people), "videos": len(in_range), "pending_review": pending,
        "trend": [{"date": d, **v} for d, v in trend.items()],
        "top": top[:8], "zones": [{"zone": z, **v} for z, v in sorted(zones.items(), key=lambda x: -sum(x[1].values()))],
        "pipeline": dict(pipeline), "camera_health": dict(camera_health), "cameras": len(cams),
        "recent": recent, "has_demo": any(v["is_demo"] for v in videos),
    }
