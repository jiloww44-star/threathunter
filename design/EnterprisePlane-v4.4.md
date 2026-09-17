# v4.4 "ENTERPRISE PLANE" — spec-to-code mapping (§73 Enterprise)

Source of truth: `ThreatHunter360 v4.0 — Intelligence Platform Analysis &
Architecture.md`, §73 Enterprise = *SSO, RBAC, private deployment, custom
connectors, SIEM/SOAR, retention/policies*.

| Spec item | Adopted as | Honest boundary |
|---|---|---|
| **RBAC** | `core/rbac.py` — closed role set (viewer < analyst < governance < admin) + deterministic permission matrix; role resolution in `current_user`; enforcement at every governance surface (approvals.decide, assurance.sweep, agents.register/promote, inventory.read, siem.export, retention.apply, connectors.manage) | SSO is documented-only (no IdP in the sandbox); the demo human path is admin-with-disclosure or the `X-TH360-Role` demo override — plainly stated in `whoami`, never a production claim. API keys carry their declared role and cannot self-elevate (tested) |
| **Retention/policies** | `core/retention.py` — per-class windows, dry-run default, per-class counts, own audit row per run; sweeps: notifications 90d, assurance runs 180d, terminal trees 30d | `audit_trail` and `consent_ledger` are **PERMANENT by invariant** — the sweeper has no code path to them; a consent-chain deletion would self-evidence CRITICAL posture (v4.3 chain tests) |
| **SIEM/SOAR export** | `GET /ops/siem/export` — NDJSON audit/event stream with taxonomy classes (platform_event/policy_decision/safety/privacy/lifecycle/connector/governance…), provenance fields, record-count header | optional `TH360_SIEM_KEY` attaches an HMAC-SHA256 signature header — the signed-export contract; SOAR actions = the approval engine (existing), not a fake webhook farm |
| **Custom connectors** | `core/connectors.py` + `connectors` table + routes — §80 kinds A Methodology/B Discovery/C Data APIs/D Research Distribution; register ADMIN-only → PENDING_APPROVAL → approval-engine grant flips ACTIVE via the **durable effect registry** (`approvals.register_effect`), then the connector mounts into the Source Health Monitor as `connector:<name>` (§6/§32); retire is auditable | secrets are never stored — `auth_env` holds the env-var NAME only; pasted secrets are rejected 422 (§25) |
| **Private deployment** | documented profile: demo profile ≡ zero external keys; enterprise profile = env-provided broker keys + SIEM key + role-bearing API keys (README §private deployment) | not faked with fake SSO forms |

## Durable effects (v4.2 amendment)

`approvals.decide()` now resolves effects from a registered kind→function
map when no same-call hook is passed — queued approvals decided later still
execute. Connector activation is the first kind wired this way; legacy
same-call hooks (promotion) keep their (row) signature, registered effects
take (store, row). Rejection remains a provable no-op for both paths.

## Tests

`backend/tests/test_v44_enterprise_plane.py` — 21 tests: RBAC ranks,
resolution (no self-elevation, demo override), 403 enforcement matrix,
whoami, enterprise-key role; retention dry-run/apply/terminal-only trees/
invariants/route; SIEM NDJSON shape, taxonomy, HMAC sign/no-sign, RBAC;
connector full lifecycle + health-monitor visibility + rejection no-op +
secret rejection + kind closed set + admin gate.
