"""API integration tests — spec Part 1.4-1.7 + feed/graph endpoints."""
import asyncio

from app.scraper.orchestrator import load_sources, run_pipeline
from app.store.db import reset_store


def run(coro):
    return asyncio.run(coro)


def test_http_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    # isolated store + seed
    reset_store(str(tmp_path / "api.db"))
    from app.store.db import get_store
    run(run_pipeline(get_store(), load_sources()))
    client = TestClient(app)

    r = client.get("/healthz")
    assert r.status_code == 200

    r = client.post("/api/v1/factcheck",
                    json={"claim": "Company X was sanctioned in August 2026"})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "MOSTLY_TRUE"
    assert body["sources_independent"] < body["sources_total"]
    assert body["interpretation"].startswith("INFERENCE:")
    assert body["key_evidence"]
    check_id = body["check_id"]

    # contract fields (§19)
    for field in ("answer", "confidence", "contradictions",
                  "recommended_action", "what_would_change_conclusion",
                  "reasoning_trace"):
        assert field in body

    # Recent feed
    r = client.get("/api/v1/feed/recent")
    assert any(c["check_id"] == check_id for c in r.json())

    # Statistics
    stats = client.get("/api/v1/feed/statistics").json()
    assert stats["total_checks"] >= 1
    assert stats["evidence_items"] > 0

    # Graph view for the case
    g = client.get(f"/api/v1/graph/case/{check_id}").json()
    assert any(n["type"] == "Claim" for n in g["nodes"])
    assert any(n["type"] == "Evidence" for n in g["nodes"])
    assert any(n["type"] == "Hypothesis" for n in g["nodes"])

    # Journey
    r = client.post("/api/v1/journey/assess",
                    json={"origin": "Lagos", "destination": "Ibadan",
                          "departure_time": "2026-08-24T21:00:00Z"})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "COMPLETE"
    assert j["risk_timeline"]

    # KYC fixture
    fx = client.get("/api/v1/kyc/fixtures").json()["fixtures"]
    scenario4 = next(f for f in fx if f["id"] == "kyc-fix-002")
    r = client.post("/api/v1/kyc/verify", json=scenario4)
    assert r.status_code == 200
    assert r.json()["decision"] == "VERIFIED_WITH_ADDITIONAL_REVIEW"

    # Validation error path (§20 — never fabricated)
    r = client.post("/api/v1/factcheck", json={"claim": "  "})
    assert r.status_code == 422
