from gateway import Agent, Decision, Gateway, Tool

gateway = Gateway()
gateway.register_agent(Agent("logon-bi-agent", "workspace-owner"))
gateway.register_tool(
    Tool(
        "opportunity_search",
        frozenset({"READ", "CREATE"}),
        frozenset({"opportunity:catalog"}),
    )
)

print(
    "authorized discovery:",
    gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="opportunity_search",
        action="READ",
        resource="opportunity:catalog",
    ).value,
)

print(
    "attempted destructive action:",
    gateway.evaluate(
        agent_id="logon-bi-agent",
        tool_id="opportunity_search",
        action="DELETE",
        resource="opportunity:catalog",
    ).value,
)

print("audit chain valid:", gateway.audit.verify())
print(
    "adapter targets:",
    {"reasoning": "SERV", "tools": "MCP", "agents": "A2A",
     "identity": "ERC-8004", "machine_payments": "x402", "user_payments": "AP2"}
)
