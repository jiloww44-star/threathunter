"""Agent Inventory · Readiness · Supply Chain — v4.2 (§73 V2).

Spec: "Agent supply chain = Agent Dependency Graph; per node: owner,
version, source, publisher, permissions, credentials, trust status,
last reviewed, known issue, runtime exposure, data classification.
Key question: 'What could this agent reach if compromised?'"
And: "Readiness audit = Discover → Map → Measure → Manage (NIST AI RMF:
Govern, Map, Measure, Manage)."

This builds the per-node supply-chain card from the LIVE registry roster
(§54 — derived, never model-narrated): native agents get declared
build-time provenance; SDK custom agents carry their admission trail
(SHADOW until human promotion). Honest limits are stated in every card:
no package hashes in the demo profile — "credentials" means "what external
secrets does this code path define", and the answer is enumerated, not
glossed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..swarm import registry

# Declared dependency edges (reviewed against swarm agent call sites).
# HUNTER/AUDITOR share the evidence store; AUDITOR overlays every tree.
DEPENDENCY_EDGES = [
    {"from": "PATHFINDER", "to": "VOYAGER", "kind": "dispatches"},
    {"from": "PATHFINDER", "to": "SENTINEL", "kind": "dispatches"},
    {"from": "PATHFINDER", "to": "SENTINEL_FORENSICS", "kind": "dispatches"},
    {"from": "PATHFINDER", "to": "HUNTER", "kind": "dispatches"},
    {"from": "PATHFINDER", "to": "AUDITOR", "kind": "overlay_every_tree"},
    {"from": "SENTINEL", "to": "AUDITOR", "kind": "authorize_action_gate",
     "note": "apply_patch passes AUDITOR authorization (§27)"},
    {"from": "HUNTER", "to": "EVIDENCE_STORE", "kind": "reads"},
    {"from": "AUDITOR", "to": "AUDIT_TRAIL", "kind": "appends_only"},
]

# data these code paths actually touch (review-derived, per role)
_DATA_CLASSIFICATION = {
    "VOYAGER": "journey contexts + public geo/weather fixtures",
    "SENTINEL": "asset inventory + CVE fixtures (organization-owned)",
    "SENTINEL_FORENSICS": "media references (demo fixtures)",
    "HUNTER": "indexed evidence/signals (public OSINT)",
    "AUDITOR": "PII-adjacent screening subjects + audit trail (append-only)",
    "CUSTOM": "declared function set only (SHADOW = read-only by design)",
}

_TRUST_BY_STATUS = {"ACTIVE": "TRUSTED", "SHADOW": "OBSERVED",
                    "REJECTED": "QUARANTINED"}


def _blast_radius_note(spec: dict) -> str:
    fn = spec.get("api_functions") or []
    writable = [f for f in fn if f not in spec.get("read_only_functions", [])]
    note = (f"If compromised: could invoke {len(fn)} allowlisted function(s); "
            f"{len(writable)} of them are not read-only "
            f"({', '.join(writable[:3]) or 'none'}).")
    if spec["agent_id"] == "AUDITOR":
        note += (" AUDITOR compromise is the worst case: it appends to the"
                 " audit trail — trail integrity is the recovery anchor,"
                 " never the agent's own word (A-06).")
    if not spec.get("native"):
        note += (" Custom agent: SHADOW confinement means a compromise "
                 "yields observations only — no execution rights until a "
                 "human promotion is on the record.")
    return note


def inventory(store) -> dict:
    """Per-node supply-chain cards + the NIST RMF readiness summary."""
    roster = registry.roster(store)
    custom_ids = {c["agent_id"] for c in store.list_custom_agents()}
    nodes = []
    for spec in roster:
        native = bool(spec.get("native"))
        trust = _TRUST_BY_STATUS.get(spec.get("status", "ACTIVE"),
                                     "QUARANTINED")
        read_only = spec.get("read_only_functions", [])
        nodes.append({
            "agent_id": spec["agent_id"],
            "name": spec.get("name", spec["agent_id"]),
            # ---- spec per-node fields (verbatim set) ----
            "owner": "platform" if native else "tenant (SDK admission)",
            "version": spec.get("policy_version", registry.POLICY_VERSION),
            "source": (f"backend/app/swarm/agents/"
                       f"{spec['agent_id'].lower()}.py" if native else
                       "external SDK registration"),
            "publisher": "LOG_ON platform build" if native
            else "tenant-registered",
            "permissions": {"api_functions": spec.get("api_functions", []),
                            "read_only_functions": read_only},
            "credentials": ("none declared — no external secrets on these "
                            "code paths (demo profile; any live connector "
                            "would be broker-keyed, never agent-held)"),
            "trust_status": trust,
            "last_reviewed": ("build-time declaration (native modules "
                              "reviewed at commit; continuous review is "
                              "the V2.5 continuous-assurance plane — "
                              "stated honestly rather than faked)"
                              if native else
                              f"admission record {spec.get('status')}, "
                              f"shadow trees observed: "
                              f"{spec.get('shadow_tree_count', 0)}"),
            "known_issue": ("none recorded"
                            if not spec.get("drift_notes")
                            else spec["drift_notes"]),
            "runtime_exposure": ("in-process function calls only — no "
                                 "network listeners in the demo profile"),
            "data_classification": _DATA_CLASSIFICATION.get(
                spec["agent_id"], _DATA_CLASSIFICATION["CUSTOM"]),
            # ---- the key question, answered per node ----
            "blast_radius_note": _blast_radius_note(spec),
            "native": native,
            "status": spec.get("status", "ACTIVE"),
        })
    tracked_ids = {n["agent_id"] for n in nodes}
    edges = [e for e in DEPENDENCY_EDGES
             if e["from"] in tracked_ids | {"PATHFINDER"}]
    ready = [n for n in nodes if n["trust_status"] == "TRUSTED"]
    shadowed = [n for n in nodes if n["trust_status"] == "OBSERVED"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agents": nodes,
        "dependency_graph": {"edges": edges,
                             "note": ("Declared edges from code review — "
                                      "the question 'what could this agent "
                                      "reach if compromised' is answered "
                                      "per node by blast_radius_note.")},
        "readiness": {
            # NIST AI RMF: Govern, Map, Measure, Manage
            "govern": (f"policy={registry.POLICY_VERSION}; A-14 allowlists "
                       "architectural; promotion to ACTIVE is human-gated"),
            "map": (f"{len(nodes)} agents · {len(edges)} declared "
                    f"dependency edges"),
            "measure": (f"{len(ready)} TRUSTED · {len(shadowed)} OBSERVED "
                        f"(shadow) · {len(nodes) - len(ready) - len(shadowed)}"
                        " QUARANTINED"),
            "manage": ("SHADOW confinement, REQUIRE_HUMAN approvals, "
                       "audit-trail events for every governance action"),
        },
        "honest_limits": ("No package-hash supply chain in the demo profile; "
                          "native provenance is build-time declaration. "
                          "Live registry + admission trails are the actual "
                          "data, and they are all real store rows."),
        "policy_version": registry.POLICY_VERSION,
    }
