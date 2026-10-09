#!/usr/bin/env python3
"""End-to-end demo — spec §Self-Hosted Geo Stack + End-to-End Demo, Part 2:

    "Governor announces new airport in Lagos"
    Exercises: Firecrawl sourcing → OpenRouter reasoning → OSM journey →
               budget tracking → analytics export.

Stages (traceability §2.3):
  1. Evidence sourcing via Firecrawl + budget-guarded credits. Without a
     FIRECRAWL_API_KEY (demo/CI profile) the source degrades visibly (§20)
     and the run falls back to the pack's cached evidence — the "last
     successful fetch" banner is printed with a real age, never fabricated.
  2. Fact check through the inductive pipeline (OpenRouter narrative when an
     OPENROUTER_API_KEY is configured; deterministic templates otherwise).
  3. Journey assessment via the OSM stack (Nominatim→OSRM live geometry, or
     the offline fixture corridor with data_mode=offline-fixture).
  4. Budget trail — every reserve→settle call attributed to this case via
     app.budget.context.current_case_id (§2.1).
  5. Analytics sheet export (§4.2 Daily sheet → CSV).

Failure-mode demonstrations (§2.4, run with --inject-fault):
  osrm-down           the routing answer becomes UNDETERMINED with a clear
                      message; no timeline is fabricated.
  firecrawl-exhausted credit cap injected; sources marked degraded and the
                      staleness banner appears; the check still runs on
                      cached evidence.

Usage:
  python demo/e2e_free_stack_demo.py [--offline] [--departure 18:30]
      [--inject-fault {osrm-down|firecrawl-exhausted}]
      [--out demo_analytics.csv] [--days 7] [--db PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time as _time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.api.routes.admin import build_daily_csv                     # noqa: E402
from app.budget.context import current_case_id                       # noqa: E402
from app.budget.guard import BudgetExceeded, demo_tenant_ctx, llm_budget  # noqa: E402
from app.core.budget import get_budget                               # noqa: E402
from app.core.journey import (_bucket_of_time, _hedged_note,         # noqa: E402
                              assess_journey)
from app.core.reasoning_engine import ReasoningEngine                # noqa: E402
from app.models.schemas import JourneyRequest                        # noqa: E402
from app.scraper.orchestrator import run_pipeline                    # noqa: E402
from app.scraper.models import SourceUnavailable                     # noqa: E402
from app.scrapers.firecrawl_adapter import FirecrawlAdapter          # noqa: E402
from app.services.geo import GeoService                              # noqa: E402
from app.services.routing import RoutingService                      # noqa: E402
from app.store.db import get_store, reset_store                      # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# §2.1 — the scenario claim and the demo-pack evidence pack that stands in
# for the live Firecrawl results when no key is configured (honest §20
# stand-in, flagged at every print site).
CLAIM = ("The Governor announced construction of a new international "
         "airport in Lagos")

AIRPORT_SOURCES = [
    {
        "id": "airport_gov_portal",
        "type": "regulatory",
        "method": "file",
        "path": str(FIXTURES / "airport_press_release.json"),
        "reliability": "HIGH",
        "authority": "PRIMARY",
        "independence_group": "government",
    },
    {
        "id": "airport_wire_syndication",
        "type": "news",
        "method": "file",
        "path": str(FIXTURES / "airport_wire_syndication.json"),
        "reliability": "MODERATE",
        "authority": "SECONDARY",
        # All 13 outlets re-ran one wire dispatch quoting the same release —
        # ONE effective source by §1.6, however many hosts carried it.
        "independence_group": "press_syndication",
    },
]

# Registry used on stage 1 exactly as §2.1/§2.2 define it (firecrawl_search
# registry extension); authority kept for the engine's PRIMARY boost.
FIRECRAWL_SOURCES = [
    {
        "id": "gov_portal",
        "authority": "PRIMARY",
        "reliability": "HIGH",
        "type": "regulatory",
        "independence_group": "government",
        "firecrawl": {"mode": "search",
                      "query_template": '"Lagos State Government" '
                                        'airport announcement',
                      "limit": 8},
    },
    {
        "id": "news_aggregators",
        "authority": "SECONDARY",
        "reliability": "MODERATE",
        "type": "news",
        "independence_group": "dynamic",     # §2.2 post-domain grouping
        "firecrawl": {"mode": "search",
                      "query_template": '"Lagos State Government" airport',
                      "limit": 10},
    },
]

# Cache stand-in mapping: source id → fixture pack source id
_CACHED = {"gov_portal": "airport_gov_portal",
           "news_aggregators": "airport_wire_syndication"}


@dataclass
class DemoOut:
    """Captured output lines — tests assert against this and main() prints."""
    lines: list[str] = field(default_factory=list)

    def write(self, text: str = ""):
        self.lines.append(text)
        print(text)


async def ensure_airport_evidence(store) -> dict:
    """Seed the demo pack's airport evidence idempotently — this is the
    'last known good' cache state the degraded source falls back to (§20)."""
    have = {e.get("source_id") for e in store.all_evidence()}
    missing = [s for s in AIRPORT_SOURCES if s["id"] not in have]
    if missing:
        stats = await run_pipeline(store, missing)
        return {"seeded": [s["id"] for s in missing], "stats": stats}
    return {"seeded": [], "stats": None}


def _cached_counts(store) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in store.all_evidence():
        counts[e.get("source_id")] = counts.get(e.get("source_id"), 0) + 1
    return counts


def _staleness(store, source_id: str) -> str:
    meta = store.source_meta(_CACHED[source_id])
    last = (meta or {}).get("last_success_at")
    hours = None
    if last:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hours = max(0, int((_time.time() - dt.timestamp()) / 3600))
        except Exception:
            hours = None
    if hours is None:
        return "last successful fetch unknown"
    return f"last successful fetch {hours}h ago"


async def stage1_evidence(out: DemoOut, ctx, store, fault: str | None):
    out.write("═══ STAGE 1: Evidence sourcing via Firecrawl ═══")
    # §2.4 fault injection: firecrawl allocation cap → exhausted credits
    eng = get_budget()
    firecaps = eng._cfg.setdefault("purposes", {})
    saved = firecaps.get("firecrawl")
    if fault == "firecrawl-exhausted":
        firecaps["firecrawl"] = {"daily_cap_usd": 0.0, "monthly_cap_usd": 0.0,
                                 "min_free_only_when_capped": True}
        out.write("  [fault injected] firecrawl daily cap set to $0.00 "
                  "(simulating exhausted free-tier credits)")
    try:
        cached = _cached_counts(store)
        for src in FIRECRAWL_SOURCES:
            purpose = f"firecrawl:{src['id']}"
            try:
                async with llm_budget(ctx, purpose=purpose,
                                      model_id="firecrawl-credit",
                                      est_cost_usd=0.01):
                    evs = await FirecrawlAdapter(budget_guard=False).run(
                        {**src, "firecrawl": src["firecrawl"]},
                        entity="Lagos State Government")
                out.write(f"  {src['id']}: {len(evs)} documents (live)")
            except BudgetExceeded as e:
                # §2.4 → mark_source_degraded, staleness banner (§20)
                store.upsert_source_meta(
                    {"id": src["id"], **src}, ok=False, error=str(e))
                n = cached.get(_CACHED[src["id"]], 0)
                out.write(f"  {src['id']}: scraping credit exhausted — "
                          f"source marked DEGRADED")
                out.write(f"    ↳ Source {src['id']} is stale "
                          f"({_staleness(store, src['id'])}) — "
                          f"cached evidence stands: {n} documents")
            except SourceUnavailable as e:
                store.upsert_source_meta(
                    {"id": src["id"], **src}, ok=False, error=str(e))
                n = cached.get(_CACHED[src["id"]], 0)
                out.write(f"  {src['id']}: {n} documents "
                          f"(cached fixtures — live fetch degraded: "
                          f"FIRECRAWL_API_KEY not set)")
                out.write(f"    ↳ staleness banner: Source {src['id']} is "
                          f"stale ({_staleness(store, src['id'])})")
    finally:
        if saved is None:
            firecaps.pop("firecrawl", None)
        else:
            firecaps["firecrawl"] = saved


async def stage2_factcheck(out: DemoOut, ctx, store, case_id: str):
    out.write("\n═══ STAGE 2: Fact check via OpenRouter ═══")
    engine = ReasoningEngine(store)
    token = current_case_id.set(case_id)     # cost attribution (§2.1)
    try:
        result = await engine.run_full_pipeline(CLAIM, user=ctx.user)
    finally:
        current_case_id.reset(token)

    out.write(f"  Claim:      \"{result.claim}\"")
    out.write(f"  Verdict:    {result.verdict.value}")
    out.write(f"  Confidence: {result.confidence.value}")
    out.write(f"  Sources:    {result.sources_independent} independent "
              f"of {result.sources_total}")
    if result.copy_chain_clusters is not None:
        out.write(f"  Copy-chains detected: {result.copy_chain_clusters} "
                  f"clusters ({result.copy_chain_note})")
    if result.ai_narrative:
        out.write(f"  AI narrative: OpenRouter "
                  f"{result.ai_narrative['model_used']} "
                  f"(budget mode {result.ai_narrative['mode']})")
    else:
        out.write("  AI narrative: deterministic template stands "
                  "(OpenRouter key absent — no fabricated text, §20)")
    dup = sum(1 for e in result.key_evidence if e.is_duplicate_copy)
    if dup:
        out.write(f"  Note: {dup} syndicated copies collapsed by §1.6 "
                  f"independence analysis — see reasoning trace")
    return result


async def stage3_journey(out: DemoOut, ctx, case_id: str,
                         departure: str, fault: str | None, offline: bool):
    out.write("\n═══ STAGE 3: Journey assessment via OSM stack ═══")
    origin, destination = "Ikeja, Lagos", "Victoria Island, Lagos"

    if fault == "osrm-down":
        # §2.4 — kill the geo stack entirely: geocoding + routing + fixtures
        # all unavailable. The honest answer is UNDETERMINED — never a
        # fabricated timeline.
        geo = GeoService(offline=True, rate_pause=0.0, gazetteer={})
        routing = RoutingService(offline=True)
        o = await geo.geocode(origin)
        d = await geo.geocode(destination)
        route = await routing.route(o, d) if (o and d) else None
        out.write("  [fault injected] OSRM/Nominatim stopped "
                  "(docker stop th360-osrm)")
        if not route:
            out.write("  Routing service unavailable — journey risk cannot "
                      "be assessed reliably.")
            out.write("  Verdict: UNDETERMINED — no timeline fabricated (§20)")
            return None
    token = current_case_id.set(case_id)
    try:
        if offline:
            # deterministic demo/CI profile (public endpoints unreachable)
            import app.core.journey as J
            J.get_geo = lambda: GeoService(offline=True, rate_pause=0.0)
            J.get_routing = lambda: RoutingService(offline=True)
        hh, mm = departure.split(":")
        from datetime import datetime, timezone
        dep = datetime.now(timezone.utc).replace(
            hour=int(hh), minute=int(mm), second=0, microsecond=0)
        resp = await assess_journey(JourneyRequest(
            origin=origin, destination=destination, departure_time=dep))
    finally:
        current_case_id.reset(token)

    if resp.route_summary:
        rs = resp.route_summary
        out.write(f"  Route: {rs['total_km']} km, {rs['total_min']} min, "
                  f"{len(resp.risk_timeline)} segments "
                  f"(live OSRM geometry, geocoded via Nominatim)")
    else:
        out.write(f"  Route: fixture corridor, {len(resp.risk_timeline)} "
                  f"segments (data_mode={resp.data_mode} — live OSM "
                  f"unreachable; geometry not fabricated, §20)")
    hotspots = [t for t in resp.risk_timeline if t.max_severity != "NONE"]
    out.write(f"  Risk hotspots: {len(hotspots)}")
    for s in hotspots[:3]:
        hour = int(s.time.split(":")[0])
        note = _hedged_note(s.incident_count, 0.0, _bucket_of_time(hour),
                            s.max_severity)
        out.write(f"    · {s.segment} @ {s.time} — {note}")
    if resp.ai_narrative:
        out.write(f"  AI narrative: OpenRouter "
                  f"{resp.ai_narrative['model_used']} "
                  f"(budget mode {resp.ai_narrative['mode']})")
    else:
        out.write("  AI narrative: template hedge stands "
                  "(OpenRouter key absent, §20)")
    return resp


def stage4_budget(out: DemoOut, store, case_id: str):
    out.write("\n═══ STAGE 4: Budget trail ═══")
    txns = store.budget_tx_for_case(case_id)
    total = 0.0
    for t in txns:
        total += t["usd"]
        out.write(f"  {t['purpose']:32} {t['model_id']:38} ${t['usd']:.4f}")
    if not txns:
        out.write("  (no metered calls attributed to this case)")
    out.write(f"  Total attributed to this case: ${total:.4f}")
    out.write("  (attempts without provider keys reserve estimate → settle "
              "$0.00 — the reserve→settle audit is preserved either way)")
    return txns


def stage5_export(out: DemoOut, store, days: int, out_path: Path):
    out.write("\n═══ STAGE 5: Analytics sheet export ═══")
    csv_text = build_daily_csv(store.analytics_daily(days=days))
    out_path.write_text(csv_text, encoding="utf-8")
    out.write(f"  Exported {out_path} — verdict mix, cost/check, source "
              f"diversity columns populated by this run.")
    return out_path


async def run_demo(store=None, *, offline: bool = False, fault: str | None = None,
                   departure: str = "18:30", out_path: str | Path | None = None,
                   days: int = 7) -> dict:
    out = DemoOut()
    store = store or get_store()
    ctx = demo_tenant_ctx()                      # Part 13 sandbox tenant
    case_id = uuid.uuid4().hex                   # one case for the whole run
    out_path = Path(out_path or (REPO / "demo_analytics.csv"))

    # Last-known-good cache state (idempotent) before any sourcing attempt
    await ensure_airport_evidence(store)

    # §2.1 — one audit key spans the whole run: every reserve→settle call
    # below is attributed to this case (Stage 4 joins on it).
    token = current_case_id.set(case_id)
    try:
        await stage1_evidence(out, ctx, store, fault)
        result = await stage2_factcheck(out, ctx, store, case_id)
        journey = await stage3_journey(out, ctx, case_id,
                                       departure, fault, offline)
    finally:
        current_case_id.reset(token)
    txns = stage4_budget(out, store, case_id)
    stage5_export(out, store, days, out_path)

    out.write("\n✅ E2E run complete — every external dependency either "
              "ran live or degraded honestly (§20).")
    return {
        "case_id": case_id,
        "check_id": result.check_id,
        "verdict": result.verdict.value,
        "confidence": result.confidence.value,
        "sources_independent": result.sources_independent,
        "sources_total": result.sources_total,
        "copy_chain_clusters": result.copy_chain_clusters,
        "journey_data_mode": getattr(journey, "data_mode", None),
        "budget_total_usd": round(sum(t["usd"] for t in txns), 6),
        "budget_calls": len(txns),
        "csv": str(out_path),
        "output": "\n".join(out.lines),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--offline", action="store_true",
                    help="skip live network attempts (deterministic CI/demo)")
    ap.add_argument("--departure", default="18:30",
                    help="journey departure HH:MM (default 18:30)")
    ap.add_argument("--inject-fault", choices=["osrm-down",
                                               "firecrawl-exhausted"],
                    default=None, help="§2.4 failure-mode demonstration")
    ap.add_argument("--out", default=None, help="CSV export path")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--db", default=None,
                    help="SQLite path (default: demo db from settings)")
    args = ap.parse_args()

    store = reset_store(args.db) if args.db else get_store()
    summary = asyncio.run(run_demo(store, offline=args.offline,
                                   fault=args.inject_fault,
                                   departure=args.departure,
                                   out_path=args.out, days=args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
