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

from ...api.deps import get_db
from ...core import trust_layer
from ...core.errors import PipelineError
from ...swarm import cortex, pathfinder, registry
from ...swarm.agents import auditor, voyager

router = APIRouter(prefix="/api/v1", tags=["Unified Ops Node v3"])


class GoalRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    context: dict | None = None


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


@router.post("/ops/goal")
async def run_goal(req: GoalRequest, db=Depends(get_db)):
    """A-02: free-text goal → RGD task tree → UnifiedReport (canonical spine)."""
    return await pathfinder.run_goal(req.goal, db, context=req.context)


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
async def register_custom(req: CustomAgentRequest, db=Depends(get_db)):
    """A-13 + §5.2: AUDITOR validation gate; admission is SHADOW-mode only —
    execution rights come from a later HUMAN promotion."""
    verdict = auditor.validate_custom_agent(db, req.name, req.functions)
    if verdict["verdict"] == "REJECTED":
        return {"status": "REJECTED", **verdict}
    agent_id = f"CUSTOM-{req.name}"
    db.register_custom_agent(agent_id, req.name, req.functions,
                             status="SHADOW", drift_notes=None)
    return {"status": "SHADOW", "agent_id": agent_id, **verdict}


@router.post("/ops/agents/custom/{agent_id}/promote")
async def promote_custom(agent_id: str, db=Depends(get_db)):
    """§5.2: promotion is an external-effect governance action — AUTH'd via
    AUDITOR (REQUIRE_HUMAN), and the human's decision is on the trail."""
    agent = db.get_custom_agent(agent_id)
    if not agent:
        raise PipelineError("AGENT_NOT_FOUND", status=404)
    auth = auditor.authorize_action(db, actor="operator",
                                    action="promote_custom_agent",
                                    detail=f"promote {agent_id} to ACTIVE")
    # The operator calling this endpoint IS the human in the loop (R-05).
    db.update_custom_agent(agent_id, status="ACTIVE",
                           drift_notes=(agent.get("drift_notes") or "")
                           + f" | promoted by operator; auth={auth['decision']}")
    db.notify(kind="GOVERNANCE",
              title=f"Custom agent promoted: {agent['name']}",
              body=f"{agent_id} moved SHADOW → ACTIVE by an operator. "
                   f"Shadow trees observed: {agent.get('shadow_tree_count', 0)}.",
              ref=agent_id)
    return {"agent_id": agent_id, "status": "ACTIVE",
            "audit": auth}


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
        departure_time=dep, priority=req.priority, tolerance=tolerance)
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
        "policy_version": registry.POLICY_VERSION,
        "note": ("Demo-profile latencies are in-process; the shape is the "
                 "production contract (throughput, failure mix, per-agent "
                 "latency, failover count)."),
    }


@router.get("/ops/audit")
async def audit(db=Depends(get_db)):
    return {"audit_trail": db.audit_trail(),
            "policy_version": registry.POLICY_VERSION}
