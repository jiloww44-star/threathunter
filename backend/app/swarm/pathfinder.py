"""PATHFINDER orchestration mesh — spec A-02, §3.3, §6.

Recursive Goal Decomposition (RGD): free-text goal → TaskTreeJSON →
DispatchPlan → parallel branch execution → UnifiedReport synthesis.

Governance invariants (never bypassed):
- A-14: every task dispatch passes registry.check_dispatch allowlists.
- A-06: every tree carries a non-blocking AUDITOR compliance overlay (C-07).
- §27/R-05: external-effect actions land in REQUIRE_HUMAN states.
- §20: failures surface as classified task states, never silent.
- §6: the UnifiedReport always carries the canonical spine.

Peer redundancy (§3.3): the mesh registers 2N orchestrator peers (env
TH360_OPS_PEERS, default 2). Every task transition is persisted to the shared
store (state-machine replication), so a surviving peer can resume any RUNNING
tree via resume_tree(). TH360_OPS_PEER_DOWN=1 simulates losing the primary —
used by the P1 failover test.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from ..models.schemas import Confidence, JourneyRequest
from ..store.db import EvidenceStore
from . import registry
from .agents import auditor, hunter, sentinel, voyager

log = logging.getLogger("th360.pathfinder")

# ------------------------------------------------------------ task states --
PENDING, RUNNING = "PENDING", "RUNNING"
COMPLETE, DEGRADED, FAILED = "COMPLETE", "DEGRADED", "FAILED"
BLOCKED, AWAITING_HUMAN = "BLOCKED", "AWAITING_HUMAN"


# ------------------------------------------------------------- peer mesh ---
class OrchestrationMesh:
    """§3.3 — 2N PATHFINDER peers with state-machine replication of tree
    state into the shared store; any peer can resume a tree (failover <5s by
    design goal — resume is a store re-read)."""

    def __init__(self):
        n = max(2, int(os.getenv("TH360_OPS_PEERS", "2")))
        n += n % 2  # force 2N
        self.peers = [{"peer_id": f"pathfinder-{i+1:02d}",
                       "role": "primary" if i == 0 else "replica", "alive": True}
                      for i in range(n)]
        self._primary = 0
        self.failovers = 0
        self.policy_version = registry.POLICY_VERSION

    @property
    def primary(self) -> dict:
        return self.peers[self._primary]

    def primary_id(self) -> str:
        if os.getenv("TH360_OPS_PEER_DOWN") == "1":
            # §3.3 simulated partition: primary considered lost pre-dispatch
            self.failover("simulated-partition (TH360_OPS_PEER_DOWN)")
        return self.primary["peer_id"]

    def failover(self, reason: str) -> dict:
        old = self.primary
        old["alive"] = False
        self._primary = (self._primary + 1) % len(self.peers)
        while not self.peers[self._primary]["alive"]:
            self._primary = (self._primary + 1) % len(self.peers)
        self.peers[self._primary]["role"] = "primary"
        # demote old primary's role for a clean status picture
        old["role"] = "replica"
        self.failovers += 1
        log.warning("PATHFINDER failover: %s → %s (%s)",
                    old["peer_id"], self.primary["peer_id"], reason)
        return {"from": old["peer_id"], "to": self.primary["peer_id"],
                "reason": reason, "failovers": self.failovers}

    def status(self) -> dict:
        return {"peers": self.peers, "primary": self.primary["peer_id"],
                "peer_count": len(self.peers), "failovers": self.failovers,
                "replication": "task transitions persisted to shared store "
                               "(state-machine replication, §3.3)",
                "policy_version": self.policy_version}


MESH = OrchestrationMesh()


# ----------------------------------------------------------------- RGD -----
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tid() -> str:
    return str(uuid.uuid4())[:12]


def classify_goal(goal: str) -> list[str]:
    """RGD intent fan-out. A goal may trigger several branches in parallel."""
    g = goal.lower()
    intents: list[str] = []
    import re as _re
    from_to = bool(_re.search(r"\bfrom\s+[\w' -]{2,40}\s+to\s+[\w' -]{2,40}",
                              g))
    if any(k in g for k in ("travel", "journey", "route", "trip", "commute",
                            "drive to", "go to", "get to", "passage")) \
            or (from_to and any(k in g for k in
                                ("get ", "go ", "travel", "need", "want",
                                 "going", "heading", "leave", "depart"))):
        intents.append("journey")
    if any(k in g for k in ("secure", "vulnerab", "cve", "patch", "scan",
                            "harden", "iot", "exposure", "exploit")):
        intents.append("security")
    if any(k in g for k in ("verify identity", "kyc", "onboard", "sanction",
                            "pep", "aml", "screen")):
        intents.append("identity")
    if any(k in g for k in ("is it true", "fact", "claim", "rumour", "rumor",
                            "really", "viral", "hoax", "verify that")):
        intents.append("claim")
    if not intents:
        intents.append("intel")  # generic OSINT sweep (A-05 path)
    return intents


def _parse_journey_params(goal: str) -> dict:
    ctx = voyager.parse_route_context(goal)
    dep = None
    now = datetime.now(timezone.utc)
    if ctx.get("departure_hint") == "tomorrow":
        dep = (now + timedelta(days=1)).replace(hour=8, minute=0,
                                                second=0, microsecond=0)
    elif ctx.get("departure_hint") == "tonight":
        dep = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if dep < now:
            dep += timedelta(days=1)
    elif ctx.get("departure_hint") == "today":
        dep = now + timedelta(hours=1)
    return {"origin": ctx.get("origin"), "destination": ctx.get("destination"),
            "departure_time": dep, "departure_hint": ctx.get("departure_hint")}


def _claim_entity(goal: str) -> str:
    from ..core import nlp_lite
    ents = nlp_lite.extract_entities(goal)
    return ents[0] if ents else goal[:60]


def decompose(goal: str, context: dict | None = None) -> list[dict]:
    """RGD: goal → TaskTreeJSON (flat list with parent edges; Strategy Map
    renders the nesting). Context from the Conversational Cortex pre-fills
    slots so RGD asks no question it doesn't materially need (§3.1)."""
    context = context or {}
    tasks: list[dict] = []

    def add(agent: str, function: str, title: str, parent: str | None = None,
            params: dict | None = None) -> str:
        tid = _tid()
        tasks.append({"task_id": tid, "parent_id": parent, "agent": agent,
                      "function": function, "title": title,
                      "params": params or {},
                      "position": len(tasks)})
        return tid

    intents = classify_goal(goal)

    if "journey" in intents:
        jp = _parse_journey_params(goal)
        origin = context.get("origin") or jp["origin"]
        destination = context.get("destination") or jp["destination"]
        dep = context.get("departure_time") or jp["departure_time"]
        root = add("VOYAGER", "assess_journey",
                   f"Assess journey risk: {origin or '?'} → {destination or '?'}",
                   params={"origin": origin, "destination": destination,
                           "departure_time": dep.isoformat()
                           if isinstance(dep, datetime) else dep,
                           "assumed_time": bool(jp["departure_hint"]) and not
                           context.get("departure_time")})
        add("VOYAGER", "compare_routes",
            "Compare route options with explicit trade-offs", parent=root,
            params={"origin": origin, "destination": destination,
                    "from_task": root})
        add("VOYAGER", "predict_route_risk",
            "Predict segment risk (hedged, §9)", parent=root,
            params={"origin": origin, "destination": destination,
                    "from_task": root})
        add("VOYAGER", "monitor_active_journey",
            "Enrol journey for live reassessment (§1.10)", parent=root,
            params={"origin": origin, "destination": destination,
                    "from_task": root})

    if "security" in intents:
        root = add("SENTINEL", "enumerate_assets",
                   "Enumerate asset inventory")
        scan = add("SENTINEL", "scan_cves",
                   "Scan assets against CVE feed", parent=root,
                   params={"assets_from": root})
        vpr = add("SENTINEL", "score_vpr",
                  "Score findings (VPR prioritization)", parent=scan,
                  params={"findings_from": scan})
        add("SENTINEL", "open_remediation_tickets",
            "Open remediation tickets for P1/P2 (human queue)", parent=vpr,
            params={"scored_from": vpr})
        add("SENTINEL", "request_patch",
            "Request patch execution (AUDITOR-gated)", parent=vpr,
            params={"scored_from": vpr})

    if "identity" in intents:
        entity = context.get("subject") or _claim_entity(goal)
        root = add("AUDITOR", "screen_entity",
                   f"L3 screening: sanctions/PEP lists — {entity}",
                   params={"entity": entity})
        add("AUDITOR", "mask_pii", "Zero-trust PII masking pass (A-06)",
            parent=root, params={"text": goal})
        if context.get("selfie_ref"):
            add("SENTINEL_FORENSICS", "analyze_media",
                "L2 forensic media authenticity check (A-04)", parent=root,
                params={"ref": context.get("selfie_ref")})

    if "claim" in intents:
        claim = context.get("claim") or goal
        entity = context.get("subject") or _claim_entity(claim)
        root = add("HUNTER", "footprint_scan",
                   f"Evidence footprint sweep — {entity}",
                   params={"entity": entity, "claim": claim})
        add("HUNTER", "actor_analysis",
            "Cross-source contradiction sweep (global §1.8)", parent=root,
            params={"entity": entity, "claim": claim})

    if "intel" in intents:
        entity = context.get("subject") or _claim_entity(goal)
        root = add("HUNTER", "footprint_scan",
                   f"OSINT footprint reconstruction — {entity}",
                   params={"entity": entity})
        add("HUNTER", "actor_analysis",
            "Entity signal clustering + contradiction flags", parent=root,
            params={"entity": entity})
        add("HUNTER", "external_audit",
            "External audits (Fusion Core providers)", parent=root,
            params={"entity": entity})

    # C-07 — AUDITOR runs as a non-blocking parallel overlay on EVERY tree
    subjects = [t.get("params", {}).get("entity") for t in tasks]
    add("AUDITOR", "compliance_overlay",
        "Compliance & ethics overlay (PII + screening, non-blocking)",
        params={"goal": goal,
                "subjects": [s for s in subjects if s]})
    return tasks


def dispatch_plan(tasks: list[dict]) -> dict:
    """A-02 DispatchPlan — branches per agent + the synthesis contract."""
    branches: dict[str, list[str]] = {}
    for t in tasks:
        branches.setdefault(t["agent"], []).append(t["task_id"])
    return {"branches": [{"agent": a, "tasks": ts} for a, ts in branches.items()],
            "overlay": "AUDITOR",
            "synthesis": "canonical spine (spec §6): ANSWER → CONFIDENCE → "
                         "KEY EVIDENCE → CONTRADICTIONS → INTERPRETATION → "
                         "RECOMMENDED ACTION → SOURCES"}


# ------------------------------------------------------------ executors ----
def _journey_req(params: dict, results: dict) -> JourneyRequest:
    dep = params.get("departure_time")
    if not dep and params.get("from_task"):
        parent = results.get(params["from_task"], {})
        dep = parent.get("departure_time_used")
    dt = None
    if dep:
        try:
            dt = datetime.fromisoformat(str(dep))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
    if dt is None:
        dt = datetime.now(timezone.utc) + timedelta(hours=1)
    return JourneyRequest(origin=params.get("origin") or "",
                          destination=params.get("destination") or "",
                          departure_time=dt,
                          priority=params.get("priority", "balanced"))


async def _exec(task: dict, store: EvidenceStore, results: dict) -> dict:
    """Task executor — dispatches ONLY through governed agent functions."""
    agent, fn, p = task["agent"], task["function"], task.get("params", {})

    if agent == "VOYAGER":
        if fn == "assess_journey":
            req = _journey_req(p, results)
            if not req.origin or not req.destination:
                return {"_status": DEGRADED,
                        "classified_error": "CLARIFICATION_NEEDED",
                        "note": ("origin/destination not present in goal or "
                                 "context — the Conversational Cortex asks "
                                 "for these before RGD (§3.1/§14-15).")}
            resp = await voyager.assess_journey(req)
            out = resp.model_dump(mode="json")
            out["departure_time_used"] = req.departure_time.isoformat() \
                if req.departure_time else None
            if p.get("assumed_time"):
                out["assumption_note"] = ("Departure time inferred from "
                                          "phrasing — disclosed, never hidden.")
            return out
        if fn == "compare_routes":
            opts = voyager.compare_routes(_journey_req(p, results))
            return {"options": [o.model_dump(mode="json") for o in opts]}
        if fn == "predict_route_risk":
            preds = voyager.predict_route_risk(_journey_req(p, results))
            return {"predictions": [x.model_dump(mode="json") for x in preds]}
        if fn == "monitor_active_journey":
            req = _journey_req(p, results)
            if not req.origin:
                return {"_status": DEGRADED,
                        "classified_error": "CLARIFICATION_NEEDED",
                        "note": "no route in scope to monitor"}
            return voyager.monitor_active_journey(
                store, origin=req.origin, destination=req.destination,
                departure_time=req.departure_time, priority=req.priority)

    if agent == "SENTINEL":
        if fn == "enumerate_assets":
            return sentinel.enumerate_assets()
        if fn == "scan_cves":
            assets = (results.get(p.get("assets_from", ""), {})
                      .get("assets")) if p.get("assets_from") else None
            return sentinel.scan_cves(assets)
        if fn == "score_vpr":
            findings = results.get(p.get("findings_from", ""), {}) \
                .get("findings", [])
            return {"scored": sentinel.score_vpr(findings)}
        if fn == "open_remediation_tickets":
            scored = results.get(p.get("scored_from", ""), {}).get("scored", [])
            return sentinel.open_remediation_tickets(store, scored)
        if fn == "request_patch":
            scored = results.get(p.get("scored_from", ""), {}).get("scored", [])
            top = scored[0] if scored else None
            if not top:
                return {"patch_state": "NOT_REQUESTED",
                        "note": "no findings in scope"}
            out = sentinel.request_patch(store, top["cve_id"], top["asset_id"])
            if out["patch_state"] == "AWAITING_HUMAN_APPROVAL":
                out["_status"] = AWAITING_HUMAN
                out["classified_error"] = "REQUIRE_HUMAN"
            return out

    if agent == "SENTINEL_FORENSICS":
        if fn == "analyze_media":
            return sentinel.analyze_media(p.get("ref"))
        if fn == "liveness_check":
            return sentinel.liveness_check(p.get("ref"))

    if agent == "HUNTER":
        if fn == "footprint_scan":
            return hunter.footprint_scan(store, p.get("entity", ""))
        if fn == "actor_analysis":
            out = hunter.actor_analysis(store, p.get("entity", ""))
            if p.get("claim"):
                from ..core.reasoning_engine import ReasoningEngine
                resp = await ReasoningEngine(store).run_full_pipeline(
                    p["claim"])
                out["fact_check"] = {
                    "verdict": resp.verdict.value,
                    "confidence": resp.confidence.value,
                    "check_id": resp.check_id,
                    "answer": resp.answer,
                    "sources_independent": resp.sources_independent,
                    "copy_chain_note": resp.copy_chain_note,
                    "review_route": resp.review_route}
            return out
        if fn == "external_audit":
            out = hunter.external_audit(p.get("entity", ""))
            out["_status"] = DEGRADED  # §20 honest gap, disclosed in report
            return out

    if agent == "AUDITOR":
        if fn == "mask_pii":
            return auditor.mask_pii(p.get("text", ""))
        if fn == "screen_entity":
            return await auditor.screen_entity(store, p.get("entity", ""))
        if fn == "compliance_overlay":
            return auditor.compliance_overlay(
                store, tree_goal=p.get("goal", ""),
                subjects=p.get("subjects", []))
        if fn == "authorize_action":
            return auditor.authorize_action(
                store, actor="PATHFINDER", action=p.get("action", ""),
                detail=p.get("detail", ""))
        if fn == "validate_custom_agent":
            return auditor.validate_custom_agent(
                store, p.get("name", ""), p.get("functions", []))

    return {"_status": FAILED,
            "classified_error": "TASK_EXECUTION_ERROR",
            "note": f"no executor for {agent}.{fn}"}


# ------------------------------------------------------------ execution ----
async def _run_levels(tree_id: str, tasks: list[dict], store: EvidenceStore
                      ) -> dict[str, dict]:
    """Execute tasks level-by-level; siblings in a level run in parallel
    (swarm branches, v2 C-01). Every transition is persisted (§3.3)."""
    by_id = {t["task_id"]: t for t in tasks}
    depth: dict[str, int] = {}

    def d(tid: str) -> int:
        if tid in depth:
            return depth[tid]
        t = by_id[tid]
        depth[tid] = 0 if not t.get("parent_id") else d(t["parent_id"]) + 1
        return depth[tid]

    for t in tasks:
        d(t["task_id"])
    results: dict[str, dict] = {}
    for level in sorted(set(depth.values())):
        batch = [t for t in tasks if depth[t["task_id"]] == level
                 and t.get("_status_done") is not True]
        async def one(t):
            t["status"] = RUNNING
            t["started_at"] = _now()
            store.upsert_task({**t, "tree_id": tree_id, "result": {}})
            try:
                # A-14 governance gate — outside allowlist = BLOCKED task
                registry.check_dispatch(store, t["agent"], t["function"])
            except registry.GovernanceError as ge:
                t["status"] = BLOCKED
                t["classified_error"] = ge.classification
                t["ended_at"] = _now()
                store.upsert_task({**t, "tree_id": tree_id,
                                   "result": {"note": str(ge)}})
                store.audit(actor=t["agent"], action=t["function"],
                            decision="DENY", detail=str(ge),
                            policy_version=registry.POLICY_VERSION)
                results[t["task_id"]] = {"note": str(ge)}
                return
            try:
                out = await _exec(t, store, results)
            except Exception as exc:  # §20 classified failure, never silent
                t["status"] = FAILED
                t["classified_error"] = "TASK_EXECUTION_ERROR"
                t["ended_at"] = _now()
                store.upsert_task({**t, "tree_id": tree_id,
                                   "result": {"note": str(exc)[:300]}})
                log.exception("task %s failed", t["task_id"])
                results[t["task_id"]] = {"note": str(exc)[:300]}
                return
            status = out.pop("_status", COMPLETE)
            classified = out.get("classified_error")
            t["status"] = DEGRADED if status == DEGRADED else (
                AWAITING_HUMAN if status == AWAITING_HUMAN else COMPLETE)
            t["classified_error"] = classified
            t["ended_at"] = _now()
            store.upsert_task({**t, "tree_id": tree_id, "result": out})
            results[t["task_id"]] = out
        await asyncio.gather(*(one(t) for t in batch))
    return results


def _conf_rank(c: str) -> int:
    order = ["UNDETERMINED", "VERY_LOW", "LOW", "MODERATE", "HIGH",
             "VERY_HIGH"]
    try:
        return order.index(c)
    except ValueError:
        return 0


def synthesize(goal: str, tasks: list[dict], results: dict[str, dict]
               ) -> dict:
    """A-02 result synthesis — UnifiedReport on the canonical spine (§6).
    The five §28 questions must be answerable from this payload alone."""
    confs: list[str] = []
    key_evidence: list[dict] = []
    contradictions: list[dict] = []
    notices: list[str] = []
    degraded: list[dict] = []
    awaiting_human = False
    answers: list[str] = []
    actions: list[str] = []

    for t in tasks:
        out = results.get(t["task_id"], {})
        st = t.get("status")
        if st in (DEGRADED, FAILED, BLOCKED):
            degraded.append({"agent": t["agent"], "function": t["function"],
                             "state": st,
                             "classified_error": t.get("classified_error"),
                             "note": out.get("note", "")})
        if st == AWAITING_HUMAN:
            awaiting_human = True
            notices.append(out.get("note", "Awaiting human approval."))

        # ---- VOYAGER evidence
        if t["agent"] == "VOYAGER" and t["function"] == "assess_journey" \
                and out.get("answer"):
            answers.append(out["answer"])
            confs.append(out.get("confidence", "MODERATE"))
            actions.append(out.get("recommended_action", ""))
            for seg in (out.get("risk_timeline") or [])[:3]:
                key_evidence.append({
                    "trust_label": "EVIDENCE", "agent": "VOYAGER",
                    "text": f"{seg['time']} {seg['segment']}: {seg['risk']} — "
                            f"{seg['why'][:140]}"})
        if t["agent"] == "VOYAGER" and t["function"] == "monitor_active_journey" \
                and out.get("watch_id"):
            notices.append(out.get("note", ""))
        # ---- SENTINEL evidence
        if t["function"] == "score_vpr" and out.get("scored"):
            top = out["scored"][:3]
            p1 = sum(1 for r in out["scored"] if r["priority"] == "P1")
            answers.append(
                f"Vulnerability scan: {len(out['scored'])} finding(s), "
                f"{p1} at P1 priority.")
            confs.append("MODERATE")  # fixture-backed demo feed, disclosed
            actions.append("Approve P1/P2 remediation tickets in the review "
                           "queue; patching awaits human sign-off (§27).")
            for r in top:
                key_evidence.append({
                    "trust_label": r.get("trust_label", "INFERENCE"),
                    "agent": "SENTINEL",
                    "text": f"{r['priority']} {r['cve_id']} on {r['host']} "
                            f"(VPR {r['vpr']}): {r['summary'][:120]}"})
        if t["function"] == "open_remediation_tickets" and out.get("opened"):
            notices.append(out.get("note", ""))
        # ---- HUNTER evidence
        if t["function"] == "footprint_scan":
            if out.get("signals_indexed") is not None:
                key_evidence.append({
                    "trust_label": "EVIDENCE", "agent": "HUNTER",
                    "text": f"Footprint for '{out.get('entity')}': "
                            f"{out['signals_indexed']} indexed signal(s) "
                            f"across {out['independent_sources']} independent "
                            f"source group(s)."})
                if out.get("coverage_gaps"):
                    notices.append(out.get("gap_note", ""))
        if t["function"] == "actor_analysis":
            for c in out.get("contradictions", []):
                contradictions.append({
                    "trust_label": "EVIDENCE", "agent": "HUNTER",
                    "description": c["description"], "severity": c["severity"]})
            fc = out.get("fact_check")
            if fc:
                answers.append(f"Claim assessment: {fc['verdict']} — "
                               f"{fc['answer']}")
                confs.append(fc["confidence"])
                if fc.get("copy_chain_note"):
                    notices.append(fc["copy_chain_note"])
                actions.append("See the evidence graph for the full "
                               "reasoning trace before acting on this verdict.")
        # ---- AUDITOR overlay
        if t["function"] == "compliance_overlay":
            notices.extend(out.get("notices", []))
            for s in out.get("screenings", []):
                if s["state"] == "MATCH_FOUND":
                    contradictions.append({
                        "trust_label": "EVIDENCE", "agent": "AUDITOR",
                        "description": f"Screening hit for '{s['subject']}' "
                                       f"({s['match_count']} list match(es)) "
                                       f"— signal for review, not a verdict.",
                        "severity": "MODERATE"})
        if t["function"] == "screen_entity" and out.get("screening_state"):
            key_evidence.append({
                "trust_label": "EVIDENCE", "agent": "AUDITOR",
                "text": f"Screening '{out.get('entity')}': "
                        f"{out['screening_state'].replace('_', ' ')}."})

    if not answers:
        answers.append("Goal decomposed but produced no assessable result — "
                       "see task states for classified reasons (§20).")
    if not confs:
        confs.append("UNDETERMINED")

    overall = min(confs, key=_conf_rank)  # honest worst-link confidence
    tree_status = (AWAITING_HUMAN if awaiting_human else
                   DEGRADED if degraded else "COMPLETE")

    return {
        # ---- canonical spine (spec §6) ----
        "answer": " ".join(a for a in answers if a),
        "confidence": overall,
        "key_evidence": key_evidence,
        "contradictions": contradictions,
        "interpretation": ("INFERENCE: this report synthesizes governed agent "
                           "outputs; agent confidence is combined "
                           "conservatively (weakest link). Contradictions and "
                           "degraded sources are disclosed above, never "
                           "silently dropped (§20/§26)."),
        "recommended_action": (" ".join(a for a in actions if a)
                               or "No action required beyond review."),
        "sources": {"agents_consulted": sorted({t["agent"] for t in tasks}),
                    "policy_version": registry.POLICY_VERSION},
        # ---- five-question guarantee (§28) ----
        "what_would_change_conclusion":
            "New evidence on the corridor/entity (the §1.10 loop re-tests "
            "automatically), approval of pending human-gated actions, or "
            "fresh scans.",
        "trust_labels": sorted({e.get("trust_label", "INFERENCE")
                                for e in key_evidence}),
        # ---- swarm visibility (A-15) ----
        "compliance_notices": [n for n in notices if n],
        "degraded": degraded,
        "tree_status": tree_status,
    }


async def run_goal(goal: str, store: EvidenceStore,
                   context: dict | None = None) -> dict:
    """One-shot free-text goal → executable task tree → UnifiedReport."""
    tree_id = str(uuid.uuid4())[:12]
    peer = MESH.primary_id()
    tasks = decompose(goal, context)
    store.create_tree(tree_id, goal, dispatch_plan(tasks), peer)
    for t in tasks:
        t["status"] = PENDING
        store.upsert_task({**t, "tree_id": tree_id})
    results = await _run_levels(tree_id, tasks, store)
    report = synthesize(goal, tasks, results)
    store.update_tree(tree_id, status=report["tree_status"], report=report)
    report["tree_id"] = tree_id
    report["goal"] = goal
    report["peer_id"] = peer
    return report


async def resume_tree(tree_id: str, store: EvidenceStore) -> dict:
    """§3.3 — a surviving peer resumes an interrupted tree from persisted
    task state (failover path; re-runs only non-final tasks)."""
    tree = store.get_tree(tree_id)
    if not tree:
        return {"classified_error": "TREE_NOT_FOUND", "tree_id": tree_id}
    new_peer = MESH.primary["peer_id"]
    store.update_tree(tree_id, peer_id=new_peer)
    tasks = store.tasks_for_tree(tree_id)
    for t in tasks:
        t["params"] = {}  # persisted params aren't stored; re-derive below
        t["_status_done"] = t["status"] in (COMPLETE, DEGRADED, BLOCKED,
                                            AWAITING_HUMAN)
    # re-derive params by re-decomposing the SAME goal (deterministic order),
    # then remap cross-task references (uuid ids differ after reboot) from the
    # fresh ids back onto the persisted task ids so results flow correctly.
    fresh = decompose(tree["goal"])
    id_map = {new["task_id"]: old["task_id"]
              for old, new in zip(tasks, fresh)}
    for old, new in zip(tasks, fresh):
        params = dict(new.get("params", {}))
        for k, v in list(params.items()):
            if isinstance(v, str) and v in id_map:
                params[k] = id_map[v]
        old["params"] = params
    results = await _run_levels(tree_id, tasks, store)
    report = synthesize(tree["goal"], tasks, results)
    store.update_tree(tree_id, status=report["tree_status"], report=report)
    report["tree_id"] = tree_id
    report["resumed_by"] = new_peer
    report["failover_note"] = (f"Resumed by peer '{new_peer}' from persisted "
                               f"task state (§3.3 state-machine replication).")
    return report
