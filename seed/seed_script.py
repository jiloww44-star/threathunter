#!/usr/bin/env python3
"""Demo seeder — spec Part 10.5.

Usage:
    python seed/seed_script.py                 # ingest demo pack
    python seed/seed_script.py --confirm       # add official Company X
                                               # confirmation (scenario 5)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.scraper.orchestrator import run_pipeline  # noqa: E402
from app.store.db import get_store  # noqa: E402


async def main(confirm: bool = False):
    store = get_store()
    stats = await run_pipeline(store)
    print(f"✅ Seed pack ingested: {stats}")

    if confirm:
        extra = [{
            "id": "demo_gazette_official_confirm",
            "type": "regulatory",
            "method": "file",
            "path": "fixtures/sanctions_feed_confirmation.json",
            "reliability": "HIGH",
            "authority": "PRIMARY",
            "independence_group": "government",
        }]
        stats2 = await run_pipeline(store, extra)
        print(f"✅ Official confirmation ingested (scenario 5): {stats2}")

    print("✅ Demo environment ready — see seed/demo_scenarios.md")


if __name__ == "__main__":
    asyncio.run(main(confirm="--confirm" in sys.argv))
