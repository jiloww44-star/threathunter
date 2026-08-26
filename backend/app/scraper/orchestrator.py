"""Scraping orchestrator — spec Part 3.4.

SCHEDULE → FETCH → EXTRACT → NORMALIZE → SIGNALIZE → WEIGHT → STORE

The scheduler (spec Part 4: Celery beat) calls `run_pipeline` on cron;
event-driven runs fire on breaking-news keywords for urgent claims.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
import yaml

from ..config import settings
from ..store.db import EvidenceStore, get_store
from .dedupe import detect_copy_chains
from .extractor import extract_signals
from .fetcher import fetch

log = logging.getLogger("th360.scraper")


def load_sources(path: str | None = None) -> list[dict]:
    cfg_path = Path(path or settings.SOURCES_FILE)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return cfg.get("sources", [])


async def run_pipeline(store: EvidenceStore | None = None,
                       sources: list[dict] | None = None) -> dict:
    store = store or get_store()
    sources = sources if sources is not None else load_sources()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[fetch(client, s) for s in sources])
    for src, ev in zip(sources, results):
        store.upsert_source_meta(src, ok=ev is not None,
                                 error=None if ev else "SOURCE_UNAVAILABLE")

    evidence = [r for r in results if r]
    all_signals = []
    inserted = 0
    for ev in evidence:
        signals = extract_signals(ev)
        all_signals.extend(signals)
        inserted += store.insert_evidence(ev, signals)

    # §1.6 — copy-chain analysis across everything just ingested
    copy_groups = detect_copy_chains(all_signals)

    # §Willison U1 — auto source health scoring after every ingest: stale or
    # echoing sources are demoted BEFORE they silently feed the next check
    # (curators review demotions/recoveries only, never steady state).
    health_actions: list[str] = []
    try:
        from .source_health import score_sources
        sla = {s["id"]: float(s["freshness_sla_hours"])
               for s in sources if s.get("freshness_sla_hours")}
        health_actions = [f"{h.source_id}:{h.action}"
                          for h in score_sources(store, sla_hours=sla)
                          if h.action != "none"]
    except Exception as e:  # health scoring may never break ingestion (§20)
        log.warning("source health scoring degraded: %s", e)

    stats = {
        "sources_attempted": len(sources),
        "sources_ok": len(evidence),
        "signals_stored": inserted,
        "independent_groups_detected": len(copy_groups),
        "source_health_actions": health_actions,
    }
    log.info("pipeline run complete: %s", stats)
    return stats


async def run_source(source_id: str, store: EvidenceStore | None = None) -> dict:
    store = store or get_store()
    srcs = [s for s in load_sources() if s["id"] == source_id]
    return await run_pipeline(store, srcs)
