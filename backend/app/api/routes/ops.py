"""Unified Ops Node v3 API — spec §2/A-01, §3.1-3.3, §5.1-5.2.

Single-pane endpoints behind the Ops Node view:
  POST /api/v1/ops/goal            one-shot goal → task tree → UnifiedReport
  GET  /api/v1/ops/tree/{id}       Strategy Map (tree + task states)
  GET  /api/v1/ops/trees           recent task trees (Swarm Timeline source)
  POST /api/v1/ops/tree/{id}/resume PATHFINDER peer failover (§3.3)
  GET  /api/v1/ops/mesh            orchestration mesh status
  GET  /api/v1/ops/agents          agent roster + A-14 allowlists
  POST /api/v1/ops/agents/custom   SDK custom-agent admission (§5.2, SHADOW)
  POST /api/v1/ops/agents/custom/{id}/promote  human promotion (REQUIRE_HUMAN)
  POST /api/v1/cortex/chat         Conversational Cortex (§3.1)
  GET  /api/v1/ops/notifications   §1.10 verdict-change alerts
  POST /api/v1/ops/reassess        trigger the continual reassessment loop
  POST /api/v1/ops/journey/watch   VOYAGER monitor_active_journey enrolment
  GET  /api/v1/ops/journey/watches active journey watches
  GET  /api/v1/ops/kpis            sovereign statistics (§3.3 metrics)
  GET  /api/v1/ops/audit           AUDITOR trail (A-06)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...api.deps import current_user, get_db
from ...core import agent_inventory as agent_inventory_mod
from ...core import approvals, assurance, rbac, trust_layer
from ...core.errors import PipelineError
from ...swarm import cortex, incident, pathfinder, registry
from ...swarm.agents import auditor, voyager

router = APIRouter(prefix="/api/v1", tags=["Unified Ops Node v3"])


class GoalRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    context: dict | None = None
    investigation_id: str | None = None  # v4.0 §2: §63 authorization object


class CortexRequest(BaseModel):
    session_id: str = Field(min_length=4, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class CustomAgentRequest(BaseModel):
    name: str = Field(min_length=3, max_length=40)
    functions: list[str] = Field(min_length=1, max_length=20)


class WatchRequest(BaseModel):
    origin: str
    destination: str
    departure_time: str | None = None
    priority: str = "balanced"
    tolerance: str | None = None  # §3.4 defaults to user's preference
    user_id: str | None = None    # §3.4 personalization (presentation only)


class IncidentRequest(BaseModel):
    severity: str  # SEV1 | SEV2 | SEV3
    summary: str = Field(min_length=5, max_length=2000)
    declared_by: str = Field(min_length=1, max_length=64)


# ------------------------------------- v3.2 blocker G: crisis pathway ----
@router.post("/ops/incident/declare")
async def declare_incident(req: IncidentRequest, db=Depends(get_db)):
    """Incident Declaration — functional crisis pathway: records the SEV,
    fires the audit trail + notification center, attempts external delivery
    (webhook), and returns the response checklist. Never cosmetic."""
    return await incident.declare(db, severity=req.severity,
                                  summary=req.summary,
                                  declared_by=req.declared_by)


@router.get("/ops/incident/active")
async def active_incident(db=Depends(get_db)):
    """Powers the crisis-mode banner: UI simplifies while an incident is
    ACTIVE (checklist shown, motion reduced — review risk #10)."""
    inc = db.active_incident()
    if inc:
        # v3.5 — the checklist + guidance travel WITH the active state so the
        # banner/restored sessions render identically to the declare response
        inc = {**inc, "checklist": incident.RESPONSE_CHECKLIST,
               "ui_guidance": incident.UI_GUIDANCE}
    return {"incident": inc}


@router.get("/ops/incidents")
async def list_incidents(db=Depends(get_db)):
    return {"incidents": db.list_incidents()}


@router.post("/ops/incident/{incident_id}/resolve")
async def resolve_incident(incident_id: str, db=Depends(get_db)):
    inc = db.active_incident()
    if not inc or inc["incident_id"] != incident_id:
        raise PipelineError("INCIDENT_NOT_FOUND", status=404)
    db.resolve_incident(incident_id)
    db.audit(actor="operator", action="incident_resolved", decision="ALLOW",
             detail=f"{incident_id} resolved",
             policy_version=registry.POLICY_VERSION)
    return {"incident_id": incident_id, "status": "RESOLVED"}


@router.post("/cortex/session/{session_id}/purge")
async def purge_session(session_id: str, db=Depends(get_db)):
    """v3.2 exit ramp: erase a conversational context now (don't wait for
    the 1h TTL) — §25 minimization on demand."""
    removed = cortex.purge_session(session_id)
    db.audit(actor=session_id, action="safety_event:session_purged",
             decision="ALLOW", detail=f"cortex session {session_id[:12]} "
             f"purged ({removed} entries)",
             policy_version=registry.POLICY_VERSION)
    return {"session_id": session_id, "purged_entries": removed}


@router.post("/ops/goal")
async def run_goal(req: GoalRequest, db=Depends(get_db)):
    """A-02: free-text goal → RGD task tree → UnifiedReport (canonical spine).
    For the review-gated flow (checklist D) use /ops/plan → /approve.
    v4.0 §2 — pass investigation_id to enforce the §63 authorization."""
    return await pathfinder.run_goal(req.goal, db, context=req.context,
                                     investigation_id=req.investigation_id)


# ------------------------------------- v3.2 plan review (checklist D) ----
@router.post("/ops/plan")
async def propose(req: GoalRequest, db=Depends(get_db)):
    """Plan Review gate: decompose WITHOUT executing — user approves first.
    v4.0 §2 — pass investigation_id to enforce the §63 authorization."""
    return pathfinder.propose_plan(req.goal, db, context=req.context,
                                   investigation_id=req.investigation_id)


@router.post("/ops/tree/{tree_id}/approve")
async def approve(tree_id: str, db=Depends(get_db)):
    out = await pathfinder.approve_plan(tree_id, db)
    if out.get("classified_error") == "TREE_NOT_FOUND":
        raise PipelineError("TREE_NOT_FOUND", status=404)
    return out


@router.post("/ops/tree/{tree_id}/reject")
async def reject(tree_id: str, db=Depends(get_db)):
    out = pathfinder.reject_plan(tree_id, db)
    if out.get("classified_error"):
        raise PipelineError("TREE_NOT_FOUND", status=404)
    return out


# ------------------------------------- v3.2 blocker E: halt / delete -----
@router.post("/ops/tree/{tree_id}/halt")
async def halt(tree_id: str, db=Depends(get_db)):
    """Halt Execution — user-controlled stop of a running tree."""
    out = pathfinder.halt_tree(tree_id, db)
    if out.get("classified_error"):
        raise PipelineError("TREE_NOT_FOUND", status=404)
    return out


@router.delete("/ops/tree/{tree_id}")
async def delete_tree(tree_id: str, db=Depends(get_db)):
    """Exit ramp: permanently delete a generated report/tree (risk #9)."""
    if not db.get_tree(tree_id):
        raise PipelineError("TREE_NOT_FOUND", status=404)
    counts = db.delete_tree(tree_id)
    db.audit(actor="operator", action="safety_event:tree_deleted",
             decision="ALLOW", detail=f"tree {tree_id} deleted by user "
             f"({counts['tasks_deleted']} tasks)",
             policy_version=registry.POLICY_VERSION)
    return {"tree_id": tree_id, "deleted": True, **counts,
            "note": "Report and task records permanently removed. Logged "
                    "on the audit trail (deletion itself is auditable)."}


@router.get("/ops/tree/{tree_id}")
async def get_tree(tree_id: str, db=Depends(get_db)):
    tree = db.get_tree(tree_id)
    if not tree:
        raise PipelineError("TREE_NOT_FOUND", status=404)
    return tree


@router.get("/ops/trees")
async def list_trees(db=Depends(get_db)):
    return {"trees": db.list_trees()}


@router.post("/ops/tree/{tree_id}/resume")
async def resume(tree_id: str, db=Depends(get_db)):
    """§3.3 failover path — a surviving peer resumes from persisted state."""
    if not db.get_tree(tree_id):
        raise PipelineError("TREE_NOT_FOUND", status=404)
    return await pathfinder.resume_tree(tree_id, db)


@router.get("/ops/mesh")
async def mesh(db=Depends(get_db)):
    return pathfinder.MESH.status()


@router.get("/ops/agents")
async def agents(db=Depends(get_db)):
    return {"agents": registry.roster(db),
            "policy_version": registry.POLICY_VERSION}


@router.post("/ops/agents/custom")
async def register_custom(req: CustomAgentRequest, db=Depends(get_db),
                          user=Depends(current_user)):
    """A-13 + §5.2: AUDITOR validation gate; admission is SHADOW-mode only —
    execution rights come from a later HUMAN promotion.
    v4.4: requires RBAC 'agents.register' (analyst+)."""
    rbac.require_role(user, "agents.register")
    verdict = auditor.validate_custom_agent(db, req.name, req.functions)
    if verdict["verdict"] == "REJECTED":
        return {"status": "REJECTED", **verdict}
    agent_id = f"CUSTOM-{req.name}"
    db.register_custom_agent(agent_id, req.name, req.functions,
                             status="SHADOW", drift_notes=None)
    return {"status": "SHADOW", "agent_id": agent_id, **verdict}


@router.post("/ops/agents/custom/{agent_id}/promote")
async def promote_custom(agent_id: str, db=Depends(get_db),
                         user=Depends(current_user)):
    rbac.require_role(user, "agents.promote")
    """§5.2: promotion is an external-effect governance action — AUTH'd via
    AUDITOR (REQUIRE_HUMAN), and the human's decision is on the trail.
    v4.2: runs THROUGH the approval engine — an ApprovalRequested +
    ApprovalGranted pair is minted for every promotion; the effect
    (status flip) executes only from the grant hook."""
    agent = db.get_custom_agent(agent_id)
    if not agent:
        raise PipelineError("AGENT_NOT_FOUND", status=404)
    auth = auditor.authorize_action(db, actor="operator",
                                    action="promote_custom_agent",
                                    detail=f"promote {agent_id} to ACTIVE")

    def _effect(row):  # executes ONLY on the grant hook (never on reject)
        db.update_custom_agent(
            agent_id, status="ACTIVE",
            drift_notes=(agent.get("drift_notes") or "")
            + f" | promoted by operator; auth={auth['decision']}; "
              f"approval={row['id']}")
        db.notify(kind="GOVERNANCE",
                  title=f"Custom agent promoted: {agent['name']}",
                  body=f"{agent_id} moved SHADOW → ACTIVE by an operator. "
                       f"Shadow trees observed: "
                       f"{agent.get('shadow_tree_count', 0)}.",
                  ref=agent_id)

    # The operator calling this endpoint IS the human in the loop (R-05) —
    # one call, but the request/grant pair is two distinct on-trail events.
    approval = approvals.request_and_decide(
        db, kind="promote_custom_agent", subject_ref=agent_id,
        summary=f"promote {agent_id} SHADOW → ACTIVE", actor="operator",
        context={"shadow_tree_count": agent.get("shadow_tree_count", 0),
                 "auditor_decision": auth["decision"]},
        on_approval=_effect)
    return {"agent_id": agent_id, "status": "ACTIVE",
            "audit": auth, "approval": approval}


# --------------------------------- v4.2 governance planes (§73 V2) --------
@router.get("/ops/approvals")
async def list_approvals(status: str | None = None, limit: int = 50,
                         db=Depends(get_db)):
    """Approval engine queue — the durable surface for REQUIRE_HUMAN
    policy decisions (§27/R-05)."""
    return {"approvals": db.approval_list(status=status, limit=limit)}


class ApprovalDecision(BaseModel):
    decided_by: str = "operator"


@router.post("/ops/approvals/{approval_id}/approve")
async def approve(approval_id: str, req: ApprovalDecision,
                  db=Depends(get_db), user=Depends(current_user)):
    """§26 ApprovalGranted. Effects: only kinds the engine knows how to
    execute are wired (promotions execute from the promote flow itself).
    v4.4: requires RBAC 'approvals.decide' (governance+)."""
    rbac.require_role(user, "approvals.decide")
    return approvals.decide(db, approval_id, approved=True,
                            decided_by=req.decided_by)


@router.post("/ops/approvals/{approval_id}/reject")
async def reject(approval_id: str, req: ApprovalDecision,
                 db=Depends(get_db), user=Depends(current_user)):
    """Rejection — the effect NEVER ran, and that fact is on the trail.
    v4.4: requires RBAC 'approvals.decide' (governance+)."""
    rbac.require_role(user, "approvals.decide")
    return approvals.decide(db, approval_id, approved=False,
                            decided_by=req.decided_by)


@router.get("/ops/agents/inventory")
async def agent_inventory(db=Depends(get_db), user=Depends(current_user)):
    rbac.require_role(user, "inventory.read")
    """V2 agent supply chain: per-node cards (owner/version/source/
    publisher/permissions/credentials/trust/last reviewed/known issue/
    runtime exposure/data classification) + NIST-RMF readiness summary."""
    return agent_inventory_mod.inventory(db)


# --------------------------------- v4.3 continuous assurance (§73 V2.5) ---
@router.post("/ops/assurance/sweep")
async def assurance_sweep(db=Depends(get_db), user=Depends(current_user)):
    rbac.require_role(user, "assurance.sweep")
    """Run a full assurance sweep: §1.10 reassessment (named §26 events),
    §6/§32 source-health states + staleness SLA, consent-chain verification,
    posture rollup. Persisted so posture is a SERIES, not a snapshot."""
    return await assurance.run_assurance_sweep(db, actor="operator")


@router.get("/ops/assurance/status")
async def assurance_status(limit: int = 10, db=Depends(get_db)):
    """Latest sweep + series: recent posture timeline for the Governance."""
    runs = db.assurance_list(limit=max(1, min(limit, 50)))
    latest = runs[0] if runs else None
    return {
        "latest": latest,
        "series": [{"id": r["id"], "posture": r["posture"],
                    "started_at": r["started_at"]} for r in runs],
        "note": ("Continuous assurance is a series — sweep history is the "
                 "audit of the audit plane. One run per operator request in "
                 "the demo profile (§20: scheduled cadence is a V2.5+ "
                 "enterprise connector, stated not faked)."),
    }


@router.post("/cortex/chat")
async def cortex_chat(req: CortexRequest, db=Depends(get_db)):
    """§3.1 Conversational Cortex — dialogue → task tree, context retained."""
    return await cortex.chat(db, req.session_id, req.message)


@router.get("/ops/notifications")
async def notifications(db=Depends(get_db)):
    return {"notifications": db.list_notifications()}


@router.post("/ops/reassess")
async def reassess(db=Depends(get_db)):
    """§1.10 continual reassessment — fires verdict/risk-change alerts."""
    return await trust_layer.reassess_all(db)


@router.post("/ops/journey/watch")
async def start_watch(req: WatchRequest, db=Depends(get_db)):
    from datetime import datetime
    from ...core import personalization
    dep = None
    if req.departure_time:
        dep = datetime.fromisoformat(req.departure_time)
    # §3.4 — threshold default comes from the user's preferences when no
    # explicit tolerance is passed. Preferences gate ALERTS, never scores.
    tolerance = req.tolerance or personalization.default_watch_tolerance(
        db, req.user_id)
    out = voyager.monitor_active_journey(
        db, origin=req.origin, destination=req.destination,
        departure_time=dep, priority=req.priority, tolerance=tolerance,
        user_id=req.user_id)
    out["tolerance_source"] = ("preference" if not req.tolerance and
                               req.user_id else "explicit/default")
    return out


@router.get("/ops/journey/watches")
async def watches(db=Depends(get_db)):
    return {"watches": db.list_watches(active_only=False)}


@router.get("/ops/kpis")
async def kpis(db=Depends(get_db)):
    """§3.3/v2 §4 metrics opacity — orchestrator KPIs now exposed:
    task throughput/status mix, per-agent latency, tree outcomes, mesh
    failovers, review pressure, notification volume."""
    tasks = db.all_tasks()
    status_mix: dict[str, int] = {}
    agent_lat: dict[str, list[float]] = {}
    from ...core.nlp_lite import parse_iso
    for t in tasks:
        status_mix[t["status"]] = status_mix.get(t["status"], 0) + 1
        st, en = parse_iso(t.get("started_at")), parse_iso(t.get("ended_at"))
        if st and en:
            agent_lat.setdefault(t["agent"], []).append(
                (en - st).total_seconds())
    per_agent = {a: {"tasks": len(v),
                     "avg_latency_s": round(sum(v) / len(v), 3)}
                 for a, v in agent_lat.items()}
    trees = db.list_trees(limit=200)
    tree_outcomes: dict[str, int] = {}
    for r in trees:
        tree_outcomes[r["status"]] = tree_outcomes.get(r["status"], 0) + 1
    return {
        "tasks_total": len(tasks),
        "task_status_mix": status_mix,
        "per_agent": per_agent,
        "tree_outcomes": tree_outcomes,
        "mesh_failovers": pathfinder.MESH.failovers,
        "review_queue_depth": len(db.review_queue()),
        "notifications_total": len(db.list_notifications(limit=200)),
        # v3.2 checklist J — safety learning loop surfaced to dashboards
        "safety_events": db.safety_event_counts(),
        "policy_version": registry.POLICY_VERSION,
        "note": ("Demo-profile latencies are in-process; the shape is the "
                 "production contract (throughput, failure mix, per-agent "
                 "latency, failover count)."),
    }


@router.get("/ops/audit")
async def audit(db=Depends(get_db)):
    return {"audit_trail": db.audit_trail(),
            "policy_version": registry.POLICY_VERSION}


@router.get("/ops/stream")
def sovereign_stream(limit: int = 60, db=Depends(get_db)):
    """Blueprint v5.2 §3.B — Sovereign Data Stream: a low-level, honest blend
    of PERSISTED audit events (A-06 trail — the source of truth) and LIVE
    volatile pulses (in-memory mesh heartbeats, marked as such, §20)."""
    from datetime import datetime, timezone
    limit = max(1, min(limit, 120))
    events: list[dict] = []
    for row in db.audit_trail(limit):
        events.append({
            "kind": "audit", "persistence": "persisted",
            "ts": row["created_at"],
            "actor": row.get("actor", "?"),
            "text": f"{row.get('action','?')} → {row.get('decision','?')}",
            "detail": row.get("detail", "")})
    mesh = pathfinder.MESH.status()
    peers_up = sum(1 for p in mesh["peers"] if p["alive"])
    events.append({
        "kind": "heartbeat", "persistence": "live",
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": mesh["primary"],
        "text": f"heartbeat tick — {peers_up}/{mesh['peer_count']} peers up, "
                f"primary {mesh['primary']}, failovers {mesh['failovers']}",
        "detail": "volatile in-memory pulse (durable record = audit trail)"})
    events.sort(key=lambda e: e["ts"], reverse=True)
    return {"events": events[:limit], "mesh": mesh,
            "note": ("Persisted rows come from the append-only audit trail; "
                     "live rows are volatile pulses and are labelled as such.")}
