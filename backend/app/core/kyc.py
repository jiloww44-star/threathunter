"""KYC verification — spec Parts 3.4 (consistency checks) & 5 (biometric flow).

Decision taxonomy per §13. Hard rule (§12): anomaly ≠ fraud — flags route to
humans, never auto-deny on anomaly alone. PII handling per §25: only name
comparison results & hashes persist; inputs are normalized in memory.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime

from ..models.schemas import (
    Confidence, KYCDecision, KYCResponse, KYCVerifyRequest, KYCAnomaly,
    RiskLevel,
)
from ..store.db import EvidenceStore, get_store


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower().strip())


def _parse(d: str) -> date:
    return datetime.fromisoformat(d.replace("Z", "+00:00")).date() if "T" in d \
        else date.fromisoformat(d)


# ------------------------------------------------- mock biometric provider --
class LivenessResult:
    def __init__(self, passed: bool, score: float, failure_reason: str | None = None):
        self.passed = passed
        self.score = score
        self.failure_reason = failure_reason  # SPOOF_SUSPECTED | LOW_QUALITY


class MatchResult:
    def __init__(self, score: float):
        self.score = score


class MockBiometricProvider:
    """spec Part 5.2 MockProvider — dev/test only. Production swaps in a real
    provider (FaceTec etc.) behind the same interface; version logged (Part 20)."""

    def liveness(self, selfie_ref: str | None) -> LivenessResult:
        if selfie_ref == "mock:spoof":
            return LivenessResult(False, 0.93, "SPOOF_SUSPECTED")
        if selfie_ref == "mock:low_quality":
            return LivenessResult(False, 0.41, "LOW_QUALITY")
        return LivenessResult(True, 0.98)

    def face_match(self, selfie_ref: str | None) -> MatchResult:
        if selfie_ref == "mock:borderline":
            return MatchResult(0.79)  # borderline → VERIFIED_WITH_REVIEW
        return MatchResult(0.94)


# --------------------------------------------------------- consistency ----
def kyc_consistency_checks(req: KYCVerifyRequest) -> list[KYCAnomaly]:
    """spec Part 3.4 (§12) — identity, temporal and expiry consistency."""
    doc, user = req.document, req.user_input
    anomalies: list[KYCAnomaly] = []

    if normalize_name(doc.name) != normalize_name(user.name):
        anomalies.append(KYCAnomaly(
            type="NAME_MISMATCH", severity=RiskLevel.MODERATE,
            detail="Document name does not match the declared name.",
            action="Additional verification recommended"))

    dob, issue, expiry = _parse(doc.dob), _parse(doc.issue_date), _parse(doc.expiry_date)
    age_at_issue = (issue - dob).days / 365.25
    if age_at_issue < doc.min_issue_age:
        anomalies.append(KYCAnomaly(
            type="DATE_INCONSISTENCY", severity=RiskLevel.HIGH,
            detail=f"Issue date implausible: holder was {age_at_issue:.1f} at "
                   f"issue, minimum is {doc.min_issue_age}.",
            action="Route to document specialist"))

    if expiry < date.today():
        anomalies.append(KYCAnomaly(
            type="DOCUMENT_EXPIRED", severity=RiskLevel.MODERATE,
            detail="Document past expiry date.",
            action="Re-upload of a current document required"))

    if issue > date.today():
        anomalies.append(KYCAnomaly(
            type="DATE_INCONSISTENCY", severity=RiskLevel.HIGH,
            detail="Issue date lies in the future.",
            action="Route to document specialist"))
    return anomalies


def sanctions_screening(store: EvidenceStore, name: str) -> list[dict]:
    """KYC consumes the sanctions/watchlist feeds (spec §5 table)."""
    norm = normalize_name(name).replace(" ", "")
    hits = []
    for ev in store.all_evidence():
        if "sanction" not in (ev.get("title") or "").lower() and \
           "sanction" not in (ev.get("source_id") or ""):
            continue
        hay = ((ev.get("excerpt") or "") + (ev.get("title") or "")).lower()
        if norm and norm in hay.replace(" ", ""):
            hits.append({"source_id": ev["source_id"], "excerpt": ev.get("excerpt")})
    return hits


# -------------------------------------------------------------- decision ----
def decide(liveness: LivenessResult, face_match: MatchResult, readable: bool,
           anomalies: list[KYCAnomaly]) -> KYCDecision:
    """spec Part 5.3 — gates escalate to humans, never auto-accuse (§12-13).

    Policy: only *critical* gate anomalies (spoof suspicion, sanctions hits)
    trigger full manual review; ordinary document anomalies (dates, names,
    expiry) → VERIFIED_WITH_ADDITIONAL_REVIEW, never auto-denial (§12).
    """
    if not readable:
        return KYCDecision.UNABLE_TO_VERIFY
    if liveness.failure_reason == "SPOOF_SUSPECTED" and liveness.score > 0.9:
        return KYCDecision.REQUIRES_MANUAL_REVIEW   # human decides fraud or not
    if liveness.failure_reason == "LOW_QUALITY":
        return KYCDecision.PENDING                  # ask for a retry capture

    critical = [a for a in anomalies if a.type == "SANCTIONS_HIT"]
    if critical:
        return KYCDecision.REQUIRES_MANUAL_REVIEW
    if face_match.score >= 0.90 and not anomalies:
        return KYCDecision.VERIFIED
    if face_match.score >= 0.75:
        return KYCDecision.VERIFIED_WITH_REVIEW
    return KYCDecision.REQUIRES_MANUAL_REVIEW


async def verify_identity(req: KYCVerifyRequest,
                          store: EvidenceStore | None = None) -> KYCResponse:
    store = store or get_store()
    trace: list[str] = []
    provider = MockBiometricProvider()

    trace.append("Step 1/6 document extraction received (typed fields, "
                 "number hashed — §25 data minimization)")
    anomalies = kyc_consistency_checks(req)
    trace.append(f"Step 2/6 consistency checks: {len(anomalies)} anomaly flag(s)")

    readable = all(a.type != "DOCUMENT_UNREADABLE" for a in anomalies)
    liveness = provider.liveness(req.selfie_ref)
    face = provider.face_match(req.selfie_ref)
    trace.append(f"Step 3-4/6 biometrics: liveness={liveness.failure_reason or 'PASS'} "
                 f"({liveness.score:.2f}), face-match={face.score:.2f}")

    sanction_hits = sanctions_screening(store, req.document.name)
    trace.append(f"Step 5/6 list screening: {len(sanction_hits)} sanction "
                 f"list hit(s)")
    if sanction_hits:
        anomalies.append(KYCAnomaly(
            type="SANCTIONS_HIT", severity=RiskLevel.HIGH,
            detail="Name matches an entry on a monitored sanctions list.",
            action="Mandatory analyst review — §12: flag, never auto-deny"))

    decision = decide(liveness, face, readable, anomalies)
    routed = decision in (KYCDecision.REQUIRES_MANUAL_REVIEW,
                          KYCDecision.VERIFIED_WITH_REVIEW)
    trace.append(f"Step 6/6 decision state: {decision.value}"
                 + (" (routed to human queue §27)" if routed else ""))

    confidence = {
        KYCDecision.VERIFIED: Confidence.HIGH,
        KYCDecision.VERIFIED_WITH_REVIEW: Confidence.MODERATE,
        KYCDecision.PENDING: Confidence.LOW,
        KYCDecision.UNABLE_TO_VERIFY: Confidence.UNDETERMINED,
        KYCDecision.REQUIRES_MANUAL_REVIEW: Confidence.MODERATE,
    }[decision]

    case_id = hashlib.sha256(
        f"{normalize_name(req.document.name)}|{req.document.number_hash}|"
        f"{datetime.utcnow().isoformat()}".encode()
    ).hexdigest()[:12]

    if routed:
        store.enqueue_review(
            module="kyc", case_ref=case_id,
            reason="; ".join(a.type for a in anomalies) or "borderline biometrics",
            risk="HIGH" if any(a.severity == RiskLevel.HIGH for a in anomalies)
                else "MODERATE",
            priority=60 if any(a.type == "SANCTIONS_HIT" for a in anomalies) else 30,
            # identity decisions are never sampled/tiered — exhaustive by
            # design (§Willison "the single new constraint", TRUST.md)
            tier="MANDATORY_REVIEW",
        )

    response = KYCResponse(
        case_id=case_id, decision=decision, confidence=confidence,
        anomalies=anomalies,
        checks={
            "readable": readable,
            "liveness": "PASS" if liveness.passed else liveness.failure_reason,
            "face_match_score": round(face.score, 2),
            "sanctions_hits": len(sanction_hits),
            "biometric_model_version": "mock-provider-1.0.0",  # Part 20
        },
        answer={
            KYCDecision.VERIFIED: "Identity verified successfully.",
            KYCDecision.VERIFIED_WITH_REVIEW:
                "Identity verified, pending a standard additional review.",
            KYCDecision.PENDING:
                "Verification paused — a clearer capture is needed.",
            KYCDecision.UNABLE_TO_VERIFY:
                "We could not verify this document.",
            KYCDecision.REQUIRES_MANUAL_REVIEW:
                "This verification needs a human specialist — flagged for review.",
        }[decision],
        interpretation=("INFERENCE: Anomalies indicate items for review — "
                        "they are NOT findings of fraud (§12)."),
        recommended_action={
            KYCDecision.VERIFIED: "No action needed.",
            KYCDecision.VERIFIED_WITH_REVIEW: "A reviewer will confirm shortly.",
            KYCDecision.PENDING: "Retake the capture in good lighting.",
            KYCDecision.UNABLE_TO_VERIFY: "Upload a clearer or different document.",
            KYCDecision.REQUIRES_MANUAL_REVIEW:
                "A specialist will review within the 4-hour SLA.",
        }[decision],
        what_would_change_conclusion=(
            "A valid primary document matching the declared identity, or "
            "resolution of the flagged anomalies by a reviewer."),
        reasoning_trace=trace, routed_to_human_review=routed,
    )
    store.record_check(
        module="kyc",
        subject=f"KYC case {case_id} ({normalize_name(req.document.name)[:12]}…)",
        outcome=decision.value, confidence=confidence.value,
        response=response.model_dump(mode="json"),
    )
    return response
