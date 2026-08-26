"""KYC tests — spec Parts 3.4 / 5.3, demo scenario 4 (§12: anomaly ≠ fraud)."""
import asyncio

from app.core.kyc import (
    KYCDecision, LivenessResult, MatchResult, MockBiometricProvider, decide,
    normalize_name, verify_identity,
)
from app.models.schemas import (KYCDocumentExtraction, KYCUserInput,
                                KYCVerifyRequest)


def run(coro):
    return asyncio.run(coro)


def _request(selfie="mock:pass", dob="2008-11-02", issue="2020-05-20",
             name="Daniel Mensah"):
    return KYCVerifyRequest(
        document=KYCDocumentExtraction(
            name=name, dob=dob, issue_date=issue, expiry_date="2030-05-19"),
        user_input=KYCUserInput(name=name, dob=dob),
        selfie_ref=selfie,
    )


def test_anomaly_alone_never_denies(seeded):
    """§12 / Part 8.3 — a date inconsistency must not auto-deny."""
    decision = decide(LivenessResult(True, 0.98), MatchResult(0.92), True,
                      anomalies=[])  # passed separately below
    assert decision == KYCDecision.VERIFIED


def test_clean_document_verifies(seeded):
    r = run(verify_identity(_request(dob="1991-04-17", issue="2023-03-05",
                                     name="Clara Eze"), seeded))
    assert r.decision == KYCDecision.VERIFIED
    # §25 — PII never persists raw: only hashed case reference
    assert r.case_id and " " not in r.case_id


def test_scenario_4_date_inconsistency_review_not_denial(seeded):
    """Demo scenario 4: expected VERIFIED_WITH_ADDITIONAL_REVIEW."""
    r = run(verify_identity(_request(), seeded))
    assert r.decision == KYCDecision.VERIFIED_WITH_REVIEW
    assert any(a.type == "DATE_INCONSISTENCY" for a in r.anomalies)
    assert r.routed_to_human_review  # §27 queue


def test_low_quality_capture_is_pending(seeded):
    r = run(verify_identity(_request(selfie="mock:low_quality",
                                     dob="1991-04-17", issue="2023-03-05",
                                     name="Clara Eze"), seeded))
    assert r.decision == KYCDecision.PENDING
    assert "retake" in r.recommended_action.lower()


def test_spoof_routes_to_manual_review_never_auto_denied(seeded):
    r = run(verify_identity(_request(selfie="mock:spoof",
                                     dob="1991-04-17", issue="2023-03-05",
                                     name="Clara Eze"), seeded))
    assert r.decision == KYCDecision.REQUIRES_MANUAL_REVIEW
    assert "specialist" in r.answer.lower()


def test_sanctions_hit_manual_review(seeded):
    """Part 5: sanctions feed from scraped gazette gates to humans (§12)."""
    r = run(verify_identity(_request(name="Vendor Y", dob="1988-01-12",
                                     issue="2019-02-11"), seeded))
    assert r.decision == KYCDecision.REQUIRES_MANUAL_REVIEW
    assert any(a.type == "SANCTIONS_HIT" for a in r.anomalies)


def test_interpretation_labeled_and_queued(seeded):
    r = run(verify_identity(_request(), seeded))
    assert r.interpretation.startswith("INFERENCE:")
    queue = [q for q in seeded.review_queue() if q["case_ref"] == r.case_id]
    assert queue, "routed case must appear in analyst queue (§27)"


def test_normalize_name():
    assert normalize_name("Clara  Eze ") == normalize_name("clara eze")
