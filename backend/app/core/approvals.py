"""Approval Engine — v4.2 (§73 V2). §27/R-05 made a first-class object.

REQUIRE_HUMAN policy decisions need a durable, listable, decidable record:
    request (§26 ApprovalRequested) → PENDING
    human decides                  → APPROVED (§26 ApprovalGranted)
                                   | REJECTED  (event:ApprovalRejected)

Single-step flows (an operator calling an endpoint IS the human — R-05)
run request+decide in one call so the API stays simple, but the record and
both §26 events always exist. Effects execute ONLY after APPROVED — the
approval engine calls the provided on_approval hook; denial runs nothing.

Double-decides are refused with a classified 409 (§20: never silent).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .errors import PipelineError
from ..swarm import registry

ENGINE_VERSION = "approval-engine/4.2.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(store, name: str, actor: str, detail: str) -> None:
    store.audit(actor=actor, action=f"event:{name}", decision="ALLOW",
                detail=detail, policy_version=ENGINE_VERSION)


def request(store, *, kind: str, subject_ref: str, summary: str,
            requester: str, context: dict | None = None) -> dict:
    """§26 ApprovalRequested — durable PENDING record."""
    aid = str(uuid.uuid4())[:12]
    store.approval_create(aid, kind, subject_ref, summary, requester,
                          json.dumps(context or {}))
    _event(store, "ApprovalRequested", requester,
           f"{kind} for {subject_ref}: {summary[:120]}")
    return store.approval_get(aid)


def decide(store, approval_id: str, *, approved: bool,
           decided_by: str, on_approval=None) -> dict:
    """Approve → §26 ApprovalGranted (+ execute effect hook); reject →
    §26-style ApprovalRejected, effect NEVER runs."""
    row = store.approval_get(approval_id)
    if not row:
        raise PipelineError("TREE_NOT_FOUND", status=404,
                            detail=f"approval {approval_id} not found")
    changed = store.approval_decide(approval_id,
                                    "APPROVED" if approved else "REJECTED",
                                    decided_by)
    if changed != 1:
        raise PipelineError("APPROVAL_NOT_PENDING", status=409,
                            detail=f"approval is {row['status']}, not PENDING")
    if approved:
        _event(store, "ApprovalGranted", decided_by,
               f"{row['kind']} for {row['subject_ref']} approved by "
               f"{decided_by}")
        if on_approval is not None:
            on_approval(row)
    else:
        _event(store, "ApprovalRejected", decided_by,
               f"{row['kind']} for {row['subject_ref']} rejected by "
               f"{decided_by}")
    return store.approval_get(approval_id)


def request_and_decide(store, *, kind: str, subject_ref: str, summary: str,
                       actor: str, context: dict | None = None,
                       on_approval=None) -> dict:
    """Single-step flow: the calling operator is the human (R-05). The
    request and the grant are still two distinct on-trail events."""
    req = request(store, kind=kind, subject_ref=subject_ref,
                  summary=summary, requester=actor, context=context)
    return decide(store, req["id"], approved=True, decided_by=actor,
                  on_approval=on_approval)
