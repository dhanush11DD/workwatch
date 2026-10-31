"""Command line entry point:  python -m workwatch <command>

  serve        start the dashboard + API (+ in-process analysis worker)   python -m workwatch serve --port 8000
  worker       run analysis jobs from the queue                          python -m workwatch worker
               ... on a remote GPU box, over HTTP                         python -m workwatch worker --server https://app --token $WW_WORKER_TOKEN
  analyze      run stage 1 (detect + track) on a file -> results.zip     python -m workwatch analyze clip.mp4 -o results.zip
  import       import a results.zip/json into a video                    python -m workwatch import 3 results.zip
  maintenance  inbox ingest, retention, camera health, reminders         python -m workwatch maintenance
  seed-demo    analyse the sample clip once; new organizations get it    python -m workwatch seed-demo samples/warehouse_sample.mp4 --zones samples/demo_zones.json
  create-org   create an organization + manager from the shell           python -m workwatch create-org "Acme Steel" boss@acme.com
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

    w = sub.add_parser("worker")
    w.add_argument("--server", help="WorkWatch URL (remote mode)")
    w.add_argument("--token", help="WW_WORKER_TOKEN of that server")
    w.add_argument("--once", action="store_true", help="process one job and exit")

    a = sub.add_parser("analyze")
    a.add_argument("video")
    a.add_argument("-o", "--out", default="results.zip")
    a.add_argument("--model", help="yolov8n.pt (fast) / yolov8s.pt (default) / yolov8m.pt (accurate)")
    a.add_argument("--device", help="cpu, mps or cuda:0 (default: auto)")
    a.add_argument("--sample-fps", type=float)

    i = sub.add_parser("import")
    i.add_argument("video_id", type=int)
    i.add_argument("results")

    sub.add_parser("maintenance")

    sd = sub.add_parser("seed-demo")
    sd.add_argument("video")
    sd.add_argument("--zones", required=True)
    sd.add_argument("--name", default="Demo · steel fabrication floor")
    sd.add_argument("--org", type=int, help="also add it to this existing organization id")
    sd.add_argument("--all", action="store_true", help="add it to every existing organization")

    co = sub.add_parser("create-org")
    co.add_argument("name")
    co.add_argument("email")

    args = ap.parse_args(argv)

    from . import db
    db.init()

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("workwatch.server:app", host=args.host, port=args.port)

    elif args.cmd == "worker":
        import logging
        from . import jobs
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        if args.server:
            jobs.remote_worker(args.server, args.token or "", once=args.once)
        else:
            jobs.worker_loop(once=args.once)

    elif args.cmd == "analyze":
        import tempfile
        import zipfile
        from . import pipeline
        kw = {k: v for k, v in {"model_name": args.model, "device": args.device, "sample_fps": args.sample_fps}.items() if v}
        tmp = Path(tempfile.mkdtemp())
        res = pipeline.detect_track(args.video, thumbs_dir=str(tmp / "thumbs"), ref_path=str(tmp / "ref.jpg"),
                                    progress=lambda p: print(f"\r{p * 100:5.1f}%", end="", file=sys.stderr), **kw)
        print(file=sys.stderr)
        with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("result.json", json.dumps(res))
            for f in (tmp / "thumbs").glob("*.jpg"):
                z.write(f, f"thumbs/{f.name}")
            if (tmp / "ref.jpg").exists():
                z.write(tmp / "ref.jpg", "ref.jpg")
        print(json.dumps(res["stats"]))
        print(f"wrote {args.out}")

    elif args.cmd == "import":
        import tempfile
        import zipfile
        from . import store
        p = Path(args.results)
        if zipfile.is_zipfile(p):
            tmp = Path(tempfile.mkdtemp())
            with zipfile.ZipFile(p) as z:
                z.extractall(tmp)
            print("run", store.import_raw(args.video_id, json.loads((tmp / "result.json").read_text()),
                                          thumbs_src=tmp / "thumbs", ref_src=tmp / "ref.jpg"))
        else:
            print("run", store.import_raw(args.video_id, json.loads(p.read_text())))

    elif args.cmd == "maintenance":
        from . import jobs
        print(json.dumps(jobs.maintenance(), indent=2))

    elif args.cmd == "seed-demo":
        from . import jobs
        res = jobs.build_demo(Path(args.video), json.loads(Path(args.zones).read_text()), args.name)
        print("demo cached:", json.dumps(res["stats"]))
        with db.tx() as c:
            orgs = [r["id"] for r in c.execute("SELECT id FROM organizations")] if args.all else (
                [args.org] if args.org else [])
            if orgs:
                c.execute(f"DELETE FROM videos WHERE is_demo=1 AND org_id IN ({','.join('?' * len(orgs))})", orgs)
        for o in orgs:
            print(f"org {o}: demo video", jobs.clone_demo(o))

    elif args.cmd == "create-org":
        from . import auth
        pw = getpass.getpass("Manager password (8+ chars): ")
        with db.tx() as c:
            org = auth.create_org(c, args.name)
            u = auth.create_user(c, org, email=args.email, password=pw, role="manager")
        print(f"organization {org}, manager {u['email']}")


if __name__ == "__main__":
    main()
