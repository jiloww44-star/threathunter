# v4.0 "INTELLIGENCE CORE" — spec-to-code mapping

Source of truth: `ThreatHunter360 v4.0 — Intelligence Platform Analysis &
Architecture.md` (pasted spec, preserved verbatim at repo root).

## What this tranche adopts (from §73 MVP definition: V1 core)

| Spec § | Requirement | Implementation |
|---|---|---|
| §2 | Investigation is the primary backend object | `backend/app/core/investigation.py` + `investigations`/`investigation_links` tables (`store/db.py`) + `routes/investigate.py` |
| §63 | Authorization object: purpose, subject, authority, scope, expiration, allowed sources | columns on `investigations`; `create()` validates authority + subject_type vocab; expiry clamped 1–90 days and always set |
| §35 | LLM proposes, policy disposes | `authorize_run()` executes in `pathfinder.propose_plan()` **before any tree exists** — a refused plan leaves zero tree rows (test `test_plan_denied_before_tree_exists`) |
| §76 | Invariant: no consequential action without living authorization | closed/expired investigations raise classified `ACTION_DENIED` 403s with §76 in the meaning; `errors.py` ERROR_MAP entry added |
| §26 | Event vocabulary on a single event store | `event:InvestigationCreated / EvidenceLinked / InvestigationClosed / AuthorizationDenied / AuthorizationExpired` appended to the existing `audit_trail` with `policy_version=intel-core/4.0.0` — no shadow tables |
| §5 | Evidence chain: artifact → investigation linkage | `investigation_links` rows (`ops_tree` links created automatically by propose/run; any artifact via `POST /{id}/link`) |
| §70 | Reports separate Observed / Interpreted / Assessed / Recommended | `epistemic` block on every UnifiedReport (`pathfinder.synthesize()`), derived from real assembly fields — observed counts only `EVIDENCE`-labelled items |
| §49–51 | Confidence AND Coverage axes; never "Risk = 76%" | `coverage` + `coverage_basis` on `FactCheckResponse` (`reasoning_engine._coverage_assessment`, deterministic: HIGH = ≥3 independent groups + PRIMARY; MEDIUM = ≥2; else LOW). `assessed.confidence_axis` strings state "never a single 'risk %'" |
| §6/§32 | Source Health Monitor: ACTIVE \| DEGRADED \| AUTH_REQUIRED \| SCHEMA_CHANGED \| DEPRECATED \| UNAVAILABLE | `GET /api/v1/feed/source-health` — deterministic mapping (`routes/feed.py::_health_state`) from `sources_meta` health scorecards + notes |
| §64 | Source-sensitivity tiers (allowlists bind source families) | `BRANCH_SOURCES` map in `core/investigation.py`; empty allowlist = disclosed open public tier |
| Frontend | Ops Node "Cases" tab | list/create/activate/close; "Link current tree"; plan-review card shows the bound case id; `opsGoal`/`planGoal` pass `investigation_id` |

## Explicitly deferred (per §73/§74 — NOT V1)

- **Agent supply chain & inventory (V2 plane)** — spec §73 assigns it to V2;
  the v3.0 SHADOW-mode custom-agent registry already covers the admission
  half and stays as-is.
- **NIST five-plane separation as separate services** — §13 is honored here
  as *documentation of the control mapping* (Evidence/Gap/Owner/Control/
  Status live in TRUST.md), not a five-process deployment. Single-store,
  single-service remains the demo profile.
- **TanStack/Next rewrite of the frontend** — the React+Vite Ops Node gains
  the Cases tab in place; no framework migration in V1.
- **1,000 OSINT connectors / autonomous pentesting / custom LLM (§74)** —
  out of scope by spec.

## Data model

```
investigations(id, objective, subject_type, subject, purpose, authority,
               scope, allowed_sources_json, expires_at, status, user_id,
               created_at, updated_at)           status: OPEN | CLOSED
investigation_links(id, investigation_id, kind, ref_id, created_at)
```

No migration needed for existing DBs — `CREATE TABLE IF NOT EXISTS` runs in
the same idempotent schema block as the rest of the store.

## Failure posture (§20)

- Unknown id → `TREE_NOT_FOUND` 404 (reuses existing classified code).
- Closed/expired → `ACTION_DENIED` 403 + audit event; detail names the §76
  invariant and what to do next (renew or open a new investigation).
- Allowlist denial → `ACTION_DENIED` 403 naming the denied source families
  and the allowed set; `AuthorizationDenied` event recorded.
- Empty allowlist → disclosed "open public tier" in UI and events — never a
  silent blanket authorization claim.

## Tests

`backend/tests/test_intel_core.py` — 31 tests: object lifecycle, gate
denials (expired/closed/unknown/allowlist), pathfinder binding (denied plan
leaves no tree; accepted plan links the tree), epistemic block structure,
coverage-axis boundaries, source-health vocabulary + mapping table +
endpoint shape.
