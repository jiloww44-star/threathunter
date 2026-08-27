"""Reasoning engine tests — spec Part 8.2, the critical asset.

Each test encodes a §-reference from the architecture spec.
"""
import asyncio

from app.models.schemas import Confidence, Verdict


def run(coro):
    return asyncio.run(coro)


def test_copy_chain_counts_as_one_source(engine):
    """§1.6 — near-identical claims from one independence group = ONE source."""
    groups = engine._independence_groups([
        {"independence_group": "press", "claim_text": f"Company X sanctioned {i}",
         "evidence_id": f"e{i}"}
        for i in range(5)
    ])
    assert len(groups) == 1  # 5 copies ≠ 5 sources


def test_scenario_1_mostly_true_high_with_contradiction(engine):
    """Demo scenario 1 (Part 10.6): 'Company X sanctioned in August 2026' →
    MOSTLY_TRUE / HIGH, copy-chain collapsed, contradiction flagged."""
    r = run(engine.run_full_pipeline("Company X was sanctioned in August 2026",
                                     persist=False))
    assert r.verdict == Verdict.MOSTLY_TRUE
    assert r.confidence == Confidence.HIGH
    assert r.sources_independent < r.sources_total          # copy chain collapsed
    assert len(r.contradictions) >= 2                        # scope + date conflict
    assert any(c.severity.value == "HIGH" for c in r.contradictions)


def test_contradiction_blocks_very_high(engine):
    """§1.8 / Part 8.2 — unresolved conflicts cap confidence below VERY_HIGH."""
    r = run(engine.run_full_pipeline(
        "Company X was sanctioned in August 2026", persist=False))
    assert r.confidence != Confidence.VERY_HIGH


def test_no_evidence_returns_unverified_not_false(engine):
    """§1.9 — absence of evidence → UNVERIFIED, never FALSE."""
    r = run(engine.run_full_pipeline(
        "The moon base opened a parking garage yesterday", persist=False))
    assert r.verdict == Verdict.UNVERIFIED
    assert r.confidence == Confidence.UNDETERMINED


def test_rumor_single_weak_source_is_unverified(engine):
    """§1.9 — a single anonymous-source rumor is not corroboration."""
    r = run(engine.run_full_pipeline(
        "A celebrity secretly married in Lagos last week", persist=False))
    assert r.verdict == Verdict.UNVERIFIED


def test_primary_source_single_is_provisional(engine):
    """§1.6 — one effective source, even PRIMARY, yields PARTIALLY_TRUE."""
    r = run(engine.run_full_pipeline(
        "Vendor Y lost its operating license in March 2026", persist=False))
    assert r.verdict == Verdict.PARTIALLY_TRUE


def test_reassessment_upgrades_with_primary(engine, seeded):
    """§1.10 / demo scenario 5 — ingesting an official confirmation upgrades
    the same claim to VERIFIED / VERY_HIGH."""
    extra = [{
        "id": "gazette_confirm",
        "method": "file", "path": "fixtures/sanctions_feed_confirmation.json",
        "reliability": "HIGH", "authority": "PRIMARY",
        "independence_group": "government",
    }]
    import asyncio
    from app.scraper.orchestrator import run_pipeline
    asyncio.run(run_pipeline(seeded, extra))
    r = run(engine.run_full_pipeline(
        "Company X was sanctioned in August 2026", persist=False))
    assert r.verdict == Verdict.VERIFIED
    assert r.confidence == Confidence.VERY_HIGH


def test_reasoning_trace_present(engine):
    """§19 — analysts can expand a full reasoning trace."""
    r = run(engine.run_full_pipeline(
        "Company X was sanctioned in August 2026", persist=False))
    assert len(r.reasoning_trace) >= 5
    assert any("Independence analysis" in t for t in r.reasoning_trace)
    assert any("Hypothesis H1" in t for t in r.reasoning_trace)


def test_inference_is_labeled(engine):
    """§26 — interpretation is always labeled INFERENCE, never posed as fact."""
    r = run(engine.run_full_pipeline(
        "Company X was sanctioned in August 2026", persist=False))
    assert r.interpretation.startswith("INFERENCE:")


def test_flood_claim_matches_weather_related_news(engine):
    r = run(engine.run_full_pipeline(
        "A flood warning was issued in Lagos on 18 August 2026", persist=False))
    assert r.sources_total >= 1
    assert r.verdict != Verdict.FALSE
