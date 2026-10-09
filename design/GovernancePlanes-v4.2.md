# v4.2 "GOVERNANCE PLANES" — spec-to-code mapping (§73 V2)

Source of truth: `ThreatHunter360 v4.0 — Intelligence Platform Analysis &
Architecture.md`, §73 V2 = *agent inventory, readiness, supply chain,
policy engine, approval engine* — plus §34/§35 decision-responsibility.

## Policy engine

| Spec ref | Requirement | Implementation |
|---|---|---|
| §34 | "Deterministic systems = permissions, policy, … audit, execution controls" | `backend/app/core/policy_engine.py` — ONE `evaluate()` entry point; every decision returns `PERMIT \| DENY \| REQUIRE_HUMAN` + full check ledger (`R-INV-LIFECYCLE`, `R-INV-EXPIRY`, `R-DENY-SOURCES`, `R-DISPATCH`, `R-EXTERNAL`) + reasons + `policy-engine/4.2.0` version stamp |
| §35 | "LLM proposes → policy engine: authorized for this subject? → YES execute / NO reject-request-authorization" | `investigation.authorize_run` now **delegates** to `policy_engine.evaluate` with byte-for-byte behavior parity (same classified errors, same §26 events — 48 parity tests stay green); A-14 dispatch checks re-wrap `registry.check_dispatch`; `record()` writes every denial to the trail (denials are the safety signal, never filtered) |
| §27/R-05 | external-effect actions are human-gated | any `action_class` in `{"patch_apply","promote_custom_agent","execute_dork_set","webhook_deliver","active_probe","external_post"}` ⇒ REQUIRE_HUMAN |

## Approval engine

`backend/app/core/approvals.py` + `approvals` table + routes in `ops.py`:

- `request()` → §26 **ApprovalRequested** (the spec's exact event name)
- `decide()` → §26 **ApprovalGranted** / **ApprovalRejected**; the effect
  hook `on_approval` runs **only** on APPROVED — rejection proves no-op by
  construction (test `test_reject_never_runs_effect`)
- double-decides: atomic `WHERE status='PENDING'` transition → 409
  `APPROVAL_NOT_PENDING` (§20: never silent)
- single-step flow (`request_and_decide`): the operator IS the human
  (R-05) — one HTTP call, but the request/grant pair is two distinct
  on-trail events; the custom-agent promotion flow executes **through**
  this engine (status flips only inside the grant hook)

## Agent inventory / readiness / supply chain

`backend/app/core/agent_inventory.py`, `GET /api/v1/ops/agents/inventory`:
per-node cards with the spec's verbatim field set — owner, version, source,
publisher, permissions, credentials, trust status, last reviewed, known
issue, runtime exposure, data classification — plus:

- **the key question**: `blast_radius_note` per node ("If compromised: X
  allowlisted functions, Y non-read-only…" — AUDITOR flagged as worst case)
- **dependency graph**: declared edges (PATHFINDER→agents, SENTINEL→AUDITOR
  gate) with a note that they're review-derived, not probed
- **readiness audit**: NIST AI RMF Govern/Map/Measure/Manage summary
  computed from the live roster
- **honest limits**: no package-hash supply chain in the demo profile —
  stated on the record, never faked; trust mapping ACTIVE→TRUSTED,
  SHADOW→OBSERVED, REJECTED→QUARANTINED

## Frontend

Ops Node **Governance** pane: approvals queue (PENDING approve/reject
buttons; APPROVED/REJECTED shown with decider+time) and the agent
inventory (trust chips, per-node `details` cards, readiness summary,
dependency-edge line).

## Tests

`backend/tests/test_v42_governance_planes.py` — 19 tests: engine
permit/deny/require-human, reasons and ledger contents, dispatch rule,
audit recording, authorize_run parity, approval lifecycle/events/effects/
409/404, promotion chain (register→SHADOW→promote→ACTIVE with both §26
names in trail order), inventory field completeness, trust mapping, NIST
phases, honest-limits presence.

## Not in this tranche (spec order, honest note)

- **V2.5 continuous assurance**: live runtime monitoring, drift scoring,
  real-time TI — the `last_reviewed` card field says so.
- **Enterprise plane**: SSO/RBAC/SIEM/SOAR connectors.
- **Package-hash supply chain**: requires real build attestation; the demo
  profile's `honest_limits` states this rather than emitting fake hashes.
