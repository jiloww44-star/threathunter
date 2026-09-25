# LOG_ON Assurance Gate — SERV Hackathon MVP

## Product

**LOG_ON Assurance Gate** is the smallest useful version of the LOG_ON product:

> **Before an AI agent acts, prove it may.**

The product is a Governance + Agent Assurance layer for agentic workflows.

The Agent Economy is a deployment environment LOG_ON can govern; it is not the product's primary identity.

## Demo loop

agent request
→ SERV reasoning
→ structured action proposal
→ LOG_ON deterministic policy
→ PASS / ESCALATE / BLOCK
→ audit evidence
→ audit-chain verification

OpenServ's current Hackathon Edition 01 requires a new, working, demoable agent/workflow/product that leverages SERV Reasoning. The Open Track accepts any SERV Reasoning build, and judging emphasizes creativity, user-readiness and revenue potential.

OpenServ states that SERV is available through an OpenAI-compatible inference endpoint at:

https://inference-api.openserv.ai/v1

and says existing OpenAI-compatible agents can use SERV by changing the base URL.

## Run

Copy `.env.example` to `.env` and set `SERV_API_KEY`. Adjust `SERV_MODEL` when needed for models available to the account.

```bash
npm start
```

Open `http://localhost:3000`.

Run tests:

```bash
npm test
```

## Assurance controls shown by the MVP

- Identity
- Permissions
- Tools
- Data access
- Runtime/environment
- Approval boundary
- Audit evidence

The MVP also exposes `GET /api/audit/verify` so the demo can prove that the in-memory evidence chain has not been altered since it was recorded.

## Product boundary

The MVP intentionally does not attempt to build a complete enterprise assurance platform.

It proves one thing:

**the reasoning model is not the authority.**

The model proposes a structured action. LOG_ON's deterministic control layer decides whether the action may proceed.

## Next

- AAGATE as a real execution boundary
- MCP tool adapter
- Assurance Passport
- Evidence Graph
- workflow-state authorization
- A2A delegation envelope
- continuous assurance
- governed economic actions
