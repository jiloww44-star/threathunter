"""Agent registry + function-level governance — spec A-14, §5.2.

A-14: per-agent `api_functions` allowlists; dispatch of any function outside
an agent's allowlist is blocked architecturally (privilege-escalation
prevention), and the block is recorded on the AUDITOR trail (§20: never
silently skipped).

§5.2: custom agents (A-13 SDK) are admitted only through AUDITOR validation
and run in SHADOW mode — read-only — until promoted by a human.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class GovernanceError(Exception):
    """Raised when dispatch violates function-level governance (A-14)."""
    def __init__(self, message: str, classification: str = "ACTION_DENIED"):
        super().__init__(message)
        self.classification = classification


@dataclass
class AgentSpec:
    agent_id: str
    name: str
    role: str            # Defense | Intelligence | Compliance | Journey | ...
    description: str
    api_functions: list[str]          # A-14 allowlist
    read_only_functions: list[str] = field(default_factory=list)
    native: bool = True
    status: str = "ACTIVE"            # ACTIVE | SHADOW | REJECTED

    def allows(self, function: str) -> bool:
        return function in self.api_functions


# Native roster — spec §2 architecture diagram. Every function an agent may
# ever run is enumerated here; PATHFINDER dispatch checks this map (A-14).
NATIVE_AGENTS: dict[str, AgentSpec] = {
    "VOYAGER": AgentSpec(
        agent_id="VOYAGER", name="VOYAGER", role="Journey & Situational",
        description=("Guardian-of-Passage: journey risk assessment, route "
                     "comparison, hedged prediction, live journey monitoring "
                     "(spec §5.1; v1 §5–9 restored)."),
        api_functions=["assess_journey", "build_risk_timeline",
                       "compare_routes", "predict_route_risk",
                       "monitor_active_journey", "parse_route_context"],
        read_only_functions=["assess_journey", "build_risk_timeline",
                             "compare_routes", "predict_route_risk",
                             "parse_route_context"]),
    "SENTINEL": AgentSpec(
        agent_id="SENTINEL", name="SENTINEL", role="Defense",
        description=("CVE scanning, VPR-style prioritization, remediation "
                     "ticketing (A-03). Patching itself is NEVER autonomous — "
                     "AUDITOR gates apply_patch as REQUIRE_HUMAN (§27)."),
        api_functions=["enumerate_assets", "scan_cves", "score_vpr",
                       "open_remediation_tickets", "request_patch"],
        read_only_functions=["enumerate_assets", "scan_cves", "score_vpr"]),
    "SENTINEL_FORENSICS": AgentSpec(
        agent_id="SENTINEL_FORENSICS", name="SENTINEL Forensic Sub-Agent",
        role="Forensics",
        description=("Media authenticity: liveness, deepfake indicators, "
                     "manipulation audit (A-04). Demo provider is heuristic; "
                     "absent a configured provider it degrades to UNVERIFIED "
                     "honestly (§20)."),
        api_functions=["analyze_media", "liveness_check"],
        read_only_functions=["analyze_media", "liveness_check"]),
    "HUNTER": AgentSpec(
        agent_id="HUNTER", name="HUNTER", role="Intelligence",
        description=("OSINT footprint reconstruction over the evidence graph; "
                     "live dorking/carrier/breach lookups degrade to "
                     "SOURCE_UNAVAILABLE markers in the demo profile (A-05)."),
        api_functions=["footprint_scan", "actor_analysis", "external_audit"],
        read_only_functions=["footprint_scan", "actor_analysis",
                             "external_audit"]),
    "AUDITOR": AgentSpec(
        agent_id="AUDITOR", name="AUDITOR", role="Compliance & Ethics",
        description=("Zero-trust PII masking, AML/PEP/sanctions screening, "
                     "ethical gating (authorize_action), immutable audit "
                     "trail (A-06). Runs as non-blocking parallel overlay on "
                     "every tree (v2 C-07)."),
        api_functions=["mask_pii", "screen_entity", "authorize_action",
                       "compliance_overlay", "validate_custom_agent"],
        read_only_functions=["mask_pii", "screen_entity",
                             "validate_custom_agent"]),
}

# §5.2 — sovereign policy version applies to native and SDK agents alike.
POLICY_VERSION = "sovereign-policy/3.0.0"


def roster(store=None) -> list[dict]:
    """Full agent roster (native + custom) for the Ops Node UI."""
    out = [{
        "agent_id": s.agent_id, "name": s.name, "role": s.role,
        "description": s.description, "api_functions": s.api_functions,
        "native": s.native, "status": s.status,
        "policy_version": POLICY_VERSION,
    } for s in NATIVE_AGENTS.values()]
    if store is not None:
        for c in store.list_custom_agents():
            out.append({
                "agent_id": c["agent_id"], "name": c["name"],
                "role": "Custom (SDK)",
                "description": ("Custom agent admitted via SDK — SHADOW mode "
                                "until human promotion (§5.2)."),
                "api_functions": c["functions"],
                "native": False, "status": c["status"],
                "policy_version": POLICY_VERSION,
                "shadow_tree_count": c.get("shadow_tree_count", 0),
                "drift_notes": c.get("drift_notes"),
            })
    return out


def check_dispatch(store, agent_id: str, function: str) -> None:
    """A-14 gate: raise GovernanceError unless the call is inside the agent's
    function allowlist. §20: denial is a classified, auditable event, never a
    silent skip."""
    spec = NATIVE_AGENTS.get(agent_id)
    if spec is not None:
        if spec.allows(function):
            return
        raise GovernanceError(
            f"A-14 governance: {agent_id} is not allowed to run '{function}' "
            f"(allowlist: {', '.join(spec.api_functions)})")
    # custom agent path (§5.2)
    c = store.get_custom_agent(agent_id) if store is not None else None
    if c is None:
        raise GovernanceError(f"Unknown agent '{agent_id}'",
                              classification="ACTION_DENIED")
    if c["status"] == "REJECTED":
        raise GovernanceError(
            f"Custom agent '{agent_id}' is REJECTED — see AUDITOR notes")
    if function not in c["functions"]:
        raise GovernanceError(
            f"A-14 governance: custom agent '{agent_id}' is not allowed to "
            f"run '{function}' (declared: {', '.join(c['functions'])})")
    if c["status"] == "SHADOW":
        raise GovernanceError(
            f"Custom agent '{agent_id}' is in SHADOW mode — read-only "
            f"observation only; human promotion required for execution",
            classification="REQUIRE_HUMAN")
