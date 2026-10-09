# v4.5 — PRODUCTION PILOT READINESS · spec-mapping doc

Maps every piece of this tranche to the master spec
(`ThreatHunter360 v4.0 — Intelligence Platform Analysis & Architecture.md`,
verbatim at repo root). Roadmap position: the §73 ladder (V1 → Enterprise)
is complete as of v4.4; **v4.5 is the operational tranche that makes the
completed platform pilotable** — measurable (§71/§72), real-data-capable
(§80), and deployable with honest boundaries (§74–§76).

---

## 1. §71/§72 — KPI engine + north-star

Spec: *"KPIs (§71) — intelligence quality (evidence-backed conclusion rate,
contradiction detection rate, freshness, diversity, analyst correction
rate); journey (completion, reroute acceptance, false-alarm rate, freshness,
decision latency); fact checker (evidence coverage, agreement, correction
rate, latency); agent security (inventory counts, remediated findings,
coverage); governance (policy coverage, evidence completeness,
reconstruction time, exceptions)."*
§72: *"North-star: evidence-backed decisions successfully completed."*

| Spec asks | Implementation | Status |
|---|---|---|
| North-star count | `kpis._north_star()` — CLOSED investigations with ≥1 `investigation_links(kind='evidence')` | **measured** |
| evidence-backed conclusion rate | same rows as a rate | **measured** |
| contradiction detection rate | `review_queue` rows from the contradiction detector ÷ `checks` | **measured** (0/0 ⇒ UNAVAILABLE) |
| freshness | age of newest `evidence.fetched_at` | **measured** |
| diversity | distinct `source_id` in evidence store (+independence handled by §1.6 in fact-check coverage) | **measured** |
| analyst correction rate | review decisions store no system-vs-human diff | **UNAVAILABLE, basis names gap (proposal P-3)** |
| journey completion | CLOSED ÷ all investigations | **measured** |
| reroute acceptance | watches carry no accept/decline adjudication | **UNAVAILABLE, named** (reroute *events* measured from `event:JourneyConditionChanged`) |
| false-alarm rate | notification outcomes not adjudicated | **UNAVAILABLE, named** (alert volume measured) |
| journey decision latency | mean request→decision across the approval engine (the authorization decision is the journey's consequential decision, §37) | **measured** |
| fact-check evidence coverage | share of runs with `coverage=HIGH` mined from persisted `checks` rows (v4.0 §49 axis made this computable) | **measured** |
| agreement | mean §1.6 copy-chain-aware independent-source count per run | **measured** |
| fact-check correction rate / latency | not persisted per run | **UNAVAILABLE, named** |
| agent inventory counts / coverage | `agent_inventory.inventory()` cards — totals, trust distribution, known-issue count, review-field coverage | **measured** |
| remediated findings | APPROVED approvals of kind `*patch*` (remediation through the engine, §37) | **measured** |
| policy coverage / decisions | investigations with declared `allowed_sources`; `audit_trail` grouped PERMIT/DENY/REQUIRE_HUMAN in window | **measured** |
| evidence completeness | `privacy.verify_chain()` re-run on read → 1.0/0.0 | **measured** |
| reconstruction time | wall-clock of 500-row audit re-read + full chain reverify, measured live per request | **measured** |
| exceptions | APPROVED approvals with explicit `decision_basis_overrides` + pending>72h aging debt + override_rate | **measured** |

**The honesty rule (§20 applied to telemetry):** every KPI is a
`KpiValue{value, unit, status, sample, basis}`. UNAVAILABLE means the
write-path does not exist; the basis names it. A measured zero (sample n) is
OK — a fabricated zero is never emitted. Prometheus export
(`GET /ops/metrics`, text exposition, zero deps) omits UNAVAILABLE value
series entirely and emits `th360_kpi_available{...} 0` instead — alerting on
un-measurable KPIs is possible, consuming fake numbers is not.

Surface: `core/kpis.py` (`KPI_ENGINE_VERSION = "kpi-engine/4.5.0"`),
`GET /api/v1/ops/kpis` (legacy block + `v71`), standalone
`GET /api/v1/ops/kpis/v71`, `GET /api/v1/ops/metrics` — all RBAC `read`
(viewer+). Ops Node **KPIs pane** renders north-star banner + five family
sections; UNAVAILABLE chips carry the basis in full (not just a tooltip).
Window via `TH360_KPI_WINDOW_HOURS` (default 168h) or `?window_hours=`.

## 2. Override instrumentation (§71 "exceptions")

The platform already writes the two decision trails a pilot needs:
`policy_engine.record()` audits every PERMIT/DENY/REQUIRE_HUMAN (v4.2) and
the approval engine keeps request/decision timestamps + context (v4.2).
v4.5 turns them into first-class telemetry: `policy_decisions` by outcome,
`decision_latency`, `override_exceptions`/`override_rate`
(context `decision_basis_overrides` on APPROVED rows), aging governance debt
(`approvals_pending_over_72h`). Nothing is inferred — every counter is a
GROUP BY over the permanent audit trail (retention-invariant since v4.4).

## 3. First REAL source, through the registry (§80 + §73 Enterprise)

Spec §80 source map types A–D; the v4.4 connectors registry is the only
door. v4.5 onboards the pilot's first live source — **crt.sh Certificate
Transparency**:

- **Why crt.sh**: PASSIVE only (§64 *public infrastructure record
  (technical)* — lowest-sensitivity OSINT class), keyless (no §25 credential
  theater), deterministic content hash (§68 reproducibility + idempotency).
- **Gate order** (`live_sources.run_crtsh_observation`, each failure
  classified §20): **§76** living-case via `authorize_run` (exact parity
  with every consequential run) → **§63** scope binding (queried domain must
  be the case subject or in its subdomain cone; IPs/URLs/wildcards rejected
  as non-scope) → **§80** connector ACTIVE and on the case allowlist →
  fetch.
- **Wire discipline**: injectable `http_get`; classified taxonomy
  `SOURCE_TIMEOUT` (503) / `SOURCE_UNREACHABLE` (503) / `SOURCE_THROTTLED`
  (429) / `SOURCE_BAD_RESPONSE` (502), each with what-happened / what-it-
  means / what-to-do payloads; new codes added to `ERROR_MAP`; the
  PipelineError handler now also surfaces `detail` (additive — legacy keys
  unchanged).
- **Evidence discipline**: one PAGE-mode evidence row per distinct CT
  snapshot (sha256 over canonical names) — re-observing identical bytes
  links but never duplicates; metadata carries query, connector id, result
  hash, truncation flag, `reliability=HIGH`, `authority=PRIMARY`
  (append-only signed logs), PII note (§61: infrastructure identifiers
  only); `evidence_id_by_hash()` is the idempotency chokepoint.
- **Event + health discipline**: `event:SourceQueried` (ALLOW *and* DENY on
  failure) + `event:ObservationReceived` in §26 vocabulary at
  `policy_version="live-sources/4.5.0"`; the connector's source-health row
  reflects outcomes — **DEGRADED with cause+timestamp after classified
  failures, ACTIVE after success** (scorecard via `update_source_health`;
  the activation-time mount alone no longer masquerades as fetch health —
  caught in live verification).
- Route: `POST /api/v1/osint/live/crtsh`, RBAC `investigate.run` (analyst+).

## 4. Deployable profile (docker refresh + runbook)

`docker-compose.yml` passes `TH360_SIEM_KEY` / `TH360_KPI_WINDOW_HOURS`
through (defaults preserve demo behavior); `.env.example` documents the
secret-by-env-NAME convention for connectors; **`PILOT.md`** is the
operator runbook: start → scrape `/ops/metrics` → governed crt.sh onboarding
(register→approve→observe) → KPI watch table with trip-wires → smoke
checklist → rollback (single-commit revert; all v4.5 storage additive).

## 5. TRUST posture (blast radius + review level)

- **Blast radius: MEDIUM.** New write paths are evidence rows, audit rows,
  health scorecards — all existing permanent/consent-safe classes; no new
  credential handling (crt.sh keyless); the KPI accessor `kpi_sql` is
  SELECT-only by construction (refuses non-SELECT).
- **New failure modes**: an ACTIVE connector with a broken egress shows
  DEGRADED (honest); KPI consumers may build dashboards on UNAVAILABLE
  series — mitigated by making unavailable states explicit first-class
  output in UI + export.
- **Review level**: human review of this mapping doc + PILOT.md before any
  tenant onboarding — same bar as v4.3/v4.4 addenda.

## 6. Gates

`backend/tests/test_v45_pilot_readiness.py` — 25 tests (KPI shape/honesty,
measured-from-real-rows families, Prometheus contract, full governed crt.sh
chain incl. idempotency + classified failure + health flip, RBAC, domain
normalization). **297/297 backend green**, `tsc --noEmit` clean,
`vite build` green. Live-verified end-to-end: connector lifecycle →
classified SOURCE_UNREACHABLE (sandbox egress blocks crt.sh TLS) → DENY on
the audit trail → monitor honestly DEGRADED → KPI/§72 metrics reporting →
Prometheus exposition omitting UNAVAILABLE series by design.
