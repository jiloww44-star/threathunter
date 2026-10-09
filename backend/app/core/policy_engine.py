"""Policy Engine — v4.2 (§73 V2) deterministic decision point.

§34: "Deterministic systems = permissions, policy, scoring constraints,
schema validation, timestamps, audit, execution controls."
§35: "LLM must not invent/escalate tool permissions: LLM proposes 'query
Shodan' → policy engine: 'authorized for this subject?' → YES execute /
NO reject-request-authorization."

Every authorization question in the platform funnels through
`evaluate()` — ONE function, NO model judgment (§54). Decisions:

    PERMIT          all checks green
    DENY            a hard rule failed (fail-closed default)
    REQUIRE_HUMAN   §27/R-05 external-effect action — an approval must
                    exist before execution (approval engine, core/approvals)

Each decision returns its full check ledger (check/outcome/detail) and is
written to the audit trail by callers via `record()` — no silent policy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..swarm import registry

POLICY_ENGINE_VERSION = "policy-engine/4.2.0"

PERMIT, DENY, REQUIRE_HUMAN = "PERMIT", "DENY", "REQUIRE_HUMAN"

# action classes — anything external-effect is REQUIRE_HUMAN (§27/R-05)
EXTERNAL_EFFECT_CLASSES = ("patch_apply", "promote_custom_agent",
                           "execute_dork_set", "webhook_deliver",
                           "active_probe", "external_post")


@dataclass
class PolicyDecision:
    decision: str
    action: str
    subject: str
    checks: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    policy_version: str = POLICY_ENGINE_VERSION
    dispatched_policy: str = registry.POLICY_VERSION
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {"decision": self.decision, "action": self.action,
                "subject": self.subject, "checks": self.checks,
                "reasons": self.reasons,
                "policy_version": self.policy_version,
                "dispatched_policy": self.dispatched_policy,
                "evaluated_at": self.evaluated_at}


def _check(checks: list[dict], name: str, ok: bool, detail: str) -> bool:
    checks.append({"check": name, "outcome": "PASS" if ok else "FAIL",
                   "detail": detail})
    return ok


def evaluate(store, *, action: str, subject: str = "platform",
             action_class: str | None = None,
             investigation_row: dict | None = None,
             requested_sources: list[str] | None = None,
             agent_id: str | None = None,
             function: str | None = None) -> PolicyDecision:
    """Deterministic conjunction of rules; the FIRST failure mode wins,
    with every other check still reported (no short-circuit hiding).

        R-INV-LIFECYCLE  investigation exists, OPEN, unexpired (§63)
        R-DENY-SOURCES   requested families ⊆ allowed_sources (§35/§64)
        R-DISPATCH       function ∈ agent allowlist (A-14)
        R-EXTERNAL       action_class external-effect ⇒ REQUIRE_HUMAN (§27)
        R-DENY-DEFAULT   fail-closed: any FAIL ⇒ DENY overall
    """
    checks: list[dict] = []
    reasons: list[str] = []
    failed = False

    # R-INV-LIFECYCLE — only applied when an investigation binds the action
    if investigation_row is not None:
        inv = investigation_row
        ok = _check(checks, "R-INV-LIFECYCLE", inv.get("status") == "OPEN",
                    f"status={inv.get('status')}")
        exp_raw = inv.get("expires_at")
        exp_ok, exp_detail = True, f"expires_at={exp_raw}"
        if exp_raw:
            exp = datetime.fromisoformat(exp_raw)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                exp_ok = False
                exp_detail = f"expired {exp_raw}"
        ok = _check(checks, "R-INV-EXPIRY", exp_ok, exp_detail) and ok
        failed |= not ok
        if not ok:
            reasons.append(f"investigation {inv.get('id')} is not living "
                           f"({exp_detail}; status={inv.get('status')}) — "
                           "§76 requires living authorization")
        # R-DENY-SOURCES
        allowed = inv.get("allowed_sources")
        if allowed is None:
            allowed = json.loads(inv.get("allowed_sources_json") or "[]")
        if allowed and requested_sources:
            denied = sorted(set(requested_sources) - set(allowed))
            ok = _check(checks, "R-DENY-SOURCES", not denied,
                        f"allowed={allowed} requested="
                        f"{sorted(requested_sources)}"
                        + (f" denied={denied}" if denied else ""))
            failed |= not ok
            if denied:
                reasons.append("source families not in scope: "
                               f"{denied} (allowed: {allowed}); §35: LLM "
                               "proposes, policy disposes")
        else:
            _check(checks, "R-DENY-SOURCES", True,
                   "open public tier (empty allowlist)" if not allowed
                   else "no families requested")

    # R-DISPATCH — A-14 allowlists are architectural
    if agent_id and function:
        try:
            registry.check_dispatch(store, agent_id, function)
        except Exception:
            ok = _check(checks, "R-DISPATCH", False,
                        f"{agent_id}.{function} is not allowlisted")
            failed |= not ok
            reasons.append(f"{agent_id}.{function} is outside the A-14 "
                           "allowlist")
        else:
            _check(checks, "R-DISPATCH", True,
                   f"{agent_id}.{function} allowlisted")

    # R-EXTERNAL — §27/R-05 human gate
    if action_class in EXTERNAL_EFFECT_CLASSES:
        _check(checks, "R-EXTERNAL", True,
               f"action_class={action_class} is external-effect ⇒ human "
               "decision required before execution")

    if failed:
        return PolicyDecision(DENY, action, subject, checks, reasons)
    if action_class in EXTERNAL_EFFECT_CLASSES:
        reasons.append("external-effect action requires a recorded human "
                       "decision (§27/R-05)")
        return PolicyDecision(REQUIRE_HUMAN, action, subject, checks, reasons)
    return PolicyDecision(PERMIT, action, subject, checks,
                          reasons or ["all deterministic checks passed"])


def record(store, decision: PolicyDecision, actor: str) -> None:
    """Every decision is on the trail — denied decisions ARE the safety
    signal (learning loop), never filtered away."""
    store.audit(actor=actor, action=f"policy:{decision.action}",
                decision=decision.decision,
                detail=" | ".join(decision.reasons)[:400],
                policy_version=POLICY_ENGINE_VERSION)
