"""Investigation chronology — v4.8 (§67 immutable investigation chronology).

The spec(§67): every investigation has an **immutable chronology**. Ours is
*derived*, not stored: the permanent, append-only audit trail + the case
link table + the case row itself ARE the chronology's atoms; this module
assembles them deterministically and commits to the assembly with a digest.

Why derived-not-stored: a second, separate chronology table would be a
second source of truth that could diverge (and would have to be trusted on
its own). Here there is exactly one history (the audit trail, PERMANENT by
retention invariant since v4.4); the chronology is a faithful read of it,
and the **digest lets any auditor detect history edits**: recompute →
different digest ⇒ someone touched the trail. Immutability is the trail's
property; the digest makes tampering *visible*.

Derivation scoping (stated honestly, §20): trail rows are matched to the
case by the investigation id appearing in the detail text (the §26 events
minted by v4.0+ flows all carry it); case-opened comes from the case row
itself because `InvestigationCreated` precedes the id-bearing convention.
Link events come from the link table, whose rows are case-scoped by
column. That's the whole claim — no inference beyond string equality.
"""
from __future__ import annotations

import hashlib
import json

from .errors import PipelineError

CHRONOLOGY_VERSION = "chronology/4.8.0"

_KIND_BY_EVENT = {
    "InvestigationCreated": "LIFECYCLE",
    "InvestigationClosed": "LIFECYCLE",
    "AuthorizationDenied": "AUTHORIZATION",
    "AuthorizationExpired": "AUTHORIZATION",
    "SourceQueried": "OBSERVATION",
    "ObservationReceived": "OBSERVATION",
    "ObservationChanged": "OBSERVATION",
    "ObservationRerun": "OBSERVATION",
    "AlertTriggered": "ALERT",
    "ApprovalRequested": "GOVERNANCE",
    "ApprovalGranted": "GOVERNANCE",
    "ApprovalRejected": "GOVERNANCE",
    "EvidenceLinked": "LINK",
}


def _kind_of(action: str) -> str:
    if action.startswith("event:"):
        return _KIND_BY_EVENT.get(action.split(":", 1)[1], "EVENT")
    return "TRAIL"


def _digest(events: list[dict]) -> str:
    blob = json.dumps(
        [(e["at"], e["actor"], e["action"], e["decision"], e["detail"])
         for e in events],
        ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{CHRONOLOGY_VERSION}|{blob}".encode()).hexdigest()


def build_chronology(store, investigation_id: str) -> dict:
    inv = store.inv_get(investigation_id)
    if not inv:
        raise PipelineError("INV_NOT_FOUND", status=404,
                            detail=f"investigation {investigation_id} does "
                                   "not exist.")
    # 1. case-opened from the case row (InvestigationCreated predates the
    #    id-bearing event convention — stated in the derivation note)
    events: list[dict] = [{
        "at": inv["created_at"], "actor": inv.get("user_id") or "unknown",
        "action": "case:Opened", "decision": "ALLOW",
        "kind": "LIFECYCLE",
        "detail": (f"case opened: {inv['objective'][:80]} "
                   f"[{inv['subject_type']}:{inv['subject']}] authority="
                   f"{inv['authority']} expiry={inv['expires_at'][:10]}"),
    }]
    if inv["status"] == "CLOSED":
        # closed state from the row; any InvestigationClosed event in the
        # trail will also match below and add its own richer detail
        pass
    # 2. trail rows scoped to this case (id in detail; ASC ordering + kind)
    trail = store.kpi_sql(
        """SELECT actor, action, decision, detail, created_at, policy_version
           FROM audit_trail WHERE detail LIKE ?
           ORDER BY created_at ASC, rowid ASC""",
        (f"%{investigation_id}%",))
    for r in trail:
        events.append({
            "at": r["created_at"], "actor": r["actor"],
            "action": r["action"], "decision": r["decision"],
            "kind": _kind_of(r["action"]), "detail": r["detail"],
            "policy_version": r.get("policy_version"),
        })
    # 3. link-table events (case-scoped by column, not text-match)
    for l in store.inv_links_for(investigation_id):
        events.append({
            "at": l["created_at"], "actor": "investigation-core",
            "action": f"link:{l['kind']}", "decision": "ALLOW",
            "kind": "LINK",
            "detail": f"{l['kind']} {l['ref_id'][:24]} linked into the case",
        })
    events.sort(key=lambda e: (e["at"] or "", e["action"]))
    return {
        "investigation_id": investigation_id,
        "subject": f"{inv['subject_type']}:{inv['subject']}",
        "status": inv["status"],
        "chronology_version": CHRONOLOGY_VERSION,
        "event_count": len(events),
        "digest": _digest(events),
        "events": events,
        "derivation": (
            "Derived on read from the permanent audit trail (rows whose "
            "detail names this case id), the case link table (column-"
            "scoped), and the case row (case-opened). Nothing here is a "
            "second history — recompute and compare digest to detect trail "
            "edits (§67). Pre-v4.0 case events may predate the id-bearing "
            "convention; those cases' trails are thinner, not padded."),
    }
