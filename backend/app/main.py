"""ThreatHunter360 API — spec Part 1 (FastAPI backend).

Run: uvicorn app.main:app --host 0.0.0.0 --port 8000
On startup the demo seed pack (Part 10) is ingested so the platform answers
immediately with zero external dependencies.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import admin, factcheck, feed, graph, journey, kyc, ops, voice
from .core.errors import ERROR_MAP, PipelineError
from .store.db import get_store

logging.basicConfig(level=os.getenv("TH360_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("th360.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = get_store()
    if not store.all_evidence():  # first boot → ingest demo seed pack
        from .scraper.orchestrator import run_pipeline
        stats = await run_pipeline(store)
        log.info("seed pack ingested: %s", stats)
    yield


app = FastAPI(
    title="ThreatHunter360",
    version="3.0.0",
    description=("SOVEREIGN FUSION: governed agent swarm + conversational "
                 "cortex. Fact Checker, Journey Advisor, KYC Verification, "
                 "PATHFINDER orchestration, VOYAGER/SENTINEL/HUNTER/AUDITOR "
                 "agents, Evidence & Trust Layer — evidence-based "
                 "conclusions, honest uncertainty, provenance everywhere, "
                 "humans in command."),
    lifespan=lifespan,
)

# Browser-facing: the Vite dev server proxies /api (see frontend/.env-less
# setup) so CORS stays permissive only for the dev origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("TH360_CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# §20 — classified errors: what happened / what it means / what to do next.
@app.exception_handler(PipelineError)
async def pipeline_error_handler(request, exc: PipelineError):
    title, meaning, next_step = ERROR_MAP.get(
        exc.code,
        ("An unexpected error occurred", "Processing stopped",
         "Please retry or contact support"),
    )
    return JSONResponse(
        status_code=exc.status,
        content={"error_code": exc.code, "title": title, "meaning": meaning,
                 "next_step": next_step},
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    store = get_store()
    return {"status": "ready", "evidence_items": len(store.all_evidence())}


@app.get("/")
async def root():
    return {
        "product": "ThreatHunter360",
        "version": "3.0.0 SOVEREIGN FUSION",
        "modules": ["factcheck", "journey", "kyc", "ops-node", "cortex"],
        "agents": ["VOYAGER", "SENTINEL", "SENTINEL_FORENSICS", "HUNTER",
                   "AUDITOR"],
        "docs": "/docs",
        "spec": "ThreatHunter360 v3.0 — SOVEREIGN FUSION Upgrade "
                "Specification.md",
    }


for module in (factcheck, journey, kyc, feed, graph, voice, admin, ops):
    app.include_router(module.router)
