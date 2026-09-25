# LOG_ON Governance & Agent Assurance Control Plane v0.2

**Primary role:** govern and assure AI agents operating inside enterprise workflows and the emerging agent economy.

The Agent Economy is **not** the product boundary. It is one environment whose agents, tools, delegations, data access and economic actions are governed by LOG_ON.

## Core principle

> **The model may reason. The runtime may propose. The policy plane decides. AAGATE authorizes. Infrastructure enforces. The assurance plane proves what happened.**

## Seven mandatory control dimensions

**agent identity → permissions → tools → data access → runtime monitoring → approval boundaries → audit trail**

The agent must never become the authority over the controls protecting it.

## What this repository slice proves

- agent identity/state enforcement
- explicit tool and resource authorization
- deterministic PASS / BLOCK / ESCALATE policy decisions
- human approval boundaries for high-impact actions
- runtime/tool-call budget limits
- suspended/revoked agent enforcement
- tamper-evident hash-chained audit events
- positive, negative and bypass-oriented tests
- Agent Economy protocol adapter targets

## Architecture

```
Business objective
      ↓
LOG_ON Intelligence / SERV Reasoning
      ↓
Agent Runtime
      ↓
Policy + Risk + Assurance Control Plane
      ↓
AAGATE
      ↓
MCP / A2A / Browser / Data / Economic adapters
      ↓
External systems
      ↓
Evidence + Audit + Monitoring
```

## Agent Economy alignment

| Capability | External layer | LOG_ON responsibility |
|---|---|---|
| Reasoning | SERV | propose / reason |
| Tools | MCP | govern tool access |
| Agent-to-agent | A2A | govern delegation |
| Identity/trust | ERC-8004 | normalize trust signals |
| Machine payments | x402 | govern economic side effects |
| User-authorized payments | AP2 | verify intent/mandate constraints |
| Wallets | AgentKit / wallet APIs | expose bounded capabilities only |

External protocol signals never independently authorize execution.

## Demonstrated control paths

```
authorized READ              -> PASS
wrong resource               -> BLOCK
destructive action           -> ESCALATE
approved destructive action  -> PASS
budget exceeded              -> BLOCK
suspended agent              -> BLOCK
```

## Tests

```bash
python logon-agent-economy/tests/test_gateway.py
python logon-agent-economy/demo.py
```

## Roadmap

1. MCP enforcement adapter
2. A2A scoped delegation and capability envelopes
3. workload identity / SPIFFE adapter
4. data policy + tenant isolation
5. runtime event stream
6. circuit breaker + kill authority
7. sandbox enforcement
8. x402/AP2 governed payment adapters
9. ERC-8004 trust adapter
10. SERV/OpenServ orchestration
11. assurance test harness + attack corpus
12. drift detection + continuous assurance

This is a reference implementation. It is not a production security boundary and does not claim certification or compliance.
