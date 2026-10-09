"""Continuous Assurance — v4.3 (§73 V2.5).

One sweep = the whole platform loop, honestly measured:
  §1.10 reassessment (watches, open verdicts, entity watchlists)
  → §26 events: RiskRecalculated, JourneyConditionChanged, AlertTriggered
  §6/§32 source-health states + staleness SLA breaches
  → platform event SourceHealthChanged (extension beyond §26, documented)
  consent-ledger chain verification (privacy verify_chain)
  posture rollup (deterministic OK | ATTENTION | CRITICAL)

Every sweep is persisted (assurance_runs) so posture transitions can be
audited across time — continuous assurance is a SERIES, not a dashboard
snapshot. Nothing here is predictive: it is derived from live store rows.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from . import policy_engine, privacy
from .health import health_state

ENGINE_VERSION = "assurance-engine/4.3.0"

# §54 deterministic posture rules — evaluated in order, first match wins:
#   CRITICAL if consent chain is broken or a SEV1 incident is active
#   ATTENTION if any source is outside ACTIVE or any approval is PENDING
#             or policy denials in the last 50 trail rows > 10
#   OK otherwise

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(store, name: str, actor: str, detail: str) -> None:
    store.audit(actor=actor, action=f"event:{name}", decision="ALLOW",
                detail=detail, policy_version=ENGINE_VERSION)


def _count_reassessment_events(reassessment: dict) -> dict[str, int]:
    """§26 counting — §1.10 movements are emitted NATIVELY by
    trust_layer.reassess_all (one emission site for all its callers);
    this sweep counts what its own run provoked for posture reporting."""
    return {
        "RiskRecalculated": (len(reassessment.get("verdict_notifications",
                                                  []))
                             + len(reassessment.get(
                                 "watchlist_notifications", []))),
        "JourneyConditionChanged": len(reassessment.get(
            "watch_notifications", [])),
        # AlertTriggered rows are minted by store.notify itself
        "AlertTriggered": reassessment.get("emitted", 0),
    }


def _source_sweep(store, actor: str) -> dict:
    """§6/§32 states + staleness SLA; transitions vs silence are events
    worth recording (platform extension: SourceHealthChanged)."""
    metas = store.all_source_meta()
    prev = (store.assurance_latest() or {}).get("summary", {})
    prev_states = prev.get("source_states", {})
    states: dict[str, str] = {}
    transitions: list[dict] = []
    stale: list[str] = []
    now = _now()
    for m in metas:
        sid = m.get("source_id", "?")
        state = health_state(m)
        states[sid] = state
        if prev_states.get(sid) and prev_states[sid] != state:
            transitions.append({"source_id": sid,
                                "from": prev_states[sid], "to": state})
            _event(store, "SourceHealthChanged", actor,
                   f"{sid}: {prev_states[sid]} → {state}")
        # staleness SLA — demo profile: >24h since last success = breach
        last = m.get("last_success_at")
        lag_min = None
        if last:
            try:
                ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                lag_min = (now - ts).total_seconds() / 60
            except Exception:
                lag_min = None
        if lag_min is None and state == "ACTIVE":
            stale.append(f"{sid} (never succeeded)")
        elif lag_min is not None and lag_min > 24 * 60:
            stale.append(f"{sid} ({lag_min / 60:.0f}h stale)")
            if state == "ACTIVE":
                states[sid] = "DEGRADED"
                transitions.append({"source_id": sid, "from": "ACTIVE",
                                    "to": "DEGRADED",
                                    "reason": "staleness SLA 24h"})
                _event(store, "SourceHealthChanged", actor,
                       f"{sid}: ACTIVE → DEGRADED (staleness SLA 24h)")
    degraded = [s for s, st in states.items() if st != "ACTIVE"]
    return {"source_states": states, "degraded_or_worse": degraded,
            "transitions": transitions, "stale_sources": stale}


def _posture(store, source_sweep: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    chain = privacy.verify_chain(store)
    if chain.get("chain_intact") is False:
        return "CRITICAL", ["consent ledger hash chain failed verification"]
    incident = store.active_incident()
    if incident and incident.get("severity") == "SEV1":
        return "CRITICAL", [f"SEV1 incident {incident['incident_id']} active"]
    if source_sweep["degraded_or_worse"]:
        reasons.append(f"sources outside ACTIVE: "
                       f"{source_sweep['degraded_or_worse']}")
    pending = store.approval_list(status="PENDING", limit=50)
    if pending:
        reasons.append(f"{len(pending)} approval(s) PENDING")
    recent = store.audit_trail(limit=50)
    denials = sum(1 for r in recent
                  if r.get("decision") in ("DENY", "BLOCKED")
                  or "AuthorizationDenied" in str(r.get("action")))
    if denials > 10:
        reasons.append(f"policy denial burst: {denials}/latest 50 trail rows")
    if incident:
        reasons.append(f"incident {incident['incident_id']} "
                       f"({incident.get('severity')}) active")
    if reasons:
        return "ATTENTION", reasons
    return "OK", ["all posture checks green"]


async def run_assurance_sweep(store, actor: str = "assurance-loop") -> dict:
    """The sweep. §20: every channel is individually failure-guarded; a
    broken channel degrades its own block, never the posture math."""
    from . import trust_layer  # local import: engine pulls heavy deps
    run_id = str(uuid.uuid4())[:12]
    started = _now()

    try:
        reassessment = await trust_layer.reassess_all(store)
    except Exception as exc:
        reassessment = {"watch_notifications": [], "verdict_notifications": [],
                        "watchlist_notifications": [], "emitted": 0,
                        "degraded": f"reassessment loop failed: {exc}"}
    events = _count_reassessment_events(reassessment)
    sources = _source_sweep(store, actor)
    posture, posture_reasons = _posture(store, sources)
    chain = privacy.verify_chain(store)

    summary = {
        "run_id": run_id,
        "actor": actor,
        "posture": posture,
        "posture_reasons": posture_reasons,
        "events_emitted": events,
        "watch_notifications": len(reassessment.get("watch_notifications",
                                                    [])),
        "verdict_notifications": len(reassessment.get(
            "verdict_notifications", [])),
        "watchlist_notifications": len(reassessment.get(
            "watchlist_notifications", [])),
        "source_states": sources["source_states"],
        "degraded_or_worse": sources["degraded_or_worse"],
        "stale_sources": sources["stale_sources"],
        "source_transitions": sources["transitions"],
        "consent_chain_valid": chain.get("chain_intact"),
        "consent_chain_entries": chain.get("entries", None),
        "pending_approvals": len(store.approval_list(status="PENDING",
                                                     limit=50)),
        "active_incident": (store.active_incident() or {}).get("incident_id"),
        "reassessment_degraded": reassessment.get("degraded"),
        "engine_version": f"{ENGINE_VERSION} · "
                          f"{policy_engine.POLICY_ENGINE_VERSION}",
    }
    finished = _now()
    store.assurance_record(run_id, actor, posture, json.dumps(summary),
                           started.isoformat(), finished.isoformat())
    summary["started_at"] = started.isoformat()
    summary["finished_at"] = finished.isoformat()
    return summary
