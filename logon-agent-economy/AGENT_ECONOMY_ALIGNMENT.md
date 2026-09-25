# LOG_ON Agent Economy Alignment

## Position

LOG_ON is not a generic crypto agent. The target is:

**Agent Assurance + Business Intelligence infrastructure for governed agent-to-agent and agent-to-service commerce.**

External protocols are adapters around the LOG_ON authority boundary.

## Protocol map

| Layer | Protocol / platform | LOG_ON responsibility |
|---|---|---|
| Reasoning | SERV | reason and propose |
| Tool access | MCP | governed capability access |
| Agent interoperability | A2A | task/delegation transport |
| Agent identity/trust | ERC-8004 | discovery, identity, reputation, validation inputs |
| Machine payments | x402 | payment request/settlement adapter |
| User-authorized payments | AP2 | intent/mandate-bound payment adapter |

## Non-negotiable chain

```
external identity / protocol
        ↓
LOG_ON trust normalization
        ↓
policy engine
        ↓
AAGATE
        ↓
adapter / tool / payment execution
        ↓
evidence
```

An ERC-8004 reputation signal, A2A delegation message, MCP tool declaration, wallet capability, x402 payment request, or AP2 mandate does **not** independently authorize an action.

## Agent-to-agent delegation

Every delegation should become a bounded capability:

```
parent_agent
  ↓
child_agent
  ↓
task
  ↓
allowed tools
  ↓
allowed resources
  ↓
budget
  ↓
expiry
  ↓
trace
```

## Economic actions

Economic actions remain high-impact capabilities:

```
identity
→ purpose
→ merchant/resource
→ amount
→ spending policy
→ approval threshold
→ payment protocol
→ execute
→ settlement evidence
```

Raw private keys must never be exposed to the model.

## Future end-to-end demo

LOG_ON discovers a specialist agent, verifies trust inputs, delegates a bounded task, governs its MCP/tool access, evaluates an economic action, routes it through the appropriate payment adapter, and records the full evidence chain.
