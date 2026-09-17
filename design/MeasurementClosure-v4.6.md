# v4.6 — MEASUREMENT CLOSURE · spec-mapping doc

Maps this tranche to the master spec. Position: v4.5 made the platform
pilotable and reported five §71 KPIs honestly **UNAVAILABLE — the write-paths
did not exist**. v4.6 builds those write-paths. The promise v4.5 made
("UNAVAILABLE names the gap") is now kept ("the gap is closed"). No KPI was
ever silently zero-filled in between.

## 1. The five flips (§71)

| KPI | v4.5 status | v4.6 write-path | v4.6 measurement |
|---|---|---|---|
| intelligence_quality.analyst_correction_rate | UNAVAILABLE (P-3) | review decisions: `POST /ops/review/{id}/decide` CONFIRMED/CORRECTED | CORRECTED ÷ decided reviews (window) |
| fact_checker.correction_rate | UNAVAILABLE | same route, `module='factcheck'` scope | CORRECTED ÷ decided factcheck reviews |
| fact_checker.latency | UNAVAILABLE | `checks.latency_ms` persisted by `ReasoningEngine.run_full_pipeline` (perf_counter around the full §1 pipeline) | mean ms of latency-persisting runs (window) |
| journey.reroute_acceptance_rate | UNAVAILABLE | watches elevation ≥ tolerance ⇒ `reroute_pending=1`; `POST /ops/watches/{id}/reroute` ACCEPT/DECLINE | ACCEPTED ÷ human-decided (AUTO_RESOLVED excluded) |
| journey.false_alarm_rate | UNAVAILABLE | `POST /ops/notifications/{id}/adjudicate` TRUE_/FALSE_POSITIVE | FALSE_POSITIVE ÷ adjudicated alerts (window) |

## 2. The write-paths (each is §76 for humans)

**Review decisions** (`core/adjudication.decide_review`). The §27 queue was
read-only until now. Decision semantics: CONFIRMED (system output stands) |
CORRECTED (requires the corrected outcome **in writing** — validation error
otherwise: an unwritten correction isn't a correction). `prior_outcome` is
resolved from the system's own persisted verdict (`checks.outcome` for
factcheck/kyc items) and stored alongside; where a module has no persisted
verdict, NULL is stored and the audit event says so — no back-filled
"system said" claims. Atomic single-decision guard (`UPDATE … WHERE
status='OPEN'`), double-decide → 409 REVIEW_ALREADY_DECIDED (approvals
engine parity). Mints `event:ReviewDecided`.

**Reroute adjudication** (`decide_reroute` + voyager patch). The machine
side: `voyager.reassess_watches` elevation ≥ tolerance now mints
`reroute_pending=1` alongside the ELEVATED flip. The human side: ACCEPT or
DECLINE, atomic, once. The engine's own out: when corridor risk eases with
a recommendation pending, `auto_resolve_reroute` retires it as
**AUTO_RESOLVED — explicitly neither acceptance nor rejection** and excluded
from the KPI denominator (denominator hygiene is stated in the KPI basis).
Mints `event:RerouteAdjudicated`.

**Alert adjudication** (`adjudicate_alert`). One verdict per alert,
atomically (`WHERE adjudication IS NULL`), second attempt → 409
ALERT_ALREADY_ADJUDICATED naming the recorded verdict and adjudicator.
Mints `event:AlertAdjudicated`.

## 3. Event vocabulary honesty

`ReviewDecided` / `RerouteAdjudicated` / `AlertAdjudicated` are **platform
extensions** beyond §26's fourteen named events — documented here and in
TRUST §15, following the v4.3 SourceHealthChanged precedent: extensions are
named openly, never smuggled into the spec list. Emission version
`adjudication/4.6.0`.

## 4. KPI engine consequences

`KPI_ENGINE_VERSION = "kpi-engine/4.6.0"`. The five metrics now read
measured rows with windows on `decided_at` / `adjudicated_at` /
`reroute_decided_at`. **Honesty rule preserved**: empty denominator ⇒ still
UNAVAILABLE (not 0), and the basis now names the write-path that exists and
is awaiting use — the exact sentence a pilot operator needs. New context
metrics: `reviews_decided_in_window`, `reroutes_pending`,
`alerts_adjudicated`. The v4.5 test pins were updated consciously (two
basis-text assertions), recorded here as an intended contract evolution.

Also resolved during live verification in v4.5 and carried through:
`notifications`/`review_queue`/`journey_watches`/`checks` receive their
v4.6 columns via guarded ALTERs (same migration idiom as v3.2–v4.4 — no
destructive change, old DBs upgrade in place).

## 5. Surface map

- Backend: `core/adjudication.py` (one home for human-outcome writes),
  migrations + atomic store methods (`review_decide`,
  `adjudicate_notification`, `decide_watch_reroute`, `reroute_rows`),
  engine latency persistence, voyager pending/auto-resolve, routes
  (`/ops/review/{id}/decide`, `/ops/notifications/{id}/adjudicate`,
  `/ops/watches/{id}/reroute`, `GET /ops/watches/reroutes`), RBAC
  (`review.decide` / `alerts.adjudicate` / `journey.reroute` = analyst),
  ERROR_MAP +6 codes.
- Frontend: Governance pane gains **Review decisions** (queue rows +
  confirm/correct + correction-note input) and **Journey oversight —
  reroutes** (pending with accept/decline, decided incl. AUTO_RESOLVED
  annotation); Alerts pane gains per-alert **✓ real / ✕ false alarm**
  adjudication with recorded-verdict chips.

## 6. TRUST posture

Blast radius: **MEDIUM** — new write columns on existing tables; atomic
single-decision guards everywhere; adjudication rows are append-only facts
on the permanent audit trail; no deletion paths; personalization untouched.
Review level: **D2** (same bar as adjudication-adjacent v4.2/v4.4 surfaces;
the denominator-hygiene rules are the load-bearing logic — line-reviewed).

## 7. Gates

`tests/test_v46_measurement_closure.py` — 18 tests (decision flows, 409
guards, RBAC, prior-verdict capture, auto-resolve denominator exclusion,
KPI flips, window semantics, empty-store honesty). **315/315 backend
green**, tsc clean, vite build green. Live-verified: full correction +
adjudication flows through the API, KPI read-out flipping UNAVAILABLE→OK on
the same database, voyager elevation minting pending recommendations.
