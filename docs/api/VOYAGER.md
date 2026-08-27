# VOYAGER API — Full Schema (v3.4)

VOYAGER is the **external interface agent** (master spec §5.1; blueprint v5.2
§4). This document is the canonical schema for every function in its
A-14 allowlist — what PATHFINDER may dispatch, what the HTTP layer exposes,
and the honesty contract each output carries.

Governance: every function below is in
`backend/app/swarm/registry.py::NATIVE_AGENTS["VOYAGER"].api_functions`.
All are **read-only** (`read_only_functions`) — VOYAGER never causes external
effects; anything that would (patching, blocking, messaging) routes through
`AUDITOR.authorize_action` → REQUIRE_HUMAN instead.

---

## 1. Journey & situational functions

### `parse_route_context(text) -> dict`
Deterministic NL slot-filling (no LLM). Extracts `{origin, destination,
departure_hint}` from free text. `departure_hint ∈ {today, tonight, tomorrow,
null}`. Missing slots return `null` — never guessed silently.

### `assess_journey(origin, destination, departure_time, priority="balanced",
assumed_time=False) -> JourneyAssessment`
Corridor risk synthesis from ingested signals (incidents, weather, traffic).
- `risk_rating ∈ {LOW, MODERATE, HIGH, CRITICAL}` from evidence bands.
- `confidence` reflects independence-count of sources; copy-chains count as
  ONE source (§1.6).
- `assumptions[]` lists every inference (e.g. assumed departure time).
- `staleness` signals marked honestly when feeds are degraded (§20).

### `build_risk_timeline(origin, destination, departure_time) -> list[HourBand]`
Hour-by-hour corridor risk bands; each band carries its driving signals for
the Strategy Map drill-downs.

### `compare_routes(origin, destination, departure_time) -> list[RouteOption]`
Alternatives with **explicit trade-offs** (time vs exposure vs prediction
reliability). Never a single "best" answer without stated assumptions (§9).

### `predict_route_risk(origin, destination, departure_time) -> Prediction`
Hedged forward risk: `{level, basis, hedging}`. Language rule: predictions
are patterns, NOT certainties (§9) — the `hedging` field is mandatory.

### `monitor_active_journey(origin, destination, departure_time, ...) -> Watch`
Enrols a corridor watch for the §1.10 reassessment loop. Drift vs the stored
level emits `RISK_ELEVATION` / `RISK_RESOLUTION` notifications; elevation at
or beyond the user's tolerance flips watch status to `ELEVATED`.

---

## 2. Identity-integrity functions (blueprint v5.2 §5)

### `check_sim_swap(phone) -> CarrierProbe`
A-9 carrier-integrity probe.
- Response: `{phone_tail, status, notes, source}`.
- `status ∈ {OK, PORTED, SWAP_SUSPECTED, UNKNOWN}`.
- **Honesty rule:** without a live carrier API the status is `UNKNOWN` —
  UNVERIFIED, never cleared (§1.9). `TH360_SIM_FIXTURES` (JSON map
  `{phone: status}`) feeds bounded demo signals, same pattern as feed
  fixtures.

### `id_audit_l1(identity, identifier_type="auto", domain="", phone="",
consent_granted=True) -> L1Audit` — `/id_audit_l1`
L1 domain/carrier integrity audit. HTTP: `POST /api/v1/privacy/id-audit`
`{identity, identifier_type?, domain?, phone?, consent_granted?}`.

Response schema:

| field | type | notes |
| --- | --- | --- |
| `identity` / `identifier_type` | string | `identifier_type ∈ {email, domain, phone}` (`auto` resolves) |
| `level` | `"L1"` | L2/L3 (screening, biometrics) stay with AUDITOR/SENTINEL |
| `verdict` | `PASS \| REVIEW \| FAIL` | **indicator, not proof** — see `hedge` |
| `risk_points` | int | ≥6 → FAIL, >0 → REVIEW, 0 → PASS |
| `checks[]` | list | per-check `{check, source, verdict, signals[], detail}` |
| `hedge` | string | mandatory §1.9 caution |
| `disclaimer` | string | AI-generated-output notice (v5.2 §6.D) |
| `provenance` | `{checks[], degraded}` | which sources fed the verdict (§16) |

Behavioural rules:
- Domain check = bounded deterministic heuristics (TLD risk, estimated age,
  registrar recognition) in the demo profile; provenance says so.
- Carrier check wraps `check_sim_swap`: `UNKNOWN` can only push the overall
  verdict toward REVIEW — **never toward PASS** (fail-closed, §20).
- Every call is written to the AUDITOR trail (`id_audit_l1 → LOGGED`) so it
  appears in the Sovereign Data Stream and compliance math.

---

## 3. HTTP surfaces summary

| Surface | Function | Effect |
| --- | --- | --- |
| `POST /api/v1/journey/*` (assess, compare, predict, timeline, monitor) | journey fns | read-only |
| `POST /api/v1/privacy/id-audit` | `id_audit_l1` | read-only + trail |
| `POST /api/v1/ops/goal` / conversation | dispatched by PATHFINDER | read-only |
| fixture hook `TH360_SIM_FIXTURES` | `check_sim_swap` | demo binding |

Degradation: live-carrier/live-WHOIS calls not available in the demo profile
are marked `SOURCE_UNAVAILABLE`/stubbed per §20 — outputs state their
boundedness explicitly rather than fabricating coverage.
