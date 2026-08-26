"""Fetcher with deduplication & provenance — spec Part 3.1 / 3.1.

Two transports:
  * http/https — httpx with the ThreatHunter360Bot UA and timeout (robots.txt
    and rate-limit compliance happen in the source registry layer, §22).
  * file       — demo profile (Part 10): fixture directory instead of HTTP.

Every success stamps provenance; every failure is a classified
SOURCE_UNAVAILABLE error — never fabricated content (§20).
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx

from ..config import SEED_ROOT
from .models import RawEvidence, SourceUnavailable
from ..core.nlp_lite import utcnow_iso

log = logging.getLogger("th360.fetcher")


async def fetch_firecrawl(src: dict) -> RawEvidence | None:
    """§2 — Firecrawl-backed sources; failures surface classified reason."""
    from ..scrapers.firecrawl_adapter import FirecrawlAdapter
    try:
        evidence = await FirecrawlAdapter().run(src)
    except SourceUnavailable as e:
        log.error("SOURCE_UNAVAILABLE source=%s detail=%s", src.get("id"), e)
        return None
    if not evidence:
        return None
    # Multi-item results (search mode): carry bundle hash; per-article
    # splitting still happens downstream in the store (article mode).
    if len(evidence) == 1:
        return evidence[0]
    joined = "\n\n---\n\n".join(ev.raw_text for ev in evidence)
    first = evidence[0]
    return RawEvidence(
        source_id=first.source_id, url=first.url, fetched_at=first.fetched_at,
        content_hash=hashlib.sha256(joined.encode()).hexdigest(),
        raw_text=joined, metadata=first.metadata,
    )


def _evidence_from_text(src: dict, text: str, url: str) -> RawEvidence:
    h = hashlib.sha256(text.encode()).hexdigest()
    return RawEvidence(
        source_id=src["id"],
        url=url,
        fetched_at=utcnow_iso(),
        content_hash=h,
        raw_text=text,
        metadata={
            "reliability": src.get("reliability", "UNKNOWN"),
            "authority": src.get("authority", "SECONDARY"),
            "independence_group": src.get("independence_group", src["id"]),
            "type": src.get("type", "news"),
        },
    )


async def fetch(client: httpx.AsyncClient | None, src: dict) -> RawEvidence | None:
    method = src.get("method", "api")
    if method in ("firecrawl", "firecrawl_search"):
        return await fetch_firecrawl(src)   # §2 — budget-guarded adapter
    try:
        if method == "file":
            path = Path(src["path"])
            if not path.is_absolute():
                path = SEED_ROOT / path
            text = path.read_text(encoding="utf-8")
            return _evidence_from_text(src, text, url=f"file://{path}")

        url = src["url"]
        headers = {"User-Agent": "ThreatHunter360Bot/1.0 (+robots-txt-compliant)"}
        if src.get("requires_auth") and src.get("auth_token"):
            headers["Authorization"] = f"Bearer {src['auth_token']}"
        own_client = client is None
        try:
            if client is None:
                client = httpx.AsyncClient()
            r = await client.get(url, timeout=15, headers=headers, follow_redirects=True)
            r.raise_for_status()
            return _evidence_from_text(src, r.text, url=url)
        finally:
            if own_client:
                await client.aclose()
    except Exception as e:  # §20 — classify, never fabricate
        log.error("SOURCE_UNAVAILABLE source=%s detail=%s", src.get("id"), e)
        return None


def run_fetch(src: dict) -> RawEvidence | None:
    """Sync wrapper for tests / seed scripts."""
    import asyncio

    return asyncio.run(_fetch_one(src))


async def _fetch_one(src: dict) -> RawEvidence | None:
    async with httpx.AsyncClient() as client:
        return await fetch(client, src)
