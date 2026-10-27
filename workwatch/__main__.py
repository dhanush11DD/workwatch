"""Command line entry point:  python -m workwatch <command>

  serve        start the dashboard + API            (python -m workwatch serve --port 8000)
  analyze      run the YOLOv8 pipeline on a file    (python -m workwatch analyze clip.mp4 --zones zones.json -o results.json)
  import       import a results.json into a video   (python -m workwatch import 3 results.json)
  daily        ingest inbox, analyse, report, email (python -m workwatch daily --date 2026-10-27)
  record       record a camera stream into a video  (python -m workwatch record 1 --minutes 60)
  create-user  add a dashboard account              (python -m workwatch create-user boss@acme.com --role manager)
  seed-demo    load a clip as the demo video        (python -m workwatch seed-demo clip.mp4 --zones zones.json)
"""
import argparse
import getpass
import json
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="workwatch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    a = sub.add_parser("analyze")
    a.add_argument("video")
    a.add_argument("--zones", required=True, help="JSON file: list of {name, type: work|break|exclusion, points: [[x,y],...]} in 0-1 coords")
    a.add_argument("-o", "--out", default="results.json")
    a.add_argument("--sample-fps", type=float)
    a.add_argument("--model", help="e.g. yolov8n.pt (fast) or yolov8s.pt / yolov8m.pt (more accurate)")
    a.add_argument("--conf", type=float, help="detection confidence threshold")
    a.add_argument("--device", help="cpu, mps (Apple GPU) or cuda:0")

    i = sub.add_parser("import")
    i.add_argument("video_id", type=int)
    i.add_argument("results")

    d = sub.add_parser("daily")
    d.add_argument("--date", help="YYYY-MM-DD (default: per WW_DAILY_REPORT_DAY)")
    d.add_argument("--no-email", action="store_true")

    r = sub.add_parser("record")
    r.add_argument("camera_id", type=int)
    r.add_argument("--minutes", type=float, default=60)
    r.add_argument("--analyze", action="store_true")

    u = sub.add_parser("create-user")
    u.add_argument("email")
    u.add_argument("--role", choices=["manager", "viewer"], default="viewer")
    u.add_argument("--name", default="")

    sd = sub.add_parser("seed-demo")
    sd.add_argument("video")
    sd.add_argument("--zones", help="zones JSON (default: none, draw them in the dashboard)")
    sd.add_argument("--name", default="Sample warehouse clip")
    sd.add_argument("--no-analyze", action="store_true")

    args = ap.parse_args(argv)

    from . import db
    db.init()

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("workwatch.server:app", host=args.host, port=args.port)

    elif args.cmd == "analyze":
        from . import pipeline
        kw = {k: v for k, v in {"sample_fps": args.sample_fps, "model_name": args.model, "det_conf": args.conf,
                                "device": args.device}.items() if v}
        out = Path(args.out)
        res = pipeline.analyze(args.video, json.loads(Path(args.zones).read_text()),
                               thumbs_dir=str(out.with_suffix("")) + "_thumbs",
                               progress=lambda p: print(f"\r{p * 100:5.1f}%", end="", file=sys.stderr), **kw)
        print(file=sys.stderr)
        out.write_text(json.dumps(res))
        _print_people(res["people"])
        print(f"\nwrote {out}  ({res['stats']['processing_s']}s)")

    elif args.cmd == "import":
        from . import store
        res = json.loads(Path(args.results).read_text())
        thumbs = Path(str(Path(args.results).with_suffix("")) + "_thumbs")
        print("run", store.import_results(args.video_id, res, thumbs_src=thumbs if thumbs.exists() else None))

    elif args.cmd == "daily":
        from . import jobs
        print(json.dumps(jobs.daily(report_day=args.date, send_email=not args.no_email), indent=2))

    elif args.cmd == "record":
        from . import jobs
        vid = jobs.record_camera(args.camera_id, args.minutes)
        print("video", vid)
        if args.analyze:
            jobs.analyze_video(vid)

    elif args.cmd == "create-user":
        from . import auth
        pw = getpass.getpass("Password (8+ chars): ")
        print(auth.create_user(args.email, pw, args.name, role=args.role))

    elif args.cmd == "seed-demo":
        from . import jobs
        zones = json.loads(Path(args.zones).read_text()) if args.zones else []
        with db.tx() as c:
            c.execute("UPDATE videos SET is_demo=0")
        vid = jobs.register_video(Path(args.video), args.name, zones=zones, is_demo=True)
        print("demo video", vid)
        if zones and not args.no_analyze:
            jobs.analyze_video(vid)
            from . import store
            with db.tx() as c:
                ps = store.run_people(c, db.latest_run_id(c, vid))
            _print_people([{**p, "segments": p["segments"]} for p in ps])


def _print_people(people):
    from .reports import hms
    print(f"{'person':<16}{'working':>10}{'non-working':>13}{'flagged':>9}")
    for p in people:
        flagged = sum(1 for s in p["segments"] if s["flagged"])
        print(f"{p['label']:<16}{hms(p['working_s']):>10}{hms(p['idle_s']):>13}{flagged:>9}")


if __name__ == "__main__":
    main()
