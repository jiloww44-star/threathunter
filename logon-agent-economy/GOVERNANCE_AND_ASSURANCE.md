# LOG_ON Governance & Agent Assurance Control Plane

## Core role

LOG_ON is **not primarily a crypto agent, payment agent, or cybersecurity product**.

The primary role is:

> **Govern the lifecycle, authority, execution and evidence of AI agents operating inside business workflows and the emerging agent economy.**

The Agent Economy is one deployment environment that LOG_ON governs.

The security principle is:

> **A compromised model must not automatically become compromised authority.**

## Authority separation

```
HUMAN / ORGANIZATIONAL GOVERNANCE
        ↓
ASSURANCE CONTROL PLANE
        ├── risk classification
        ├── policy
        ├── approval rules
        ├── capability boundaries
        └── budget rules
        ↓
AUTHORIZATION PLANE
        ├── agent identity
        ├── agent registry
        ├── tool registry
        ├── delegation
        └── AAGATE
        ↓
AGENT RUNTIME
        ├── model
        ├── planner
        ├── memory
        └── workers
        ↓
ENFORCEMENT
        ├── MCP/API tools
        ├── browser
        ├── data
        ├── payments
        └── external systems
        ↓
ASSURANCE PLANE
        ├── evidence
        ├── audit-as-code
        ├── testing
        ├── runtime monitoring
        ├── drift detection
        └── incident response
```

The agent never becomes the authority over its own controls.

## Seven mandatory control dimensions

Every governed LOG_ON agent must maintain:

1. **Agent identity** — who/what is acting and who owns it.
2. **Permissions** — what the agent may do, against which resources and under what conditions.
3. **Tools** — which MCP/API/browser capabilities are registered and allowed.
4. **Data access** — what data classes/resources may be read, transformed or written.
5. **Runtime monitoring** — what happened during execution, including policy decisions and anomalies.
6. **Approval boundaries** — which actions require independent human or organizational approval.
7. **Audit trail** — evidence linking identity, intent, policy, tool, resource, approval, execution and outcome.

## Governance state machine

```
REGISTERED
   ↓
TESTING
   ↓
SHADOW
   ↓
APPROVED
   ↓
ACTIVE
   ├── DEGRADED
   ├── SUSPENDED
   ├── REVOKED
   └── RETIRED
```

An agent cannot become ACTIVE only because a flag changed. Promotion requires assurance evidence.

## Execution invariant

Every external side effect must pass:

```
intent
→ identity validation
→ registry lookup
→ tool/resource validation
→ risk classification
→ policy evaluation
→ budget check
→ approval check
→ circuit-breaker check
→ PASS / BLOCK / ESCALATE
→ execution
→ evidence
→ outcome monitoring
```

## Governance versus Agent Economy

Agent-economy protocols are **inputs to governance**, not replacements for governance.

| Agent-economy capability | Governance interpretation |
|---|---|
| A2A delegation | proposed delegated authority |
| MCP tool declaration | proposed capability |
| ERC-8004 identity/reputation/validation | external trust signal |
| x402 payment request | proposed economic side effect |
| AP2 mandate | user-authorized commerce signal |
| AgentKit wallet | controlled economic capability |
| SERV reasoning | proposal/reasoning layer |

The LOG_ON policy plane remains authoritative.

## Business workflow role

Governance is connected to business execution:

```
business objective
→ intelligence
→ decision
→ workflow
→ agent
→ governed authority
→ execution
→ verification
→ audit
```

The objective is not maximum autonomy.

The objective is **controlled autonomy that creates measurable business value with accountable authority**.

## Assurance evidence

A control is only considered implemented when:

```
DESIGNED
→ IMPLEMENTED
→ ENFORCED
→ TESTED
→ ATTACKED
→ VERIFIED
→ EVIDENCED
→ MONITORED
```

A dashboard checkbox, configuration field or model response is not proof of enforcement.

## v0.1 scope

This repository slice proves the first governance boundary:

- agent identity/state
- tool/resource authorization
- deterministic policy decisions
- approval escalation
- budget enforcement
- suspension enforcement
- tamper-evident audit events
- negative tests

It does not claim production-grade identity infrastructure, sandbox isolation, payment execution, A2A networking, ERC-8004 registration, x402 settlement, AP2 execution or compliance certification.
