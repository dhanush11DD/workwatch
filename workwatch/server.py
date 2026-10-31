"""WorkWatch web API + dashboard.  Run:  python -m workwatch serve"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import config, db, jobs
from .api import auth_api, cameras_api, dashboard_api, org_api, reports_api, review_api, videos_api, worker_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    jobs.start_inprocess_workers()
    jobs.start_scheduler()
    yield


app = FastAPI(title="WorkWatch", version="2.0", lifespan=lifespan)


@app.middleware("http")
async def _headers(request: Request, call_next):
    response = await call_next(request)
    # The dashboard has no build step / hashed filenames, so make browsers revalidate it.
    if not request.url.path.startswith(("/api/", "/r/")):
        response.headers["Cache-Control"] = "no-cache"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


for r in (auth_api, org_api, videos_api, review_api, reports_api, cameras_api, worker_api, dashboard_api):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}


app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
