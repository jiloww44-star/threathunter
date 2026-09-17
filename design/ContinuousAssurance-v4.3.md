# v4.3 "CONTINUOUS ASSURANCE" — spec-to-code mapping (§73 V2.5)

Source of truth: `ThreatHunter360 v4.0 — Intelligence Platform Analysis &
Architecture.md`, §73 V2.5 = *continuous assurance, live monitoring,
real-time TI, advanced governance* + §26 event vocabulary.

## What runs

`backend/app/core/assurance.py` — `run_assurance_sweep()` executes one full
loop honestly from live store rows:

| Channel | Source of truth | Output |
|---|---|---|
| §1.10 reassessment | `trust_layer.reassess_all` (watches + open verdicts + entity watchlists) | §26 events **RiskRecalculated** (verdict + watchlist movement) and **JourneyConditionChanged** (watch drift) — emitted natively inside `reassess_all` so *every* caller (sweep, `/ops/reassess`, post-ingest hook) names them; one emission site, never duplicated (§26 AlertTriggered fires from `store.notify` itself) |
| Source health | `core/health.health_state` (§6/§32 mapping, now shared BETWEEN the feed endpoint and the sweep) | per-source states; 24h staleness SLA flips ACTIVE→DEGRADED; transitions across sweeps mint platform event **SourceHealthChanged** (documented extension beyond §26) |
| Consent integrity | `privacy.verify_chain` (§5.3 hash chain) | `consent_chain_valid` in every summary |
| Posture rollup | deterministic rules (§54) | **CRITICAL** = broken consent chain or SEV1 incident active · **ATTENTION** = any source outside ACTIVE / pending approvals / denial burst / incident active · else **OK** with reasons enumerated |

Every sweep is an `assurance_runs` row — **posture is a series, not a
dashboard snapshot**: `GET /ops/assurance/status` returns latest + series.

## Routes

- `POST /api/v1/ops/assurance/sweep` — run a sweep, return full summary
- `GET /api/v1/ops/assurance/status?limit=` — latest + series + honest note
  (operator-requested cadence in the demo profile; scheduled cadence is the
  enterprise connector plane — stated, not faked)

## Failure posture (§20)

Every channel is individually failure-guarded: a broken reassessment loop
degrades its own block (`reassessment_degraded` string in the summary)
while posture math still completes from the other channels — tested.

## Frontend

Governance pane gains the **Continuous assurance** section: ▶ Run sweep
button, posture chip, reasons, §26 event counts, chain state, degraded
sources, posture series line (OK → ATTENTION → … with timestamps).

## Spec-honesty notes

- "Real-time TI connectors" in the demo profile = the *seeds* behind the
  source-health monitor; the monitor's 6-state lifecycle + staleness SLA is
  the real machinery a live connector would slot into (§80 broker contract).
- `AlertTriggered` emitted once per notification at the single chokepoint
  `store.notify` — a notification that isn't an operator alert doesn't
  exist in this platform (design invariant).

## Tests

`backend/tests/test_v43_continuous_assurance.py` — 18 tests: notify→
AlertTriggered, native §26 names on verdict/watch movement, posture rules
(OK / broken-chain CRITICAL / degraded source / pending approval / SEV1
CRITICAL + heals after resolve), sweep persistence, staleness flip,
cross-sweep transition events, §20 channel-degradation guard, route
round-trip, shared health mapping (routes vs core, boundary scores).
