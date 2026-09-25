# LOG_ON Agent Economy Control Plane v0.1

This is the first executable control-plane slice for LOG_ON.

## Core invariant

**agent identity -> permissions -> tools -> data access -> runtime monitoring -> approval boundaries -> audit trail**

The model may propose. The policy engine decides. AAGATE enforces. The evidence layer records.

## What is implemented

- Agent registry
- Tool/resource authorization
- Deterministic PASS / BLOCK / ESCALATE decisions
- High-impact human approval boundary
- Tool-call budget guard
- Agent suspension/revocation enforcement
- Hash-chained audit events
- Positive and negative security tests
- Agent-economy adapter map

## Agent-economy targets

| Layer | Target |
|---|---|
| Reasoning | SERV Reasoning |
| Tool protocol | MCP |
| Agent interoperability | A2A |
| Agent identity/trust | ERC-8004 |
| Machine payments | x402 |
| User-authorized payments | AP2 |
| Wallet capability | AgentKit / governed wallet adapters |

These are **adapter targets**, not claims of protocol implementation in v0.1.

## Demo

```bash
python logon-agent-economy/tests/test_gateway.py
python logon-agent-economy/demo.py
```

Expected control paths:

```
authorized READ       -> PASS
wrong resource        -> BLOCK
production DELETE     -> ESCALATE
approved DELETE       -> PASS
budget exceeded       -> BLOCK
suspended agent       -> BLOCK
```

## Next engineering slices

1. MCP gateway adapter
2. A2A delegation/capability envelope
3. External identity adapter
4. x402/AP2 payment policy adapters
5. Runtime event stream + incident engine
6. SERV reasoning integration
7. OpenServ workflow integration

This package is a reference implementation, not a production security boundary and not a certification claim.
