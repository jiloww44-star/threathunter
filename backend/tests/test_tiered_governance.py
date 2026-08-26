"""Part 18 D1 tiered review routing + §Willison U1 source health (TRUST.md)."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
import sys
sys.path.insert(0, str(REPO))   # demo/ namespace package importable   # noqa: E402
sys.path.insert(0, str(ROOT))                                          # noqa: E402

from app.core.review_routing import (AUTO_PUBLISH, AUDIT_SAMPLE,  # noqa: E402
                                     MANDATORY_REVIEW, route_review,
                                     stakes_for_module)
from app.core.reasoning_engine import ReasoningEngine            # noqa: E402
from app.models.schemas import Confidence, Contradiction, RiskLevel  # noqa: E402
from app.scraper.orchestrator import load_sources, run_pipeline  # noqa: E402
from app.scraper.source_health import score_sources              # noqa: E402
from app.store.db import reset_store                              # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _contra(n: int, sev=RiskLevel.MODERATE) -> list[Contradiction]:
    return [Contradiction(description=f"c{i}", evidence_a_id=f"a{i}",
                          evidence_b_id=f"b{i}", severity=sev)
            for i in range(n)]


# ------------------------------------------------------------- D1 matrix ----
class TestReviewRoutingMatrix:
    def test_two_contradictions_always_mandatory(self):
        r = route_review(confidence=Confidence.VERY_HIGH,
                         contradictions=_contra(2),
                         sources_independent=3, sources_total=4)
        assert r.tier == MANDATORY_REVIEW and r.enqueued
        assert "contradictions" in r.reason

    def test_copy_chain_dominance_mandatory(self):
        r = route_review(confidence=Confidence.HIGH, contradictions=[],
                         sources_independent=1, sources_total=14)
        assert r.tier == MANDATORY_REVIEW
        assert "copy-chain" in r.reason

    def test_uncertainty_firewall_moderate(self):
        r = route_review(confidence=Confidence.MODERATE, contradictions=[],
                         sources_independent=3, sources_total=4)
        assert r.tier == MANDATORY_REVIEW
        assert "firewall" in r.reason

    def test_high_stakes_stays_human_gated(self):
        """Journey/KYC-class surfaces: HIGH conf + HIGH stakes → review."""
        r = route_review(confidence=Confidence.VERY_HIGH, contradictions=[],
                         sources_independent=3, sources_total=3,
                         stakes=stakes_for_module("journey"),
                         module="journey")
        assert r.tier == MANDATORY_REVIEW and stakes_for_module("kyc") == "high"

    def test_high_conf_low_stakes_auto_publish(self):
        r = route_review(confidence=Confidence.HIGH, contradictions=[],
                         sources_independent=3, sources_total=4,
                         sampler=lambda: 0.5)
        assert r.tier == AUTO_PUBLISH and not r.enqueued

    def test_audit_sample_is_five_percent_and_disclosed(self):
        # sampler below 0.05 → sampled; above → auto-published
        r1 = route_review(confidence=Confidence.HIGH, contradictions=[],
                          sources_independent=3, sources_total=4,
                          sampler=lambda: 0.049)
        r2 = route_review(confidence=Confidence.HIGH, contradictions=[],
                          sources_independent=3, sources_total=4,
                          sampler=lambda: 0.50)
        assert r1.tier == AUDIT_SAMPLE and "5%" in r1.reason
        assert r2.tier == AUTO_PUBLISH


# ------------------------------------------------------- engine wiring ------
def test_factcheck_persists_disclosed_route(store):
    run(run_pipeline(store, load_sources()))
    # airport fixture pack absent → scenario 1 verdict with contradictions
    r = run(ReasoningEngine(store).run_full_pipeline(
        "Company X was sanctioned in August 2026"))
    assert r.review_route in (
        AUTO_PUBLISH, AUDIT_SAMPLE, MANDATORY_REVIEW)
    q = [q for q in store.review_queue() if q["case_ref"] == r.check_id]
    if len(r.contradictions) >= 2:
        assert r.review_route == MANDATORY_REVIEW
        assert q and q[0]["tier"] == MANDATORY_REVIEW
    else:
        assert not q or q[0]["tier"] == AUDIT_SAMPLE


def test_airport_case_routes_mandatory(store):
    """13 release-vs-announcement contradictions → always humans (§D1)."""
    import demo.e2e_free_stack_demo as e2e
    run(e2e.ensure_airport_evidence(store))
    r = run(ReasoningEngine(store).run_full_pipeline(e2e.CLAIM))
    assert r.review_route == MANDATORY_REVIEW
    q = [q for q in store.review_queue() if q["case_ref"] == r.check_id]
    assert q and q[0]["tier"] == MANDATORY_REVIEW
    assert "contradictions" in q[0]["reason"]


# ------------------------------------------------------------- U1  health ----
def _backdate(store, source_id: str, hours: float):
    ts = (datetime.now(timezone.utc).timestamp() - hours * 3600)
    ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    with store._lock:
        store._conn.execute(
            "UPDATE sources_meta SET last_success_at=? WHERE source_id=?",
            (ts_iso, source_id))
        store._conn.commit()


def test_source_health_demotes_stale_primary(store):
    run(run_pipeline(store, load_sources()))
    # gazette is PRIMARY; make it 10 days stale (default SLA 48h)
    _backdate(store, "demo_gazette_official", hours=24 * 10)
    card = {h.source_id: h for h in score_sources(store)}
    g = card["demo_gazette_official"]
    # the SLA is a HARD gate: demotion fires even when composite health
    # stays above the soft threshold (§1.10 freshness is non-negotiable)
    assert not g.fresh_ok and g.action == "demoted"
    meta = store.source_meta("demo_gazette_official")
    assert meta["authority"] == "SECONDARY"
    assert "auto-demoted" in meta["health_note"]
    q = [q for q in store.review_queue() if q["case_ref"]
         == "demo_gazette_official"]
    assert q and q[0]["tier"] == "CURATOR_REVIEW"    # human reviews demotions


def test_source_health_recovers_on_freshening(store):
    run(run_pipeline(store, load_sources()))
    _backdate(store, "demo_gazette_official", hours=24 * 10)
    score_sources(store)
    assert store.source_meta("demo_gazette_official")["authority"] == "SECONDARY"
    _backdate(store, "demo_gazette_official", hours=1)      # fetched again
    card = {h.source_id: h for h in score_sources(store)}
    g = card["demo_gazette_official"]
    assert g.action == "recovered"
    assert store.source_meta("demo_gazette_official")["authority"] == "PRIMARY"


def test_copy_chain_source_flagged(store):
    """The syndication pack: 12 of 13 wire copies near-identical → copy_rate."""
    import demo.e2e_free_stack_demo as e2e
    run(e2e.ensure_airport_evidence(store))
    card = {h.source_id: h for h in score_sources(store)}
    assert card["airport_wire_syndication"].copy_rate > 0.8
    assert card["airport_gov_portal"].copy_rate == 0.0


# ------------------------------------------------------------ queue tiers ---
def test_kyc_items_labeled_mandatory(seeded):
    """Identity decisions are never sampled — §Willison named constraint."""
    from app.core.kyc import verify_identity
    from app.models.schemas import (KYCDocumentExtraction, KYCUserInput,
                                    KYCVerifyRequest)
    req = KYCVerifyRequest(
        document=KYCDocumentExtraction(
            name="Daniel Mensah", dob="2008-11-02",
            issue_date="2020-05-20", expiry_date="2030-05-19"),
        user_input=KYCUserInput(name="Daniel Mensah", dob="2008-11-02"),
        selfie_ref="mock:pass")
    r = run(verify_identity(req, seeded))
    q = [q for q in seeded.review_queue() if q["case_ref"] == r.case_id]
    assert q and all(item["tier"] == "MANDATORY_REVIEW" for item in q)
