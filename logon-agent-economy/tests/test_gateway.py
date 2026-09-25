import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway import Agent, AgentState, Approval, Decision, Gateway, Tool


def test_governance_is_authoritative():
    gateway = Gateway()
    assert gateway.GOVERNANCE_ROLE == "AGENT_GOVERNANCE_AND_ASSURANCE"

    gateway.register_agent(
        Agent("logon-bi-agent", "workspace-owner", max_tool_calls=3)
    )
    gateway.register_tool(
        Tool(
            "report_writer",
            frozenset({"READ", "CREATE", "UPDATE", "DELETE"}),
            frozenset({"report:daily-intelligence"}),
            frozenset({"PUBLIC", "INTERNAL"}),
        )
    )

    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="READ",
        resource="report:daily-intelligence",
        data_class="INTERNAL",
    ) is Decision.PASS

    # Wrong resource is blocked outside the model.
    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="UPDATE",
        resource="report:other-team",
        data_class="INTERNAL",
    ) is Decision.BLOCK

    # High-impact action escalates to an independent approver.
    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="DELETE",
        resource="report:daily-intelligence",
        environment="production",
    ) is Decision.ESCALATE

    gateway.approve(
        Approval(
            "APR-001",
            "logon-bi-agent",
            "report_writer",
            "DELETE",
            "report:daily-intelligence",
            time.time() + 60,
        )
    )

    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="DELETE",
        resource="report:daily-intelligence",
        environment="production",
        approval_id="APR-001",
    ) is Decision.PASS

    # Budget is enforced by the gateway, not by the model.
    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="READ",
        resource="report:daily-intelligence",
    ) is Decision.PASS
    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="READ",
        resource="report:daily-intelligence",
    ) is Decision.BLOCK

    # Suspension immediately removes execution authority.
    gateway.agents["logon-bi-agent"] = Agent(
        "logon-bi-agent", "workspace-owner", AgentState.SUSPENDED, 99
    )
    assert gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="report_writer",
        action="READ",
        resource="report:daily-intelligence",
    ) is Decision.BLOCK

    assert gateway.audit.verify()
    assert len(gateway.audit.events) >= 7


if __name__ == "__main__":
    test_governance_is_authoritative()
    print("ALL TESTS PASSED")
