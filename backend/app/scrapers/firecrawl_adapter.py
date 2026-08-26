"""Firecrawl adapter — spec §2 (Free-Tier Stack Integration).

Augments the fetcher for sources needing JS rendering / clean markdown.
Flow: Celery beat (Part 4) → registry method: firecrawl[_search] → markdown
→ existing extraction (unchanged) → signals → evidence store.

Credits are finite: every call goes through the budget engine as purpose
`firecrawl:<source_id>` (§2.4), so exhaustion → SOURCE_DEGRADED (visible
staleness, never silent, §1.10/§20).
"""
from __future__ import annotations

import hashlib
import logging
import os

import httpx

from ..core.budget import BudgetExceeded, get_budget
from ..core.nlp_lite import utcnow_iso
from ..scraper.models import RawEvidence, SourceUnavailable

log = logging.getLogger("th360.firecrawl")
FIRECRAWL_API = "https://api.firecrawl.dev/v1"

# §2.4 accounting: 1 scrape-credit ≈ $0.01 in the ledger
FIRECRAWL_COST_PER_CALL_USD = 0.01


class FirecrawlAdapter:
    def __init__(self, api_key: str | None = None,
                 cost_per_call: float = FIRECRAWL_COST_PER_CALL_USD,
                 budget_guard: bool = True):
        self.key = api_key if api_key is not None else \
            os.getenv("FIRECRAWL_API_KEY", "")
        self.cost_per_call = cost_per_call
        # Internal §2.4 guard is on by default (production path). Demo/e2e
        # callers wrap run() in their own llm_budget(tx) (spec §2.1) and pass
        # False so one call = ONE ledger entry (no double reserve).
        self.budget_guard = budget_guard

    @property
    def available(self) -> bool:
        return bool(self.key)

    async def run(self, source_cfg: dict, entity: str | None = None) -> list[RawEvidence]:
        if not self.available:
            raise SourceUnavailable(
                "FIRECRAWL_API_KEY not configured — source degraded, "
                "evidence store keeps last known state (§20)")
        fc = source_cfg["firecrawl"]
        headers = {"Authorization": f"Bearer {self.key}"}

        if fc["mode"] == "scrape":
            payload = {
                "url": fc["url"],
                "formats": fc.get("formats", ["markdown"]),
                "onlyMainContent": fc.get("only_main_content", True),
            }
            endpoint = "/scrape"
        elif fc["mode"] == "search":
            payload = {
                "query": fc["query_template"].format(entity=entity or ""),
                "limit": fc.get("limit", 10),
            }
            endpoint = "/search"
        else:
            payload = {"url": fc["url"], "limit": fc.get("crawl_limit", 50)}
            endpoint = "/crawl"

        # §2.4 — credit budget guard (ties into the budget engine)
        purpose = f"firecrawl:{source_cfg['id']}"
        try:
            if self.budget_guard:
                async with get_budget().allocate(
                        purpose, "firecrawl-credit", self.cost_per_call):
                    async with httpx.AsyncClient(timeout=60) as c:
                        r = await c.post(f"{FIRECRAWL_API}{endpoint}",
                                         json=payload, headers=headers)
                    r.raise_for_status()
            else:  # caller holds the outer llm_budget(tx) (spec §2.1)
                async with httpx.AsyncClient(timeout=60) as c:
                    r = await c.post(f"{FIRECRAWL_API}{endpoint}",
                                     json=payload, headers=headers)
                r.raise_for_status()
        except BudgetExceeded as e:
            log.warning("firecrawl credits exhausted for %s", source_cfg["id"])
            raise SourceUnavailable(f"scraping credit exhausted: {e}") from e
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"firecrawl call failed: {e}") from e

        data = r.json().get("data", [])
        out: list[RawEvidence] = []
        for item in (data if isinstance(data, list) else [data]):
            markdown = item.get("markdown") or item.get("content") or ""
            if not markdown.strip():
                continue
            url = (item.get("metadata") or {}).get("sourceURL") or \
                fc.get("url", "")
            out.append(RawEvidence(
                source_id=source_cfg["id"],
                url=url,
                fetched_at=utcnow_iso(),
                content_hash=hashlib.sha256(
                    f"{url}|{markdown}".encode()).hexdigest(),
                raw_text=markdown,
                metadata={
                    "reliability": source_cfg.get("reliability", "UNKNOWN"),
                    "authority": source_cfg.get("authority", "SECONDARY"),
                    "independence_group":
                        # §2.2 search mode: group assigned after domain check
                        self._independence_group(source_cfg, url),
                    "type": source_cfg.get("type", "news"),
                },
            ))
        return out

    @staticmethod
    def _independence_group(source_cfg: dict, url: str) -> str:
        """§2.2 — dynamic groups: domain-derived group for search results so
        syndicated copies across that domain collapse into one source."""
        g = source_cfg.get("independence_group", source_cfg["id"])
        if g == "dynamic":
            from urllib.parse import urlparse
            host = urlparse(url).hostname or source_cfg["id"]
            return f"{source_cfg['id']}:{host}"
        return g
