"""Self-Hosted Geo Stack + E2E free-stack demo — spec §Self-Hosted Parts 1-2.

Part 1: config-driven self-host switch (§1.3, zero code change).
Part 2: demo/e2e_free_stack_demo.py five stages + §2.4 failure modes.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO))        # demo/ importable as namespace package
sys.path.insert(0, str(ROOT))

from app.core.reasoning_engine import ReasoningEngine          # noqa: E402
from app.core.budget import get_budget, reset_budget           # noqa: E402
from app.budget.context import current_case_id                 # noqa: E402
from app.models.schemas import JourneyRequest                  # noqa: E402
from app.services.geo import GeoService                        # noqa: E402
from app.services.routing import RoutingService                # noqa: E402
from app.store.db import reset_store                           # noqa: E402
from app.config import PUBLIC_NOMINATIM, PUBLIC_OSRM, settings  # noqa: E402
from app.core.journey import assess_journey                    # noqa: E402

import demo.e2e_free_stack_demo as e2e                         # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def demo_store(tmp_path):
    s = reset_store(str(tmp_path / "demo.db"))
    reset_budget()                    # rebind ledger to the isolated store
    yield s
    s.close()
    reset_budget()


# ------------------------------------------------- Part 1.3 service switch --
class TestSelfHostedSwitch:
    def test_defaults_point_at_public_endpoints(self):
        assert settings.GEO_NOMINATIM_URL == PUBLIC_NOMINATIM
        assert settings.GEO_OSRM_URL == PUBLIC_OSRM
        assert not settings.geo_self_hosted

    def test_public_profile_keeps_fair_use_limits(self):
        geo = GeoService(base_url=PUBLIC_NOMINATIM)
        assert not geo.self_hosted
        assert geo._sem._value == 1            # 1 req/sec fair use (§1.2)
        assert geo.rate_pause == 1.05

    def test_self_hosted_widens_concurrency_and_drops_pause(self):
        geo = GeoService(base_url="http://th360-nominatim:8080")
        assert geo.self_hosted
        assert geo._sem._value == 20           # local = no 1/sec limit (§1.3)
        assert geo.rate_pause == 0.0

    def test_routing_self_hosted_url(self):
        r = RoutingService(base_url="http://th360-osrm:5000")
        assert r.self_hosted and r.osrm_url == "http://th360-osrm:5000"

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("GEO_NOMINATIM_URL", "http://local-nominatim:8080")
        from app.config import Settings
        s = Settings()
        assert s.GEO_NOMINATIM_URL == "http://local-nominatim:8080"
        assert s.geo_self_hosted

    def test_settings_yaml_parse(self):
        from app.config import _settings_yaml
        cfg = _settings_yaml()
        assert "geo" in cfg                  # blank ⇒ public fallback

    def test_compose_geo_file_exists(self):
        compose = REPO / "docker-compose.geo.yml"
        assert compose.exists()
        text = compose.read_text()
        for service in ("nominatim:", "osrm:", "osrm-prep:", "tileserver:"):
            assert service in text
        assert "mediagis/nominatim:4.4" in text
        assert "osrm/osrm-backend" in text
        assert "healthcheck" in text


# ------------------------------------------------------- budget attribution --
def test_case_attribution_via_context(demo_store):
    async def _do():
        token = current_case_id.set("case-demo-1")
        try:
            async with get_budget().allocate("factcheck", "m/free:free", 0.0042):
                pass
            async with get_budget().allocate("journey", "m/free:free", 0.0):
                pass
        finally:
            current_case_id.reset(token)
        async with get_budget().allocate("factcheck", "m/free:free", 0.001):
            pass                                    # unattributed

    run(_do())
    rows = demo_store.budget_tx_for_case("case-demo-1")
    assert len(rows) == 2
    assert rows[0]["purpose"] == "factcheck"
    assert rows[0]["usd"] == pytest.approx(0.0042, abs=1e-6)
    assert rows[1]["usd"] == 0.0                  # free model settles zero
    assert demo_store.budget_tx_for_case("other") == []


# ------------------------------------------------- airport pack correctness --
def test_airport_pack_reproduces_spec_outputs(demo_store):
    """§2.2 — the amplified echo: MISLEADING/HIGH, 2 independent of 14,
    13 syndicated articles tracing to one origin."""
    run(e2e.ensure_airport_evidence(demo_store))
    result = run(ReasoningEngine(demo_store).run_full_pipeline(
        e2e.CLAIM, persist=False))
    assert result.verdict.value == "MISLEADING"
    assert result.confidence.value == "HIGH"
    assert result.sources_independent == 2
    assert result.sources_total == 14
    assert result.copy_chain_clusters == 2
    assert "13 articles" in result.copy_chain_note
    # 13 release-date vs announcement-date conflicts, all MODERATE (§1.8)
    mods = [c for c in result.contradictions if c.severity.value == "MODERATE"]
    assert len(mods) == 13
    assert not any(c.severity.value == "HIGH" for c in result.contradictions)


def test_existing_demo_scenarios_unaffected_by_title_alias(demo_store):
    """§1.9 guard: strict doc↔doc matching kept; weak rumor still UNVERIFIED."""
    from app.scraper.orchestrator import load_sources, run_pipeline
    run(run_pipeline(demo_store, load_sources()))
    r = run(ReasoningEngine(demo_store).run_full_pipeline(
        "A celebrity secretly married in Lagos last week", persist=False))
    assert r.verdict.value == "UNVERIFIED"
    r2 = run(ReasoningEngine(demo_store).run_full_pipeline(
        "Company X was sanctioned in August 2026", persist=False))
    assert r2.verdict.value == "MOSTLY_TRUE"       # demo scenario 1 intact


# -------------------------------------------------- journey fixture corridor --
def test_victoria_island_corridor_hotspot_offline(demo_store):
    import app.core.journey as J
    J.get_geo = lambda: GeoService(offline=True, rate_pause=0.0)
    J.get_routing = lambda: RoutingService(offline=True)
    resp = run(assess_journey(JourneyRequest(
        origin="Ikeja, Lagos", destination="Victoria Island, Lagos",
        departure_time=datetime(2026, 8, 24, 18, 30, tzinfo=timezone.utc))))
    assert resp.status == "COMPLETE"
    assert resp.data_mode == "offline-fixture"
    names = [t.segment for t in resp.risk_timeline]
    assert any("Third Mainland Bridge approach" in n for n in names)
    hotspots = [t for t in resp.risk_timeline if t.max_severity != "NONE"]
    assert hotspots and any(
        "Third Mainland Bridge approach" in t.segment for t in hotspots)


# ------------------------------------------------------------- Part 2 demo --
class TestE2EDemo:
    def test_full_run_offline(self, demo_store, tmp_path):
        out_csv = tmp_path / "demo_analytics.csv"
        summary = run(e2e.run_demo(demo_store, offline=True,
                                   out_path=out_csv))
        o = summary["output"]
        for stage in ("STAGE 1", "STAGE 2", "STAGE 3", "STAGE 4", "STAGE 5"):
            assert stage in o
        assert summary["verdict"] == "MISLEADING"
        assert summary["confidence"] == "HIGH"
        assert summary["sources_independent"] == 2
        assert summary["sources_total"] == 14
        assert summary["copy_chain_clusters"] == 2
        # §2.3 traceability
        assert "staleness banner" in o             # degraded Firecrawl (§20)
        assert "Copy-chains detected: 2 clusters" in o
        assert "Third Mainland Bridge approach" in o
        assert summary["journey_data_mode"] == "offline-fixture"
        # Stage 4: all 4 metered purposes attributed, fully settled
        rows = demo_store.budget_tx_for_case(summary["case_id"])
        purposes = {r["purpose"] for r in rows}
        assert {"firecrawl:gov_portal", "firecrawl:news_aggregators",
                "factcheck", "journey"} <= purposes
        assert all(r["case_id"] == summary["case_id"] for r in rows)
        assert summary["budget_total_usd"] == 0.0  # no keys → settled $0.00
        # Stage 5 CSV with this run visible
        text = out_csv.read_text()
        assert text.splitlines()[0].startswith("day,checks_total")
        assert len(text.strip().splitlines()) >= 2
        # idempotent re-run: no duplicate evidence on second pass
        run(e2e.ensure_airport_evidence(demo_store))
        evs = [e for e in demo_store.all_evidence()
               if e["source_id"].startswith("airport_")]
        assert len(evs) == 14

    def test_fault_osrm_down_is_undetermined(self, demo_store, tmp_path):
        summary = run(e2e.run_demo(demo_store, offline=True,
                                   fault="osrm-down",
                                   out_path=tmp_path / "a.csv"))
        o = summary["output"]
        assert "Routing service unavailable — journey risk cannot be " \
               "assessed reliably." in o
        assert "UNDETERMINED" in o
        assert summary["journey_data_mode"] is None
        # fact check still completed — one dependency failed, not the system
        assert summary["verdict"] == "MISLEADING"

    def test_fault_firecrawl_exhausted_marks_source_degraded(
            self, demo_store, tmp_path):
        summary = run(e2e.run_demo(demo_store, offline=True,
                                   fault="firecrawl-exhausted",
                                   out_path=tmp_path / "b.csv"))
        o = summary["output"]
        assert "scraping credit exhausted" in o
        assert "source marked DEGRADED" in o
        assert "stale (last successful fetch" in o
        # check still ran on cached evidence (§2.4 honesty)
        assert summary["verdict"] == "MISLEADING"
        meta = demo_store.source_meta("gov_portal")
        assert meta and meta["last_error"] is not None

    def test_demo_seed_pack_files(self):
        assert (REPO / "demo/fixtures/airport_press_release.json").exists()
        wire = REPO / "demo/fixtures/airport_wire_syndication.json"
        import json
        doc = json.loads(wire.read_text())
        assert len(doc["articles"]) == 13
