# LOG_ON Agent Economy Alignment — Governed by the Assurance Plane

The Agent Economy is a **deployment domain** for LOG_ON, not LOG_ON's primary identity.

The primary LOG_ON role is:

> **Govern AI agents, their authority, their workflow participation and their evidence.**

## Governance chain

```
external protocol / agent
        ↓
identity normalization
        ↓
LOG_ON risk + policy
        ↓
AAGATE
        ↓
tool / agent / payment adapter
        ↓
execution
        ↓
evidence + monitoring
```

## Protocol mapping

| Layer | Protocol / platform | What LOG_ON governs |
|---|---|---|
| Reasoning | SERV | reasoning/proposals |
| Tools | MCP | capability scope + invocation |
| Agent collaboration | A2A | delegated task authority |
| Agent trust | ERC-8004 | identity/reputation/validation inputs |
| Machine payment | x402 | payment intent, amount, target, limits |
| User-authorized payment | AP2 | mandate scope and constraints |
| Wallet | AgentKit / wallet infrastructure | spending authority and recipient policy |

## Important distinction

An A2A message is not human authorization.

An ERC-8004 reputation signal is not authorization.

An MCP server declaration is not authorization.

An x402 payment request is not authorization.

An AP2 mandate is not a substitute for LOG_ON policy evaluation.

A wallet is not allowed to decide its own business policy.

LOG_ON remains the governance and assurance authority.

## Delegation model

Every child-agent capability should carry:

```
parent_agent
→ child_agent
→ task
→ allowed tools
→ allowed data/resources
→ budget
→ expiry
→ purpose
→ trace
```

Permissions do not propagate implicitly.

## Economic-action model

```
identity
→ business purpose
→ target / merchant
→ amount
→ data involved
→ risk
→ spending policy
→ approval threshold
→ payment protocol
→ execution
→ settlement evidence
```

Raw wallet private keys must never become model context.

## End-state

LOG_ON should become the assurance/control plane through which enterprise agents and external agents can safely participate in workflows and, where authorized, economic activity.
