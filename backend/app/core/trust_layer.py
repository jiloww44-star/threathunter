"""Evidence & Trust Layer — v3.0 spec §3.2 (+ v1 §1.8 global scope, §1.10
continual reassessment, §26 label separation).

First-class shared service every agent reads/writes:

    append_signal(...)        → evidence graph node with provenance (§16-17)
    score_conclusion(...)     → confidence engine (VERY_HIGH..UNDETERMINED)
    monitor(...)              → cross-module contradiction flags (§1.8 global)
    trust_label(...)          → FACT|EVIDENCE|INFERENCE separations (§26)
    reassess_all(...)         → §1.10 loop: NEW EVIDENCE → re-test ACTIVE
                                hypotheses/journey watches → UPDATE confidence
                                → NOTIFY on verdict/risk change (P3 exit)

Reassessment is event-driven: the ingestion pipeline calls reassess_after_
ingest() after new evidence lands, and the /ops/reassess endpoint exposes the
same loop for operators/tests. All failures are §20-guarded — the loop never
breaks ingestion.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from ..scraper.models import RawEvidence, Signal
from ..store.db import EvidenceStore

log = logging.getLogger("th360.trust_layer")

TRUST_LABELS = ("FACT", "EVIDENCE", "INFERENCE")  # §26 separation


def trust_label(kind: str) -> str:
    """§26 gate — unknown kinds degrade to INFERENCE (never upgraded silently)."""
    k = (kind or "").upper()
    return k if k in TRUST_LABELS else "INFERENCE"


def append_signal(store: EvidenceStore, *, source_id: str, claim_text: str,
                  entity: str | None = None, supports_claim: bool | None = None,
                  reliability: str = "MODERATE", authority: str = "SECONDARY",
                  independence_group: str | None = None, url: str = "",
                  event_time: str | None = None,
                  designed_to_test: str | None = None) -> dict:
    """§3.2 evidence_graph.append(signal, source, provenance).

    Every agent finding becomes a graph NODE (not a flat report line) with
    full provenance, so the contradiction monitor can reason across modules.
    Returns the evidence node id; idempotent by content hash (Part 2.4).
    """
    body = claim_text
    content_hash = hashlib.sha256(
        f"{source_id}|{body}".encode()).hexdigest()[:32]
    raw = RawEvidence(
        source_id=source_id, url=url,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        content_hash=content_hash, raw_text=body,
        metadata={"reliability": reliability, "authority": authority,
                  "published_at": event_time})
    sig = Signal(
        entity=entity, event_type=None, location=None, time=event_time,
        claim_text=claim_text, confidence_input=0.6,
        source_id=source_id,
        independence_group=independence_group or source_id,
        reliability=reliability, authority=authority,
        supports_claim=supports_claim, url=url,
        designed_to_test=designed_to_test)
    inserted = store.insert_evidence(raw, [sig])
    return {"inserted": bool(inserted), "content_hash": content_hash,
            "source_id": source_id,
            "trust_label": "EVIDENCE"}


def score_conclusion(*, n_independent_support: int, support_weight: float,
                     contradict_weight: float, has_primary: bool,
                     contradictions: list, total_independent: int):
    """§3.2 confidence_engine.score — thin honest pass-through to the v1
    confidence engine so every agent speaks the same tier language
    (VERY_HIGH..UNDETERMINED), with §1.7 honesty caps intact."""
    from .confidence import score_confidence
    return score_confidence(
        n_independent_support=n_independent_support,
        support_weight=support_weight, contradict_weight=contradict_weight,
        has_primary=has_primary, contradictions=contradictions,
        total_independent=total_independent)


def monitor(store: EvidenceStore, entity: str, limit: int = 60) -> dict:
    """§1.8 (global scope): contradiction watch over the shared graph —
    findings from ANY agent/module about one entity feed one monitor."""
    from .contradictions import detect_contradictions
    hits = store.search_signals(entity, limit=limit)
    flags = detect_contradictions(hits)
    return {"entity": entity, "signals_watched": len(hits),
            "conflict_flags": [{
                "description": f.description, "severity": f.severity.value,
            } for f in flags],
            "trust_label": "EVIDENCE"}


async def reassess_open_checks(store: EvidenceStore, limit: int = 10
                               ) -> list[dict]:
    """§1.10 — re-test recent ACTIVE fact-check hypotheses against the current
    graph; on verdict movement emit a VERDICT_CHANGE notification and record
    the old outcome in the body (old verdicts are never edited silently)."""
    emitted: list[dict] = []
    recent = [c for c in store.recent_checks(limit=50)
              if c["module"] == "factcheck"][:limit]
    if not recent:
        return emitted
    from .reasoning_engine import ReasoningEngine
    engine = ReasoningEngine(store)
    for c in recent:
        try:
            resp = await engine.reassess_case(c["id"])
        except Exception as exc:  # §20 — loop failure must not break ingest
            log.warning("reassess %s failed: %s", c["id"], exc)
            continue
        if resp is None or resp.verdict.value == c["outcome"]:
            continue
        nid = store.notify(
            kind="VERDICT_CHANGE",
            title=f"Verdict updated: {c['outcome']} → {resp.verdict.value}",
            body=(f"New evidence changed the assessment of \"{c['subject'][:120]}\". "
                  f"Previous outcome {c['outcome']} (confidence "
                  f"{c['confidence']}) is retained in the audit history; the "
                  f"current verdict is {resp.verdict.value} "
                  f"({resp.confidence.value}). What changed: "
                  f"{resp.what_would_change_conclusion or 'see evidence graph.'}"),
            ref=c["id"])
        emitted.append({"notification_id": nid, "check_id": c["id"],
                        "old": c["outcome"], "new": resp.verdict.value})
    return emitted


def _emit_s26(store: EvidenceStore, name: str, detail: str) -> None:
    """v4.3 — the §1.10 loop names its outputs with the spec's §26 event
    vocabulary (RiskRecalculated / JourneyConditionChanged); every caller
    of reassess_all (assurance sweep, /ops/reassess, post-ingest) inherits
    the naming — one emission site, never duplicated downstream."""
    store.audit(actor="trust-layer", action=f"event:{name}",
                decision="ALLOW", detail=detail,
                policy_version="trust-layer/1.10.0")


async def reassess_all(store: EvidenceStore) -> dict:
    """The full §1.10 loop — watches (VOYAGER) + open hypotheses (engine)
    + saved entity watchlists (§3.4 personalization drift alerts).
    v4.3: emits §26 RiskRecalculated / JourneyConditionChanged events for
    each movement it records (AlertTriggered fires from store.notify)."""
    from ..swarm.agents import voyager
    from . import personalization
    watch_notes = voyager.reassess_watches(store)
    check_notes = await reassess_open_checks(store)
    watchlist_notes = personalization.reassess_watchlists(store)
    for n in check_notes:
        _emit_s26(store, "RiskRecalculated",
                  f"check {n['check_id'][:12]}: {n['old']} → {n['new']}")
    for n in watchlist_notes:
        _emit_s26(store, "RiskRecalculated",
                  f"watchlist {str(n.get('entry', '?'))[:40]}: "
                  f"{n.get('old', '?')} → {n.get('new', '?')}")
    for n in watch_notes:
        _emit_s26(store, "JourneyConditionChanged",
                  f"watch {str(n.get('watch_id', '?'))[:12]}: "
                  f"{n.get('old', '?')} → {n.get('new', '?')}")
    return {"watch_notifications": watch_notes,
            "verdict_notifications": check_notes,
            "watchlist_notifications": watchlist_notes,
            "emitted": (len(watch_notes) + len(check_notes)
                        + len(watchlist_notes))}


def reassess_after_ingest(store: EvidenceStore) -> None:
    """Synchronous, failure-proof hook for the ingestion pipeline (§20-guarded).
    The async engine loop is scheduled fire-and-forget; watch reassessment
    (pure fixtures) runs inline."""
    from ..swarm.agents import voyager
    try:
        voyager.reassess_watches(store)
    except Exception as exc:
        log.warning("watch reassessment failed (non-fatal): %s", exc)
    try:
        from . import personalization
        personalization.reassess_watchlists(store)
    except Exception as exc:
        log.warning("watchlist reassessment failed (non-fatal): %s", exc)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(reassess_open_checks(store))
    except Exception as exc:
        log.warning("check reassessment scheduling failed (non-fatal): %s",
                    exc)
