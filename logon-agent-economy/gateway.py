from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import time
from typing import Optional


class Decision(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class AgentState(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class Agent:
    agent_id: str
    owner: str
    state: AgentState = AgentState.ACTIVE
    max_tool_calls: int = 10


@dataclass(frozen=True)
class Tool:
    tool_id: str
    actions: frozenset[str]
    resources: frozenset[str]
    data_classes: frozenset[str] = frozenset({"PUBLIC", "INTERNAL"})


@dataclass(frozen=True)
class Approval:
    approval_id: str
    agent_id: str
    tool_id: str
    action: str
    resource: str
    expires_at: float


@dataclass
class AuditLog:
    events: list[dict] = field(default_factory=list)

    def append(self, event: dict) -> None:
        previous = self.events[-1]["event_hash"] if self.events else "GENESIS"
        event["previous_hash"] = previous
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
        event["event_hash"] = sha256(canonical.encode()).hexdigest()
        self.events.append(event)

    def verify(self) -> bool:
        previous = "GENESIS"
        for event in self.events:
            if event["previous_hash"] != previous:
                return False
            actual = dict(event)
            event_hash = actual.pop("event_hash")
            canonical = json.dumps(actual, sort_keys=True, separators=(",", ":"))
            if sha256(canonical.encode()).hexdigest() != event_hash:
                return False
            previous = event_hash
        return True


@dataclass
class Gateway:
    policy_id: str = "LOGON-GOV-BASE-001"
    agents: dict[str, Agent] = field(default_factory=dict)
    tools: dict[str, Tool] = field(default_factory=dict)
    approvals: dict[str, Approval] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)
    audit: AuditLog = field(default_factory=AuditLog)

    # Governance boundary: agents can propose requests, but cannot decide policy.
    GOVERNANCE_ROLE = "AGENT_GOVERNANCE_AND_ASSURANCE"

    def register_agent(self, agent: Agent) -> None:
        if agent.agent_id in self.agents:
            raise ValueError("duplicate agent_id")
        self.agents[agent.agent_id] = agent
        self.calls[agent.agent_id] = 0

    def register_tool(self, tool: Tool) -> None:
        if tool.tool_id in self.tools:
            raise ValueError("duplicate tool_id")
        self.tools[tool.tool_id] = tool

    def approve(self, approval: Approval) -> None:
        self.approvals[approval.approval_id] = approval

    def _event(
        self,
        trace_id: str,
        agent_id: str,
        tool_id: str,
        action: str,
        resource: str,
        decision: Decision,
        reason: str,
        approval_id: Optional[str],
    ) -> None:
        self.audit.append(
            {
                "event_id": f"evt-{len(self.audit.events)+1:05d}",
                "timestamp": time.time(),
                "trace_id": trace_id,
                "agent_id": agent_id,
                "tool_id": tool_id,
                "action": action,
                "resource": resource,
                "decision": decision.value,
                "reason": reason,
                "policy_id": self.policy_id,
                "governance_role": self.GOVERNANCE_ROLE,
                "approval_id": approval_id,
            }
        )

    def evaluate(
        self,
        *,
        agent_id: str,
        tool_id: str,
        action: str,
        resource: str,
        environment: str = "development",
        data_class: str = "INTERNAL",
        approval_id: Optional[str] = None,
        trace_id: str = "trace-demo",
    ) -> Decision:
        def reject(decision: Decision, reason: str) -> Decision:
            self._event(
                trace_id,
                agent_id,
                tool_id,
                action,
                resource,
                decision,
                reason,
                approval_id,
            )
            return decision

        agent = self.agents.get(agent_id)
        if agent is None:
            return reject(Decision.BLOCK, "unknown agent")

        if agent.state is not AgentState.ACTIVE:
            return reject(Decision.BLOCK, f"agent state is {agent.state.value}")

        if self.calls[agent_id] >= agent.max_tool_calls:
            return reject(Decision.BLOCK, "tool-call budget exceeded")

        tool = self.tools.get(tool_id)
        if tool is None:
            return reject(Decision.BLOCK, "unregistered tool")

        if action not in tool.actions:
            return reject(Decision.BLOCK, "action not authorized for tool")

        if resource not in tool.resources:
            return reject(Decision.BLOCK, "resource not authorized for tool")

        if data_class not in tool.data_classes:
            return reject(Decision.BLOCK, "data class not authorized for tool")

        needs_approval = action in {"DELETE", "TRANSFER", "PUBLISH"} or (
            environment == "production" and action == "UPDATE"
        )

        if needs_approval:
            if not approval_id:
                return reject(Decision.ESCALATE, "human approval required")

            approval = self.approvals.get(approval_id)
            if approval is None:
                return reject(Decision.BLOCK, "approval not found")

            if (
                approval.agent_id != agent_id
                or approval.tool_id != tool_id
                or approval.action != action
                or approval.resource != resource
            ):
                return reject(Decision.BLOCK, "approval scope mismatch")

            if approval.expires_at <= time.time():
                return reject(Decision.BLOCK, "approval expired")

        self.calls[agent_id] += 1
        self._event(
            trace_id,
            agent_id,
            tool_id,
            action,
            resource,
            Decision.PASS,
            "policy satisfied",
            approval_id,
        )
        return Decision.PASS
