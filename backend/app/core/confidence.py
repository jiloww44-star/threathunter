"""Confidence scoring — spec §1.7 / Part 1.5 step 6.

Confidence is driven by evidence quality and consistency, NEVER just source
count (§1.6 independence, Part 16.3 docs):

  weighted independent support, PRIMARY authority presence, contradiction
  count/severity, entity certainty.

Bands: VERY_HIGH ≥ .90 · HIGH ≥ .72 · MODERATE ≥ .50 · LOW ≥ .30 ·
VERY_LOW < .30 · UNDETERMINED when evidence is insufficient (§1.9).
Contradictions cap attainable confidence — a HIGH-severity contradiction
blocks VERY_HIGH by design (spec Part 8 test: contradiction blocks verdict).
"""
from __future__ import annotations

from ..models.schemas import Confidence, Contradiction, RiskLevel
from ..scraper.models import Reliability


def score_confidence(
    n_independent_support: int,
    support_weight: float,
    contradict_weight: float,
    has_primary: bool,
    contradictions: list[Contradiction],
    total_independent: int,
) -> tuple[Confidence, float]:
    if total_independent == 0 or (support_weight <= 0 and contradict_weight <= 0):
        return Confidence.UNDETERMINED, 0.0

    if support_w_ := support_weight:
        net = max(support_w_ - contradict_weight, 0.0)
        base = min(net / support_w_, 1.0)
    else:  # pure-contradiction path (FALSE verdicts): weight of opposing case
        base = min(contradict_weight / 1.2, 1.0)

    if has_primary:
        base = min(base + 0.15, 1.0)
    if n_independent_support >= 3:
        base = min(base + 0.05, 1.0)

    level = _band(base)

    order = [Confidence.UNDETERMINED, Confidence.VERY_LOW, Confidence.LOW,
             Confidence.MODERATE, Confidence.HIGH, Confidence.VERY_HIGH]

    def cap(lvl: Confidence, ceiling: Confidence) -> Confidence:
        return lvl if order.index(lvl) <= order.index(ceiling) else ceiling

    # Honesty caps (§1.7): contradictions and missing PRIMARY authority bound
    # attainable certainty — VERY_HIGH needs a primary official source and a
    # clean contradiction slate; a single supporting group tops out MODERATE.
    sev_high = any(c.severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)
                   for c in contradictions)
    sev_mod = any(c.severity == RiskLevel.MODERATE for c in contradictions)
    if sev_high:
        level = cap(level, Confidence.HIGH)
    if sev_mod:
        level = cap(level, Confidence.HIGH)      # blocks VERY_HIGH (Part 8 test)
    if not has_primary:
        level = cap(level, Confidence.HIGH)
    if n_independent_support <= 1 and not has_primary:
        level = cap(level, Confidence.MODERATE)

    if n_independent_support < 1 and contradict_weight == 0:
        level = Confidence.UNDETERMINED
    return level, round(base, 3)


def _band(score: float) -> Confidence:
    if score >= 0.90:
        return Confidence.VERY_HIGH
    if score >= 0.72:
        return Confidence.HIGH
    if score >= 0.50:
        return Confidence.MODERATE
    if score >= 0.30:
        return Confidence.LOW
    return Confidence.VERY_LOW


def recommend_action(verdict: str, confidence: Confidence) -> str:
    table = {
        ("VERIFIED", Confidence.VERY_HIGH):
            "You may rely on this conclusion; a primary official source confirms it.",
        ("VERIFIED", Confidence.HIGH):
            "Safe to rely on. Independent sources agree; keep the cited sources for reference.",
        ("MOSTLY_TRUE", Confidence.HIGH):
            "Treat the core claim as supported, but note the flagged contradiction "
            "before acting on specifics (exact entity or date).",
        ("PARTIALLY_TRUE", Confidence.MODERATE):
            "Act only on the verified parts; the rest needs additional sourcing.",
        ("MISLEADING", Confidence.MODERATE):
            "Do not share as-is — the framing distorts the underlying facts.",
        ("MISLEADING", Confidence.HIGH):
            "Do not share as-is — the framing distorts the underlying facts. See contradictions.",
        ("FALSE", Confidence.HIGH):
            "Reputable independent evidence contradicts this claim. Do not act on it.",
        ("UNVERIFIED", Confidence.UNDETERMINED):
            "No confident conclusion is possible yet. We monitor sources "
            "continuously — check back as new evidence is ingested.",
    }
    return table.get(
        (verdict, confidence),
        "Review the evidence below and treat this as provisional.",
    )


def reliability_of(name: str) -> float:
    return Reliability.__members__.get(name, Reliability.UNKNOWN).value
