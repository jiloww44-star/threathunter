"""The Inductive-Logical Reasoning Engine — spec Part 1.5.

Observation → Signals → Patterns → Hypotheses → Testing → Weighting →
Confidence → Verdict.

Inductive loop, faithfully encoded:
  1. OBSERVATION (§1.1): extract entities/dates/locations/event-type from claim
  2. SOURCE DISCOVERY: semantic search over the scraped evidence store
  3. INDEPENDENCE ANALYSIS (§1.6): independence groups + copy-chain dedupe —
     5 identical claims from one group = ONE effective source
  4. CONTRADICTION DETECTION (§1.8): temporal + scope conflicts
  5. HYPOTHESIS GENERATION & TESTING (§1.4-1.5): H1 event occurred,
     H2 copy-chain, H3 entity confusion, H4 partially-true-but-misleading
  6. CONFIDENCE (§1.7): reliability-weighted, contradiction-capped,
     UNDETERMINED-honest
  7. VERDICT: hypothesis→verdict mapping; absence of evidence ≠ FALSE (§1.9)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..models.schemas import (
    Confidence, Contradiction, EvidenceItem, FactCheckResponse, Verdict,
)
from ..store.db import EvidenceStore, get_store
from . import nlp_lite
from .confidence import recommend_action, reliability_of, score_confidence
from .contradictions import detect_contradictions
from .trust_model import label_inference
from ..scraper.dedupe import simhash64, hamming


@dataclass
class Hypothesis:  # §1.4-1.5
    id: str
    statement: str
    supporting: int = 0
    contradicting: int = 0
    score: float = 0.0
    notes: list[str] = field(default_factory=list)


class ReasoningEngine:
    """Implements the spec's inductive pipeline for the Fact Checker module."""

    def __init__(self, store: EvidenceStore | None = None):
        self.store = store or get_store()

    async def run_full_pipeline(self, claim: str, user: str = "demo",
                                persist: bool = True) -> FactCheckResponse:
        import time as _time
        _t0 = _time.perf_counter()   # v4.6 — §71 fact-check latency metric
        trace: list[str] = []

        # ---- 1. OBSERVATION (§1.1) --------------------------------------
        elements = nlp_lite.extract_claim_elements(claim)
        trace.append(
            f"Observation: extracted {len(elements['entities'])} entities, "
            f"{len(elements['dates'])} dates, {len(elements['locations'])} "
            f"locations, event_type={elements['event_type']!r}"
        )

        # ---- 2. SOURCE DISCOVERY -----------------------------------------
        candidates = self.store.search_signals(claim, limit=50, elements=elements)
        trace.append(
            f"Source discovery: {len(candidates)} candidate signals retrieved "
            f"from evidence store (semantic + entity/date boosted)"
        )
        anchored = sum(1 for c in candidates if c.get("entity_matched"))
        trace.append(
            f"Entity anchoring: {anchored}/{len(candidates)} candidates "
            f"matched claim entities (office-title aliases resolved, §1.1)"
        )
        if not candidates:
            return self._unverified(
                claim, trace,
                reason="No relevant evidence found in indexed sources.",
                action="Try rephrasing, or check back later as new data is "
                       "ingested — sources are refreshed continuously.",
            )

        # ---- 3. INDEPENDENCE ANALYSIS (§1.6) -----------------------------
        groups = self._independence_groups(candidates)
        n_independent = len(groups)
        n_total = len(candidates)
        n_duplicate = n_total - n_independent
        trace.append(
            f"Independence analysis: {n_total} signals → {n_independent} "
            f"effective independent sources (copy-chain dedupe removed "
            f"{n_duplicate} duplicate/syndicated copies)"
        )

        # §1.6 display — cross-group text clusters: syndication spans hosts,
        # so simhash clustering over raw text reveals how many near-identical
        # "story copies" exist and which origin they trace back to.
        clusters, chain_note = self._text_clusters(candidates)
        if n_total >= 2 and chain_note:
            trace.append(
                f"Copy-chain clusters: {len(clusters)} text cluster(s) "
                f"across {n_total} signals; {chain_note}")

        # ---- 4. CONTRADICTION DETECTION (§1.8) ---------------------------
        contradictions = detect_contradictions(candidates)
        if contradictions:
            trace.append(
                f"Contradiction detection: {len(contradictions)} conflict(s) "
                f"flagged ({', '.join(c.severity.value for c in contradictions)})"
            )
        else:
            trace.append("Contradiction detection: no conflicts found")

        # ---- 5. HYPOTHESES (§1.4-1.5) ------------------------------------
        support_w, explicit_w, scope_w, supporting, contradicting, has_primary = \
            self._weights(groups, contradictions)
        score_scope = sum(1 for c in contradictions if c.severity.value == "HIGH")
        score_dates = sum(1 for c in contradictions if c.severity.value == "MODERATE")

        hypotheses = self._test_hypotheses(
            support_w, explicit_w, scope_w, supporting, contradicting,
            n_independent, n_duplicate, has_primary, score_scope, score_dates,
        )
        best = max(hypotheses, key=lambda h: h.score)
        for h in hypotheses:
            trace.append(f"Hypothesis {h.id} tested: {h.statement!r} "
                         f"→ score {h.score:.2f} "
                         f"(+{h.supporting} supporting / -{h.contradicting} contradicting)")
        trace.append(f"Winning hypothesis: {best.id} — {best.statement}")

        # ---- 6. CONFIDENCE (§1.7) ----------------------------------------
        n_independent_support = sum(
            1 for g in groups
            if any(s.get("supports_claim") is not False for s in g)
        )
        confidence, conf_score = score_confidence(
            n_independent_support, support_w, explicit_w + 0.4 * scope_w,
            has_primary, contradictions, n_independent,
        )

        # ---- 7. VERDICT ---------------------------------------------------
        verdict, scope_caveat = self._map_to_verdict(
            best, support_w, explicit_w, contradictions, confidence,
            n_independent_support, has_primary,
        )

        # Honest confidence for non-positive verdicts (§1.9)
        if verdict == Verdict.UNVERIFIED:
            confidence = Confidence.UNDETERMINED
        elif verdict == Verdict.FALSE and not has_primary:
            confidence = Confidence.HIGH

        # If a PRIMARY official source backs the event, unresolved secondary
        # contradictions carry far less weight (§1.10 reassessment).
        if has_primary and explicit_w == 0 and verdict in (
                Verdict.VERIFIED, Verdict.MOSTLY_TRUE):
            verdict = Verdict.VERIFIED
            confidence = Confidence.VERY_HIGH if conf_score >= 0.85 \
                else Confidence.HIGH

        trace.append(
            f"Confidence: {confidence.value} (net evidence score {conf_score})"
        )
        trace.append(f"Verdict mapping: {verdict.value}")

        response = self._build_response(
            claim, verdict, confidence, best, groups, contradictions,
            trace, scope_caveat,
        )
        # §1.6 display metrics (verdict math untouched — see trace)
        response.copy_chain_clusters = len(clusters) if n_total >= 2 else None
        response.copy_chain_note = chain_note if n_total >= 2 else None

        # spec §3 — OpenRouter narrative polish (all AI actions flow through
        # the budget-gated gateway; no key → deterministic answer stands).
        narrative = await self._narrate(response)
        if narrative:
            response.answer = narrative["text"].strip()
            trace.append(
                f"AI narrative: OpenRouter {narrative['model_used']} "
                f"(budget mode {narrative['mode']}, settled via nanocents)")
        response.ai_narrative = narrative

        # Persist: hypotheses, check record, review routing — §1.10/§27/Part 4
        if persist:
            check_id = self.store.record_check(
                module="factcheck", subject=claim, outcome=verdict.value,
                confidence=confidence.value,
                response=response.model_dump(mode="json"), check_id=response.check_id,
                # v4.6 §71 — measured wall-clock of the run, ms (latency KPI)
                latency_ms=round((_time.perf_counter() - _t0) * 1000, 1),
            )
            response.check_id = check_id
            response.graph_url = f"/api/v1/graph/case/{check_id}"
            for h in hypotheses:
                self.store.insert_hypothesis(
                    case_id=check_id, statement=h.statement,
                    supporting=h.supporting, contradicting=h.contradicting,
                    score=round(h.score, 3), confidence=confidence.value,
                    status="ACTIVE" if h is best else "SUPERSEDED",
                )
            # D1 tiered review (Part 18/§Willison): exhaustive review does
            # not scale — route by confidence × blast radius so attention
            # scales with uncertainty. The firewall rules below are always
            # mandatory regardless of volume.
            from .review_routing import route_review, stakes_for_module
            route = route_review(
                confidence=confidence, contradictions=contradictions,
                sources_independent=n_independent, sources_total=n_total,
                stakes=stakes_for_module("factcheck"), module="factcheck")
            trace.append(f"Review routing (Part 18 D1): {route.tier} — "
                         f"{route.reason}")
            if route.enqueued:
                self.store.enqueue_review(
                    module="factcheck", case_ref=check_id,
                    reason=route.reason, risk=route.risk,
                    priority=route.priority, tier=route.tier)
            response.review_route = route.tier
        return response

    async def _narrate(self, resp: "FactCheckResponse") -> dict | None:
        """spec §3 — AI action: one bounded sentence restating verdict +
        confidence. Templates stay canonical if the provider is absent."""
        from ..llm.circuit_breaker import ai_action
        from ..core.errors import PipelineError
        try:
            out = await ai_action("factcheck", [
                {"role": "user", "content":
                 "Rewrite this verdict line in ONE sentence for a layperson. "
                 "State the verdict word, keep the caveat, never overstate. "
                 f"Verdict: {resp.verdict.value}. Confidence: "
                 f"{resp.confidence.value}. Answer: {resp.answer}"}],
                max_tokens=90)
            return {"text": out["text"], "model_used": out["model_used"],
                    "mode": out["mode"]}
        except PipelineError:
            return None

    # ---------------------------------------------------------------- utils
    def _text_clusters(self, candidates: list[dict],
                       threshold: int = 6) -> tuple[list[list[dict]], str | None]:
        """§1.6 — near-text clusters across ALL candidates (display only).

        Unlike independence counting (registry groups), text clustering
        ignores groups: syndicated copies on different hosts share wording,
        so they cluster together. The note names the trace-back origin of the
        largest chain — the PRIMARY source if one sits in the chain, else the
        earliest-published member.
        """
        hashes = [(c, simhash64(c.get("claim_text") or c.get("excerpt") or ""))
                  for c in candidates]
        clusters: list[list[dict]] = []
        for c, h in hashes:
            for cl in clusters:
                if hamming(h, simhash64(cl[0].get("claim_text") or
                                        cl[0].get("excerpt") or "")) <= threshold:
                    cl.append(c)
                    break
            else:
                clusters.append([c])
        largest = max(clusters, key=len, default=[])
        if len(largest) < 2:
            return clusters, None
        primaries = [c for c in largest if c.get("authority") == "PRIMARY"]

        def _stamp(c: dict) -> str:
            return str(c.get("published_at") or c.get("event_time")
                       or c.get("fetched_at") or "")

        origin = (primaries[0] if primaries
                  else min(largest, key=_stamp))
        note = (f"largest chain = {len(largest)} articles tracing to one "
                f"origin ({origin.get('source_id', '?')})")
        return clusters, note

    def _independence_groups(self, candidates: list[dict]) -> list[list[dict]]:
        """§1.6 — the independence group IS the editorial-independence
        identity: everything from one group is one effective source. Copy
        chains (near-identical text inside a group) are flagged for display
        and copy-chain scoring, not for independence counting."""
        groups: dict[str, list[dict]] = {}
        for c in candidates:
            groups.setdefault(c["independence_group"], []).append(c)
        return list(groups.values())

    def _weights(self, groups, contradictions):
        """Reliability-weighted support vs contradiction (§1.6-1.8)."""
        scope_ids = {
            eid
            for c in contradictions if c.severity.value == "HIGH"
            for eid in (c.evidence_a_id, c.evidence_b_id)
        }
        support_w = explicit_w = scope_w = 0.0
        supporting = contradicting = 0
        has_primary = False
        for g in groups:
            rep = max(g, key=lambda s: s.get("reliability_score") or 0.2)
            rel = rep.get("reliability_score") or reliability_of(
                rep.get("reliability", "UNKNOWN"))
            supports = rep.get("supports_claim")
            in_scope_conflict = rep["evidence_id"] in scope_ids
            if rep.get("authority") == "PRIMARY" and supports is not False:
                has_primary = True
                support_w += rel
                supporting += len(g)
            elif supports is False:
                if in_scope_conflict:
                    # Scope/entity-confusion conflict: confirms the broad event
                    # family while disputing the specific subject — half weight.
                    support_w += rel * 0.5
                    scope_w += rel
                    supporting += len(g)
                else:
                    explicit_w += rel
                    contradicting += len(g)
            else:
                support_w += rel
                supporting += len(g)
        return support_w, explicit_w, scope_w, supporting, contradicting, has_primary

    def _test_hypotheses(self, support_w, explicit_w, scope_w, supporting,
                         contradicting, n_independent, n_duplicate, has_primary,
                         n_scope, n_dates) -> list[Hypothesis]:
        # H1 — genuine occurrence: driven by actual evidence mass (§1.5)
        h1 = Hypothesis("H1", "The event genuinely occurred.",
                        supporting=supporting, contradicting=contradicting,
                        score=support_w - 0.3 * scope_w - 0.8 * explicit_w
                              + (0.2 if has_primary else 0.0))
        # H2 — copy-chain: multiple copies of one originating report (§1.6)
        dupe_ratio = (n_duplicate / (n_duplicate + n_independent)) if (
            n_duplicate + n_independent) else 0.0
        h2 = Hypothesis(
            "H2", "Sources copied a single originating report.",
            supporting=n_duplicate,
            score=(0.5 * dupe_ratio if (n_independent <= 1 and not has_primary)
                   else 0.05),
        )
        # H3 — entity confusion between similar names (§1.5)
        h3 = Hypothesis("H3", "Entity name confusion between similar entities.",
                        supporting=n_scope, score=0.3 * n_scope)
        # H4 — partially true but materially misleading (§1.5)
        mixed = 1 if (supporting > 0 and contradicting > 0) else 0
        h4 = Hypothesis("H4", "Partially true but materially misleading.",
                        supporting=n_dates + mixed,
                        score=0.2 * n_dates + 0.15 * mixed)
        return [h1, h2, h3, h4]

    # Below this evidence-mass floor, "somebody said it" is not corroboration
    # (§1.9 — weak/unreliable evidence must not fabricate a positive verdict).
    SUPPORT_FLOOR = 0.45

    def _map_to_verdict(self, best, support_w, explicit_w, contradictions,
                        confidence, n_independent_support, has_primary):
        """ hypothesis+confidence → verdict (§1.4; UNVERIFIED ≠ FALSE §1.9) """
        scope_caveat = any(c.severity.value == "HIGH" for c in contradictions)
        date_caveat = any(c.severity.value == "MODERATE" for c in contradictions)

        if support_w == 0 and explicit_w > 0:
            return Verdict.FALSE, False
        if explicit_w > support_w * 1.2 and explicit_w > 0:
            return Verdict.FALSE, False
        if support_w < self.SUPPORT_FLOOR:
            return Verdict.UNVERIFIED, False

        if best.id == "H4":
            return Verdict.MISLEADING, False
        if scope_caveat:
            return (Verdict.MOSTLY_TRUE if not has_primary
                    else Verdict.VERIFIED), True
        if date_caveat:
            return (Verdict.MOSTLY_TRUE if not has_primary
                    else Verdict.VERIFIED), False
        if n_independent_support <= 1:
            # One effective source — even a PRIMARY one — is provisional.
            return Verdict.PARTIALLY_TRUE, False
        return Verdict.VERIFIED, False

    def _build_response(self, claim, verdict, confidence, hyp, groups,
                        contradictions, trace, scope_caveat) -> FactCheckResponse:
        dup_flags: dict[str, bool] = {}
        for g in groups:
            for i, s in enumerate(g):
                dup_flags[s["evidence_id"]] = i > 0

        # Sort evidence: supporting first, then PRIMARY, duplicates last (§19)
        flat = [s for g in groups for s in g]
        ordered = sorted(
            flat,
            key=lambda s: (
                dup_flags.get(s["evidence_id"], False),
                s.get("supports_claim") is False,
                -(s.get("reliability_score") or 0.2),
            ),
        )
        evidence_items = [
            EvidenceItem(
                source_id=s["source_id"],
                url=s.get("url"),
                published_at=nlp_lite.parse_iso(s.get("published_at"))
                             or nlp_lite.parse_iso(s.get("event_time")),
                fetched_at=nlp_lite.parse_iso(s.get("fetched_at"))
                           or datetime.now(timezone.utc),
                reliability=s.get("reliability", "UNKNOWN"),
                reliability_score=s.get("reliability_score") or 0.2,
                authority=s.get("authority", "SECONDARY"),
                independence_group=s["independence_group"],
                supports_claim=(None if s.get("supports_claim") is None
                                else bool(s.get("supports_claim"))),
                excerpt=(s.get("excerpt") or s.get("claim_text") or "")[:400],
                is_duplicate_copy=dup_flags.get(s["evidence_id"], False),
            )
            for s in ordered[:10]
        ]

        # v4.0 §49-51 — Coverage axis (alongside Confidence): how much of the
        # evidentiary space did we actually reach? HIGH needs ≥3 independent
        # groups incl. a PRIMARY source; MEDIUM ≥2 groups; else LOW.
        n_indep = len(groups)
        has_primary = any(s.get("authority") == "PRIMARY" for s in flat)
        coverage, coverage_basis = _coverage_assessment(n_indep, has_primary)

        answer_map = {
            Verdict.VERIFIED: "Independent evidence confirms this claim.",
            Verdict.MOSTLY_TRUE: "The core of this claim checks out — with one "
                                 "important caveat detailed below.",
            Verdict.PARTIALLY_TRUE: "Parts of this claim check out; other parts "
                                    "could not be confirmed.",
            Verdict.MISLEADING: "Factual material here creates a misleading "
                                "impression.",
            Verdict.FALSE: "Reliable independent evidence contradicts this claim.",
            Verdict.UNVERIFIED: "We could not find enough reliable evidence to "
                                "confirm or refute this claim.",
        }

        interpretation = (
            f"{hyp.statement} "
            f"Evidence basis: {len(groups)} independent source group(s). "
            + ("Unresolved entity-scope conflict — the action may apply to a "
               "related entity rather than the subject exactly as stated."
               if scope_caveat else "")
        )

        return FactCheckResponse(
            verdict=verdict, confidence=confidence, claim=claim,
            checked_at=datetime.now(timezone.utc),
            answer=answer_map[verdict],
            key_evidence=evidence_items,
            contradictions=contradictions,
            interpretation=label_inference(interpretation),
            recommended_action=recommend_action(verdict.value, confidence),
            sources_independent=len(groups),
            sources_total=sum(len(g) for g in groups),
            coverage=coverage,
            coverage_basis=coverage_basis,
            what_would_change_conclusion=(
                "A primary official source confirming or denying the event, or "
                "resolution of the flagged conflict, would materially change "
                "this assessment."
                if contradictions else
                "Credible evidence contradicting the current primary and "
                "independent sources."
            ),
            reasoning_trace=trace,
        )

    def _unverified(self, claim, trace, reason, action) -> FactCheckResponse:
        """§1.9 — absence of evidence produces UNVERIFIED, never FALSE."""
        trace.append(f"Result: {reason}")
        return FactCheckResponse(
            verdict=Verdict.UNVERIFIED, confidence=Confidence.UNDETERMINED,
            claim=claim, checked_at=datetime.now(timezone.utc),
            answer=("We could not find corroborating evidence for this claim "
                    "in any indexed source."),
            key_evidence=[], contradictions=[],
            interpretation=label_inference(
                "Absence of evidence — this is NOT proof the claim is false."),
            recommended_action=action,
            sources_independent=0, sources_total=0,
            # §49-51 — zero reach is the LOW end of the Coverage axis;
            # disclosed honestly, never absorbed into the verdict (§1.9).
            coverage="LOW",
            coverage_basis=("No indexed source group reached — coverage is "
                            "LOW; this assessment is CONFIDENCE-UNDETERMINED "
                            "and must not be read as 'claim is false'."),
            what_would_change_conclusion=(
                "New publications from primary or independent sources entering "
                "the ingestion pipeline."),
            reasoning_trace=trace,
        )


def _coverage_assessment(n_independent: int, has_primary: bool,
                         ) -> tuple[str, str]:
    """§49-51 Coverage axis — deterministic mapping (§54), never inferred
    by the model. Confidence says 'how sure'; Coverage says 'how wide'."""
    if n_independent >= 3 and has_primary:
        return ("HIGH", f"{n_independent} independent source groups including "
                        "a PRIMARY source — wide evidentiary reach.")
    if n_independent >= 2:
        return ("MEDIUM", f"{n_independent} independent source groups"
                          + (", but no PRIMARY source" if not has_primary else
                             "") + " — moderate evidentiary reach.")
    return ("LOW", f"{n_independent} independent source group(s)"
                   + ("" if has_primary else ", no PRIMARY source")
                   + " — thin evidentiary reach; treat the verdict as "
                     "provisional.")

    # §1.10 — continuous reassessment
    async def reassess_case(self, check_id: str) -> FactCheckResponse | None:
        """Re-run an earlier claim against *current* evidence (new evidence
        automatically triggers re-testing and confidence updates, §1.10)."""
        row = self.store.get_check(check_id)
        if not row:
            return None
        return await self.run_full_pipeline(row["subject"], user="reassess",
                                            persist=False)
