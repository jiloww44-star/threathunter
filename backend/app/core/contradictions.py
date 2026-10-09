"""Contradiction detection — spec Part 3.3 (§1.8).

Same entity, conflicting facts → flagged Contradiction with severity.
Temporal conflicts >1 day apart = MODERATE. Direct claim-conflict
(support vs contradict between independent sources, or explicit entity
clarification) = HIGH.
"""
from __future__ import annotations

from datetime import timedelta
from itertools import combinations

from ..models.schemas import Contradiction, RiskLevel
from . import nlp_lite


def detect_contradictions(signals: list[dict]) -> list[Contradiction]:
    out: list[Contradiction] = []
    for a, b in combinations(signals, 2):
        if a.get("evidence_id") == b.get("evidence_id"):
            continue
        if not nlp_lite.same_entity(a.get("entity"), b.get("entity")):
            continue

        # 1) Temporal contradiction
        ta = nlp_lite.parse_iso(a.get("event_time"))
        tb = nlp_lite.parse_iso(b.get("event_time"))
        if ta and tb and abs(ta - tb) > timedelta(days=1):
            out.append(Contradiction(
                description=(
                    f"Date conflict: {a['source_id']} says "
                    f"{ta.date().isoformat()}, {b['source_id']} says "
                    f"{tb.date().isoformat()} about the same entity"
                ),
                evidence_a_id=a["evidence_id"],
                evidence_b_id=b["evidence_id"],
                severity=RiskLevel.MODERATE,
            ))

        # 2) Explicit clarification / scope disagreement (NLI-contradiction in
        #    production; here: supports_claim disagreement or 'not'/'clarif'
        #    markers across DIFFERENT independence groups)
        sa = a.get("supports_claim")
        sb = b.get("supports_claim")
        disagreement = (
            sa is not None and sb is not None and bool(sa) != bool(sb)
        )
        clarification = any(
            marker in (b.get("claim_text") or "").lower()
            for marker in ("clarification", "not company", "not the", "unaffected",
                           "holding", "subsidiary")
        ) or any(
            marker in (a.get("claim_text") or "").lower()
            for marker in ("clarification", "not company", "not the", "unaffected",
                           "holding", "subsidiary")
        )
        if disagreement or (
            clarification and a["independence_group"] != b["independence_group"]
        ):
            out.append(Contradiction(
                description=(
                    f"{a['source_id']} and {b['source_id']} conflict on the "
                    f"scope/subject of the claim (possible entity confusion)"
                ),
                evidence_a_id=a["evidence_id"],
                evidence_b_id=b["evidence_id"],
                severity=RiskLevel.HIGH,
            ))

    # de-duplicate pairs
    seen: set[tuple[str, str, str]] = set()
    deduped: list[Contradiction] = []
    for c in out:
        key = (tuple(sorted([c.evidence_a_id, c.evidence_b_id]))[0],
               tuple(sorted([c.evidence_a_id, c.evidence_b_id]))[1],
               c.severity.value)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped
