"""Investigation Core — v4.0 §2: Investigation is the primary backend object.

Every meaningful work unit (fact check, journey plan, OSINT sweep, KYC case,
agent audit, incident review) binds to an Investigation carrying an
**authorization object** (§63): purpose, subject, authority, scope,
expiration, allowed sources. The policy gate here is deterministic (§54):
expiry and source allowlists are enforced in code — never by model judgment.

§76 INVARIANT (load-bearing): no consequential action without authorization.
Expired or closed investigations refuse new work with a classified §20
error; they never silently degrade to an ungoverned run.

Events (§26) are written to the audit trail — the event store already
exists; no shadow tables.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from . import policy_engine
from .errors import PipelineError

AUTHORITIES = ("organization_owned", "client_authorized", "public_research",
               "unchecked")  # §63; 'unchecked' retains the no-auth demo path
SUBJECT_TYPES = ("person", "organization", "domain", "ip", "url", "location",
                 "claim", "agent")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# §35 — BRANCH → connector families an investigation may allow. Classified
# honestly so 'allowed_sources: ["cve_feed"]' admits security sweeps but not
# identity screening (source-sensitive OSINT policy, §64).
BRANCH_SOURCES: dict[str, tuple[str, ...]] = {
    "journey": ("routes", "weather", "traffic", "incidents", "osm"),
    "security": ("asset_inventory", "cve_feed", "vpr_model"),
    "identity": ("sanctions_feed", "pep_list", "kyc_documents", "dns",
                 "carrier_lookup"),
    "identity_intel": ("osint_databases", "rdap", "carrier_lookup",
                       "breach_sources"),
    "claim": ("news_feed", "factcheck_reviews", "archive"),
    "intel": ("osint_databases", "rdap", "news_feed"),
}


def create(store, *, objective: str, subject_type: str, subject: str,
           purpose: str, authority: str, scope: str,
           allowed_sources: list[str] | None, expires_days: int,
           user_id: str) -> dict:
    if authority not in AUTHORITIES:
        raise PipelineError("INVALID_CONSENT", status=400,
                            detail=f"authority must be one of {AUTHORITIES}")
    if subject_type not in SUBJECT_TYPES:
        raise PipelineError("INVALID_CONSENT", status=400,
                            detail=f"subject_type must be one of {SUBJECT_TYPES}")
    inv_id = str(uuid.uuid4())[:12]
    expires = (datetime.now(timezone.utc)
               + timedelta(days=max(1, min(expires_days, 90)))).isoformat()
    sources = sorted(set(allowed_sources or []))
    store.inv_create(inv_id, objective, subject_type, subject, purpose,
                     authority, scope, json.dumps(sources), expires,
                     "OPEN", user_id)
    _event(store, "InvestigationCreated", user_id,
           f"'{objective[:60]}' [{authority}] scope={scope!r} "
           f"sources={sources or 'open-public-tier'}")
    return get(store, inv_id)


def get(store, inv_id: str) -> dict:
    row = store.inv_get(inv_id)
    if not row:
        raise PipelineError("TREE_NOT_FOUND", status=404,
                            detail=f"investigation {inv_id} not found")
    return row


def _event(store, name: str, actor: str, detail: str) -> None:
    """§26 events live on the append-only audit trail (single event store)."""
    store.audit(actor=actor, action=f"event:{name}", decision="ALLOW",
                detail=detail, policy_version="intel-core/4.0.0")


def authorize_run(store, inv_id: str, branches: list[str],
                  user_id: str) -> dict:
    """§35/§76 gate — called by PATHFINDER BEFORE a tree is created.

    v4.2: decision-making is delegated to the policy engine (§34:
    deterministic = permissions, policy, audit). Behavior parity is
    preserved exactly: expired, closed, or out-of-scope runs raise the
    same classified PipelineErrors and emit the same §26 events.
    Returns the investigation row on success.
    """
    row = store.inv_get(inv_id)
    if not row:
        raise PipelineError("TREE_NOT_FOUND", status=404,
                            detail=f"investigation {inv_id} not found")
    # store.inv_get() normalises the column into `allowed_sources`; accept
    # either shape so the gate never silently falls open.
    allowed = row.get("allowed_sources")
    if allowed is None:
        allowed = json.loads(row.get("allowed_sources_json") or "[]")
    needed: set[str] = set()
    for b in branches:
        needed |= set(BRANCH_SOURCES.get(b, ()))

    decision = policy_engine.evaluate(
        store, action="investigation_run", subject=inv_id,
        investigation_row=row, requested_sources=sorted(needed))

    if decision.decision == policy_engine.DENY:
        outcomes = {c["check"]: c["outcome"] for c in decision.checks}
        if outcomes.get("R-INV-LIFECYCLE") == "FAIL":
            raise PipelineError("ACTION_DENIED", status=403,
                                detail=(f"investigation {inv_id} is "
                                        f"{row['status']} — §76: no action "
                                        "without living authorization"))
        if outcomes.get("R-INV-EXPIRY") == "FAIL":
            _event(store, "AuthorizationExpired", user_id,
                   f"investigation {inv_id} expired {row['expires_at']}")
            raise PipelineError("ACTION_DENIED", status=403,
                                detail=(f"authorization expired {row['expires_at']}"
                                        " — §76: renew the investigation or open "
                                        "a new one"))
        if outcomes.get("R-DENY-SOURCES") == "FAIL":
            denied = sorted(set(needed) - set(allowed))
            _event(store, "AuthorizationDenied", user_id,
                   f"investigation {inv_id}: sources not allowed {denied}")
            raise PipelineError(
                "ACTION_DENIED", status=403,
                detail=(f"investigation scope does not authorize source "
                        f"families {denied} (allowed: {allowed}); §35: LLM "
                        "proposes, policy disposes"))
        # unreachable given the rule set — fail closed regardless
        raise PipelineError("ACTION_DENIED", status=403,
                            detail="policy decision DENY (§76)")
    policy_engine.record(store, decision, actor=user_id)
    return row


def link(store, inv_id: str, kind: str, ref_id: str, actor: str) -> dict:
    get(store, inv_id)  # existence check
    lid = str(uuid.uuid4())[:12]
    store.inv_link(lid, inv_id, kind, ref_id)
    _event(store, "EvidenceLinked", actor,
           f"{kind}:{ref_id[:12]} → investigation {inv_id}")
    return {"link_id": lid, "investigation_id": inv_id, "kind": kind,
            "ref_id": ref_id}


def close(store, inv_id: str, actor: str, reason: str = "") -> dict:
    row = get(store, inv_id)
    if row["status"] == "CLOSED":
        return row
    store.inv_set_status(inv_id, "CLOSED")
    _event(store, "InvestigationClosed", actor,
           f"{inv_id} closed{': ' + reason if reason else ''}")
    return get(store, inv_id)


# ------------------------------------------------ V1.5 investigation graph --
def graph(store, inv_id: str) -> dict:
    """§73 V1.5 investigation graph — the evidence chain (§5) as nodes/edges,
    in the same GraphData shape as Part 12 (EvidenceGraph renders it as-is):
      Investigation —LINKED_TO→ Tree —HAS_TASK→ Task
      Investigation —LINKED_TO→ Evidence | Watch | Finding | VerificationCase
    Derived live from investigation_links + the store: nothing is invented,
    an empty chain renders empty (§20)."""
    row = get(store, inv_id)  # 404s for unknown ids
    inv_node = f"inv-{inv_id}"
    nodes = [{"id": inv_node, "type": "Investigation",
              "label": row["objective"][:48],
              "provenance": {"authority": row["authority"],
                             "subject": f"{row['subject_type']}:{row['subject']}",
                             "status": row["status"],
                             "expires_at": row["expires_at"],
                             "allowed_sources": row["allowed_sources"]
                             or ["open public tier"]}}]
    edges: list[dict] = []
    seen: set[str] = {inv_node}

    def add(node_id: str, ntype: str, label: str, prov: dict,
            parent: str = inv_node, edge_type: str = "LINKED_TO"):
        if node_id not in seen:
            nodes.append({"id": node_id, "type": ntype, "label": label,
                          "provenance": prov})
            seen.add(node_id)
        edges.append({"id": f"e-{parent}-{node_id}", "source": parent,
                      "target": node_id, "type": edge_type})

    for l in row["links"]:
        kind, ref = l["kind"], l["ref_id"]
        if kind == "ops_tree":
            tree = store.get_tree(ref)
            if not tree:
                add(f"tree-{ref}", "Tree", f"tree {ref[:8]} (removed)",
                    {"link_created_at": l["created_at"],
                     "note": "linked tree no longer in store — link retained"
                             " for audit provenance (§26)"})
                continue
            tid = f"tree-{ref}"
            add(tid, "Tree", tree["goal"][:48],
                {"status": tree["status"], "peer_id": tree.get("peer_id"),
                 "link_created_at": l["created_at"]})
            for t in tree.get("tasks", [])[:12]:
                add(f"task-{ref}-{t['task_id']}", "Task",
                    f"{t['agent']}·{t['function']}",
                    {"status": t["status"], "agent": t["agent"],
                     "function": t["function"],
                     "classified_error": t.get("classified_error")},
                    parent=tid, edge_type="HAS_TASK")
        elif kind == "evidence":
            ev = store.get_evidence(ref)
            add(f"ev-{ref}", "Evidence",
                (ev or {}).get("title") or f"evidence {ref[:8]}",
                {"source_id": (ev or {}).get("source_id"),
                 "authority": (ev or {}).get("authority"),
                 "url": (ev or {}).get("url"),
                 "link_created_at": l["created_at"],
                 "present_in_store": bool(ev)})
        elif kind == "watch":
            add(f"watch-{ref}", "Watch", f"watch {ref[:8]}",
                {"link_created_at": l["created_at"]})
        else:
            add(f"{kind}-{ref}", kind.capitalize().replace("_", ""),
                f"{kind} {ref[:8]}",
                {"link_created_at": l["created_at"]})

    return {"nodes": nodes, "edges": edges,
            "note": ("§5 evidence chain for this investigation. Deletion of "
                     "linked artifacts never removes the audit link — "
                     "provenance outlives content (§26).")}
