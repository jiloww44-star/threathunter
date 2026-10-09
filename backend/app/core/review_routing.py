"""Tiered review routing — §Willison Bottleneck Map, D1 redesign (spec Part 18).

The broken assumption: exhaustive human review scales linearly with verdict
volume. The redesign: route by **confidence × blast radius** so human
attention scales with UNCERTAINTY, not VOLUME — with a mandatory-review
firewall underneath so nothing uncertain ever auto-publishes.

Routing matrix (TRUST.md §Tiered review):

    contradictions ≥ 2 ............ MANDATORY_REVIEW  (always)
    copy-chain dominance .......... MANDATORY_REVIEW  (echo/disinfo pattern)
    confidence ≤ MODERATE ......... MANDATORY_REVIEW  (uncertainty firewall)
    HIGH conf × HIGH stakes ....... MANDATORY_REVIEW  (unchanged, §27)
    HIGH conf × LOW stakes ........ AUTO_PUBLISH, 5% random AUDIT_SAMPLE

Every routing decision is recorded on the response (`.review_route`) and
traced — "sampled" never means "secretly skipped" (§20 honesty).

KYC identity decisions are explicitly OUT of scope (they cannot be sampled —
§Willison "the single new constraint"); KYC keeps its exhaustive §12/§13
routing and only gains tier labels.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..models.schemas import Confidence, Contradiction, RiskLevel

AUTO_PUBLISH = "AUTO_PUBLISH"          # tier 0 — ships without queue entry
AUDIT_SAMPLE = "AUDIT_SAMPLE"          # tier 1 — published + random QA audit
MANDATORY_REVIEW = "MANDATORY_REVIEW"  # tier 2 — human gate, §27 SLA

# Random audit-sampling rate for auto-published, high-confidence low-stakes
# items (TRUST.md: "auto-publish, 5% random audit sample")
AUDIT_SAMPLE_RATE = 0.05

# Copy-chain dominance: duplicates/copy-copies make up this share of retrieved
# signals (from the spec's echo-disinfo metric, Part 4.4)
COPY_CHAIN_DOMINANCE = 0.60

_STRONG = (Confidence.VERY_HIGH, Confidence.HIGH)


@dataclass
class ReviewRoute:
    tier: str            # AUTO_PUBLISH | AUDIT_SAMPLE | MANDATORY_REVIEW
    reason: str          # human-readable rule trace (goes INTO the queue row)
    risk: str            # queue risk label
    priority: int        # queue priority (higher = reviewed sooner)

    @property
    def enqueued(self) -> bool:
        return self.tier != AUTO_PUBLISH


def route_review(*, confidence: Confidence,
                 contradictions: list[Contradiction],
                 sources_independent: int, sources_total: int,
                 stakes: str = "low",
                 module: str = "factcheck",
                 audit_rate: float = AUDIT_SAMPLE_RATE,
                 sampler=None) -> ReviewRoute:
    """Decide where an intelligence output goes.

    `sampler`: injectable float-in-[0,1) function for deterministic tests;
    defaults to random.random. Copy-chain dominance = (total - independent) /
    total share of syndicated material (§1.6 counts).
    """
    sample = sampler if sampler is not None else random.random
    stakes_high = str(stakes).lower() in ("high", "safety", "legal")

    high_contra = [c for c in contradictions if c.severity in (
        RiskLevel.HIGH, RiskLevel.CRITICAL)]
    n_contra = len(contradictions)
    dup_share = ((sources_total - sources_independent) / sources_total
                 if sources_total else 0.0)

    # ---- the mandatory firewall (order = rule precedence) ----------------
    if n_contra >= 2:
        sev = "HIGH/CRITICAL" if high_contra else "MODERATE"
        return ReviewRoute(
            MANDATORY_REVIEW,
            f"{n_contra} active contradictions ({sev}) — rule: ≥2 "
            f"contradictions always route to humans",
            risk="HIGH" if high_contra else "MODERATE", priority=60)
    if dup_share >= COPY_CHAIN_DOMINANCE and sources_total >= 3:
        return ReviewRoute(
            MANDATORY_REVIEW,
            f"copy-chain dominance: {sources_total - sources_independent} of "
            f"{sources_total} retrieved signals are syndicated copies "
            f"(≥{COPY_CHAIN_DOMINANCE:.0%}) — echo/disinfo pattern",
            risk="MODERATE", priority=50)
    if confidence not in _STRONG:
        return ReviewRoute(
            MANDATORY_REVIEW,
            f"confidence {confidence.value} below the auto-publish firewall "
            f"(uncertainty scales review, §27)",
            risk="MODERATE", priority=45)
    if stakes_high:
        return ReviewRoute(
            MANDATORY_REVIEW,
            f"{module} is a high-stakes surface (identity/safety/legal) — "
            f"high-confidence verdicts stay human-gated (blast-radius class)",
            risk="HIGH", priority=55)

    # ---- auto-publish lane: high confidence, low stakes -------------------
    if sample() < audit_rate:
        return ReviewRoute(
            AUDIT_SAMPLE,
            "random 5% QA audit sample of an auto-published high-confidence "
            "verdict (sampled audit = the usage-evidence stream, TRUST.md)",
            risk="LOW", priority=10)
    return ReviewRoute(
        AUTO_PUBLISH,
        "auto-published: HIGH confidence, low stakes, no contradiction or "
        "echo anomalies (95% of this lane is unaudited by design)",
        risk="LOW", priority=0)


def stakes_for_module(module: str) -> str:
    """Blast-radius classes (TRUST.md §1): which surfaces default HIGH."""
    return {"kyc": "high",         # identity, legal exposure
            "journey": "high",     # physical-safety advisories
            "factcheck": "low"}.get(module, "low")
