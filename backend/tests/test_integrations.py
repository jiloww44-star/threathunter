"""Integration tests — OSM §1, Firecrawl §2, analytics §4."""
import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.core.journey import JourneyRequest, assess_journey, build_risk_timeline_live
from app.scrapers.firecrawl_adapter import FirecrawlAdapter
from app.services.geo import GeoService, _haversine_km
from app.services.routing import RoutingService


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- OSM §1 --
def test_gazetteer_offline_geocode():
    geo = GeoService(offline=True, rate_pause=0.0)
    hit = run(geo.geocode("Lagos"))
    assert hit and abs(hit["lat"] - 6.5244) < 0.01
    assert hit["source"] == "offline-gazetteer"


def test_geocode_cache_single_flight():
    geo = GeoService(offline=True, rate_pause=0.0)

    async def _gather():
        return await asyncio.gather(*[geo.geocode("Ibadan") for _ in range(3)])
    r = run(_gather())
    assert len(geo._cache) == 1 and all(h == r[0] for h in r)


def test_haversine():
    a = {"lat": 6.5244, "lon": 3.3792}      # Lagos
    b = {"lat": 7.3775, "lon": 3.9470}      # Ibadan (~117 km)
    assert 105 < _haversine_km(a, b) < 135


def test_routing_offline_returns_none():
    routing = RoutingService(offline=True)
    assert run(routing.route({"lon": 3.37, "lat": 6.52},
                             {"lon": 3.95, "lat": 7.38})) is None


def test_journey_live_falls_back_without_network(
        monkeypatch, tmp_path):
    """§20 — OSM down → fixture corridor with visible data_mode marker."""
    import app.core.journey as J
    import app.services.geo as G
    import app.services.routing as R
    monkeypatch.setattr(J, "get_geo", lambda: GeoService(offline=True, rate_pause=0.0))
    monkeypatch.setattr(J, "get_routing", lambda: RoutingService(offline=True))
    # offline still geocodes Lagos/Ibadan but routing returns None → fallback
    req = JourneyRequest(origin="Lagos", destination="Ibadan",
                         departure_time=datetime(2026, 8, 24, 7, 0,
                                                 tzinfo=timezone.utc))
    resp = run(assess_journey(req))
    assert resp.status == "COMPLETE"
    assert resp.data_mode == "offline-fixture"
    assert resp.route_geometry is None
    assert any("fixture corridor" in t for t in resp.reasoning_trace)


def test_incident_records_have_coords():
    from app.core.journey import _incident_records
    recs = _incident_records()
    assert recs and all("lat" in r and "lon" in r for r in recs)


def test_incidents_near_km42_night_only():
    from app.core.journey import _incidents_near
    night = _incidents_near({"lat": 6.825, "lon": 3.62}, 5.0, "night")
    day = _incidents_near({"lat": 6.825, "lon": 3.62}, 5.0, "day")
    assert len(night) >= 3 and len(day) == 0     # night-weighted corridor


# ---------------------------------------------------------- Firecrawl §2 --
def test_firecrawl_no_key_is_source_unavailable(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    adapter = FirecrawlAdapter(api_key="")
    with pytest.raises(SourceUnavailable):
        run(adapter.run({"id": "x", "firecrawl": {"mode": "scrape",
                                                  "url": "https://e.gov"}}))


from app.scraper.models import SourceUnavailable  # noqa: E402


def test_firecrawl_mocked_search_maps_to_evidence(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{
                "markdown": "# Company X sanctioned\nCompany X was sanctioned.",
                "metadata": {"sourceURL": "https://press.example/a1"},
            }]}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return FakeResp()

    import app.scrapers.firecrawl_adapter as F
    monkeypatch.setattr(F.httpx, "AsyncClient", FakeClient)
    from app.core.budget import BudgetEngine
    eng = BudgetEngine()
    monkeypatch.setattr(F, "get_budget", lambda: eng)
    adapter = FirecrawlAdapter(api_key="fake")
    ev = run(adapter.run(
        {"id": "news_discovery", "reliability": "MODERATE",
         "authority": "SECONDARY", "independence_group": "dynamic",
         "firecrawl": {"mode": "search",
                       "query_template": '"{entity}" sanction',
                       "limit": 5}},
        entity="Company X"))
    assert len(ev) == 1
    assert ev[0].metadata["independence_group"].startswith(
        "news_discovery:press.example")     # §2.2 dynamic domain grouping
    # ledger recorded the credit spend
    assert eng.summary()["calls"] >= 1


# ---------------------------------------------------------- Analytics §4 --
def test_analytics_daily_shape(tmp_path):
    from app.store.db import EvidenceStore
    store = EvidenceStore(str(tmp_path / "a.db"))
    store.record_check("factcheck", "c", "MOSTLY_TRUE", "HIGH",
                       {"sources_independent": 2, "sources_total": 3})
    store.record_check("kyc", "k", "VERIFIED", "HIGH", {})
    store.insert_budget_tx({
        "id": "t1", "purpose": "factcheck", "model_id": "openai/gpt-4o",
        "est_nano": 15_000_000, "actual_nano": 10_000_000,
        "mode": "STANDARD",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")})
    rows = store.analytics_daily(days=30)
    assert rows, "analytics_daily must return today's row"
    row = rows[-1]
    assert row["checks_total"] == 2
    assert row["kyc_cases"] == 1
    assert row["llm_cost_usd"] == 0.01
    assert 0.60 <= row["avg_source_diversity"] <= 0.70


def test_analytics_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.store.db import reset_store
    reset_store(str(tmp_path / "api2.db"))
    from app.store.db import get_store
    get_store().record_check("factcheck", "c", "VERIFIED", "HIGH",
                             {"sources_independent": 1, "sources_total": 1})
    client = TestClient(app)
    r = client.get("/api/v1/admin/analytics/summary?days=30")
    assert r.status_code == 200
    j = r.json()
    assert "daily" in j and "kpis" in j and "budget" in j
    assert "avg_source_diversity" in j["daily"][-1]
    r = client.get("/api/v1/admin/analytics/export?format=csv&days=30")
    assert r.status_code == 200
    assert "checks_total" in r.text
