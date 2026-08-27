# ThreatHunter360 — Inductive Intelligence Platform

An implementation of the **ThreatHunter360 — Automated Data Scraping & Content
Extraction Architecture** spec (in this repo). The document is the single
source of truth; every module here traces back to it by section (§) and Part
reference.

```
┌ FACT CHECKER ─┬─ JOURNEY ADVISOR ─┬─ KYC VERIFICATION ─┬─ RECENT CHECKS ┐
│                    INDUCTIVE-LOGICAL REASONING ENGINE                    │
│        Observation → Signals → Patterns → Hypotheses → Confidence        │
│              EVIDENCE CORRELATION & STORE (provenance first)             │
│     SCRAPING PIPELINE: Schedule → Fetch → Extract → Normalize →          │
│                        Signalize → Weight → Store                        │
│         DATA SOURCES · reliability · authority · independence_group      │
└──────────────────────────────────────────────────────────────────────────┘
```

## Quickstart (runs today, zero external dependencies — spec Part 10)

```bash
# 1. Backend (auto-ingests the demo seed pack on first boot)
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. Frontend (second terminal)
cd frontend && npm install && npm run dev

# 3. Tests (spec Part 8 — 60 tests, engine suite is trust-critical)
cd backend && python -m pytest tests
```

- Dashboard: **http://localhost:5173**
- API docs: **http://localhost:8000/docs**
- One-command wrapper: `scripts/run_demo.sh`
- Full production topology (FastAPI + Celery + pgvector Postgres + Redis):
  `docker compose up --build`

## The five scripted demo scenarios — [`seed/demo_scenarios.md`](seed/demo_scenarios.md)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | “Company X was sanctioned in August 2026” | `MOSTLY_TRUE` · `HIGH` · copy-chain collapsed (independent < total) · contradiction flagged |
| 2 | “A celebrity secretly married in Lagos last week” | `UNVERIFIED` · `UNDETERMINED` — never fabricated |
| 3 | Lagos→Ibadan at 21:00 vs 07:00 | HIGH risk at km 42 at night, LOW/MODERATE by day, per-segment *why* |
| 4 | KYC fixture with date inconsistency | `VERIFIED_WITH_ADDITIONAL_REVIEW` — anomaly ≠ fraud, routed to §27 queue |
| 5 | `python seed/seed_script.py --confirm`, then reassess check #1 | upgrades to `VERIFIED` · `VERY_HIGH` — §1.10 continuous reassessment |

## Architecture map (spec → code)

| Spec part | Implementation |
|---|---|
| Part 1 — FastAPI backend | `backend/app/` (routes, core, scraper, store, models) |
| Part 1.3 / §19 — response contract | `backend/app/models/schemas.py` → `IntelligenceResponse` |
| Part 1.5 — Inductive engine | `backend/app/core/reasoning_engine.py` (observation → discovery → independence → contradictions → H1–H4 → confidence → verdict), `confidence.py`, `contradictions.py`, `trust_model.py` |
| Parts 2·3 — scraping pipeline | `backend/app/scraper/` (fetcher·extractor·dedupe·orchestrator), registry `seed/sources_demo.yaml` |
| Part 4 — storage schema | `backend/app/store/db.py` (SQLite demo adapter over the spec's Postgres/pgvector contract; production via docker-compose) |
| Part 5/§5 — modules | routes `factcheck.py` · `journey.py` · `kyc.py`; core `journey.py` (risk fusion, predictions §9 hedged) · `kyc.py` (consistency §12, decision §13, MockBiometricProvider) |
| Part 8 — testing | `backend/tests/` — copy-chain=1 source, contradiction blocks VERY_HIGH, UNVERIFIED≠FALSE, anomaly≠denial, hedged-language fuzz |
| Part 10 — seed pack | `seed/` — fixtures deliberately designed to exercise corroboration, copy-chains, entity confusion (H3), night-vs-day risk |
| Part 11 — voice | `backend/app/api/routes/voice.py` (spoken summaries) + `frontend/src/hooks/useVoice.ts` (Web Speech adapter, graceful degradation §20) |
| Part 12 — evidence graph | `GET /api/v1/graph/case/{id}` → `EvidenceGraph.tsx` (COPIED_FROM edges visualized in red) |
| Part 13 — multi-tenant | `api/deps.py` tenant resolution; demo enterprise key `sk_demo_threathunter360` |
| Part 2 — React dashboard | `frontend/src/` — home, ClaimInput (280-char counter), LoadingStages, progressive-disclosure result, RiskTimeline, KYCFlow, dark design tokens, `prefers-reduced-motion` respected |
| **v3.0** A-02 PATHFINDER mesh | `backend/app/swarm/pathfinder.py` — RGD goal → TaskTreeJSON → parallel branch execution → UnifiedReport; 2N peer registry + store-persisted task transitions = resumable failover (§3.3) |
| **v3.0** §3.1 Conversational Cortex | `backend/app/swarm/cortex.py` — dialogue over RGD, context object retention, minimal clarifying questions (§14–15), live progress narration (§21) |
| **v3.0** §5.1/A-03..A-06 agents | `backend/app/swarm/agents/` — VOYAGER (journey restoration + live monitoring), SENTINEL (CVE scan → VPR → human-gated patching), SENTINEL Forensics (A-04), HUNTER (OSINT over evidence graph, honest coverage gaps), AUDITOR (PII masking · screening · `authorize_action` · immutable trail) |
| **v3.0** §3.2/§1.10 Trust Layer | `backend/app/core/trust_layer.py` — shared evidence graph, global contradiction monitor, label separation (§26), continual reassessment → verdict/risk-change notifications (wired post-ingest, §20-guarded) |
| **v3.0** A-14/§5.2 governance | `backend/app/swarm/registry.py` — function allowlists architectural; SDK custom agents admitted via AUDITOR gate into SHADOW mode until human promotion |
| **v3.0** A-01/A-15 Ops Node | `frontend/src/views/OpsNode.tsx` — Cortex chat, Strategy Map, Swarm Timeline/Task Matrix, verdict-change alerts, Intel Feed (v1 §3 restored), Sovereign KPIs (§3.3 metrics) |
| **v3.1** §5.3 Consent ledger | `backend/app/core/privacy.py` — hash-chained, append-only consent log (tamper-evident, auditor-verifiable); KYC consent is a real ledger write; `routes/privacy.py` |
| **v3.1** §3.4 Personalization | `backend/app/core/personalization.py` — consent-gated watchlists/priority/tolerance/format; CI-enforced rule: presentation & alerts only, never verdict/risk (§5.5 TRUST.md) |
| **v3.1** §5.4 Access parity | `frontend/src/hooks/useBandwidth.ts` + Settings view — auto (Save-Data/2G) or manual low-bandwidth mode; JourneyMap degrades to a text-first risk strip |
| **v3.2** Safety-by-design | UX review blockers closed: Plan Review gate (`/ops/plan`→`/approve`), Halt Execution (cooperative drain, HALTED states), report/data deletion, functional Incident Declaration (webhook-honest delivery), AUDITOR ethics gate (private-target + jailbreak refusals pre-decomposition), AI-output disclaimer everywhere, safety-event learning loop in KPIs — mapping: `design/Safety-Review-v3.2.md` |
| **v3.3** Sovereign Ops Node (blueprint v5.2 "Tactical Swarm Edition") | Tactical HUD reskin (#020408 / lime #CFFF00 / teal #1A5454 / red #DC2626; Space Grotesk·Inter·JetBrains Mono), mobile bottom-nav, **Sovereign Data Stream** (`/ops/stream` — persisted audit rows + honestly-labelled live heartbeat pulses), **id_audit_l1** (`/privacy/id-audit` — VOYAGER L1 domain/carrier integrity, hedged PASS/REVIEW/FAIL, UNKNOWN ≠ PASS), identity-intel RGD fan-out (HUNTER→VOYAGER→AUDITOR with identifier-first entity extraction), **4-step onboarding wizard**, **Govern tab** with transparent **Compliance Index** (`/privacy/compliance-index`, 4×25 indicator — not a certification) — mapping: `design/SovereignOps-v5.2.md` |
| **v3.4** Red-team hardening (deferrals #3/#9) | **Cortex crisis-signal detection**: live-incident language prepends an honest notice, returns a `declare_incident` action hint (one-click pathway, never cosmetic), drills/tabletop phrasing suppressed; logged to the safety learning loop once per session. **Region-aware consent defaults**: declared region catalogue (GLOBAL/EU_UK/NG opt-in · US opt-out), explicit ledger entries always win, biometrics stay opt-in in every region, effective state + origin shown honestly in the Govern tab; personalization gate reads the effective state. **VOYAGER API schema**: `docs/api/VOYAGER.md` — full function/governance/degradation contract |

## Repo layout

```
backend/           FastAPI platform (demo profile: SQLlite + zero-model NLP)
  app/api/routes/  factcheck · journey · kyc · feed · graph · voice · admin · ops
  app/core/        reasoning_engine · confidence · contradictions · journey · kyc
                    · trust_layer (v3.0) · review_routing
  app/swarm/       v3.0 — pathfinder · cortex · registry · agents/{voyager,
                    sentinel, hunter, auditor}
  app/scraper/     fetcher · extractor (JSON-LD first) · dedupe (simhash) · orchestrator
  app/store/       evidence/signals/hypotheses/checks/review_queue +
                    v3.0 ops_trees/ops_tasks/notifications/audit_trail/
                    custom_agents/journey_watches
  tests/           162 tests (engine / journey / kyc / API / geo / governance /
                    sovereign-fusion / privacy-personalization /
                    safety-by-design / sovereign-ops / v3.4-hardening suites)
frontend/          React + Vite dashboard (progressive disclosure, accessible)
  src/views/       Home · FactChecker · JourneyAdvisor · KYCFlow · Analytics · OpsNode
seed/              Part 10 demo pack + scenarios + seeder (+ --confirm for §1.10)
                    + v3.0 asset_inventory/cve_feed fixtures
scripts/           run_demo.sh
docker-compose.yml Production topology (api/worker/beat/db/redis)
```

## v3.0 SOVEREIGN FUSION (upgrade spec → this build)

Master spec: [`ThreatHunter360 v3.0 — SOVEREIGN FUSION Upgrade Specification.md`](ThreatHunter360%20v3.0%20—%20SOVEREIGN%20FUSION%20Upgrade%20Specification.md).
Release plan §8 status: **P1 ✅ · P2 ✅ · P3 ✅ (incl. the §3.4
personalization layer — consent-gated, watchlist drift alerts, CI-enforced
"presentation never conclusions") · P4: SDK shadow-mode ✅, privacy
completion ✅ (§5.3 hash-chained consent ledger), a11y parity ✅ (§5.4
low-bandwidth text-first mode + reduced-motion budget); hyperscale
certification remains a production-phase item. Design/audit notes for the
v3.1 tranche: [`design/Product-Audit-v3.1.md`](design/Product-Audit-v3.1.md).**

Try it (Ops Node → #/ops):

```bash
curl -X POST localhost:8000/api/v1/ops/goal -H 'Content-Type: application/json' \
  -d '{"goal":"Secure the Lagos IoT deployment — scan for vulnerabilities"}'
# → UnifiedReport: 14 findings, P1 ticket in the human queue, patch request
#   parked AWAITING_HUMAN (AUDITOR authorize_action = REQUIRE_HUMAN)

curl -X POST localhost:8000/api/v1/cortex/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-1","message":"I am travelling tomorrow"}'
# → "Where are you leaving from, and where are you headed?" (context retained)

curl -X POST localhost:8000/api/v1/ops/reassess
# → §1.10 continual reassessment: fired notifications on any verdict/risk drift
```

Canonical invariants the v3.0 suite enforces (24 tests, `tests/test_sovereign_fusion.py`):
every UnifiedReport carries the §6 spine; A-14 dispatch outside an allowlist is
BLOCKED and audited; patching never executes autonomously; SHADOW agents cannot
execute until a human promotes them; missing feeds degrade to classified
`SOURCE_UNAVAILABLE`, never fabricated findings; journey watches and open
checks re-test on new evidence and notify on drift.


## Free-Tier Stack Integration (spec §1–§4)

| Integration | Where | Behavior |
|---|---|---|
| **OpenStreetMap** — Nominatim geocoding, OSRM routing, Leaflet map | `backend/app/services/geo.py`·`routing.py`, fused in `core/journey.py` (`build_risk_timeline_live`), rendered in `frontend/src/components/JourneyMap.tsx` | Keyless, fair-use limited (1 req/s, cache + semaphore). Unavailable → fixture corridor with visible `data_mode: "offline-fixture"` (§20), map still renders seeded segments |
| **Firecrawl** — evidence sourcing | `backend/app/scrapers/firecrawl_adapter.py`, `method: firecrawl[_search]` in the source registry (see `seed/sources_demo.yaml` commented examples) | Every call budget-guarded as `firecrawl:<source_id>` (§2.4); exhaustion → SOURCE_DEGRADED. `search` mode assigns dynamic per-domain independence groups (§2.2) |
| **OpenRouter** — AI actions | `backend/app/llm/` (`openrouter.py`, `circuit_breaker.py` + `config/model_ladder.yaml`, `config/budget.yaml`) | All narratives flow through the budget-gated gateway: `select_model` walks the ladder FULL → STANDARD → MINIMAL(`:free`) → OFF; native fallback chains; actual usage cost settles as nanocents; KYC never degrades to free models. No key → deterministic templates (demo profile) |
| **Budget engine (Part E)** | `backend/app/core/budget.py` + `budget_tx` table | Nanocent accounting governs both OpenRouter tokens AND Firecrawl credits; failed calls settle at $0; attempts always logged; feeds analytics |
| **Analytics sheet & dashboard** | `backend/app/api/routes/admin.py` (`/admin/analytics/summary`, `/admin/analytics/export?format=csv|xlsx`, `/admin/budget`), `frontend/src/views/Analytics.tsx` | §4.1 `analytics_daily` view (checks, verdict mix, confidence, source-independence ratio, spend/day) → KPI cards, stacked verdict area, cost/volume scatter, independence-ratio line with 0.6 target; data-sheet export CSV (XLSX when `openpyxl` installed) |

### Cost posture of this demo

With no `FIRECRAWL_API_KEY`/`OPENROUTER_API_KEY` set the platform runs **$0.00**:
OSM/Leaflet are keyless, all AI narrative slots degrade to deterministic
templates with visible markers, and the budget ledger (`/api/v1/admin/budget`)
shows attempts at zero realized spend. Point the two keys at your providers
and the same paths come alive under the cap rules in `backend/config/budget.yaml`.

## Self-Hosted Geo Stack (spec §Self-Hosted Part 1) + E2E Demo (Part 2)

Public Nominatim/OSRM have fair-use limits and no SLA. The self-host path is
defined in **`docker-compose.geo.yml`** (Nominatim 4.4 + OSRM + optional
tileserver, with healthchecks and a one-shot `osrm-prep` data job):

```bash
# 1. Geo stack (one-time import, ~30–90 min depending on extract size)
docker compose -f docker-compose.geo.yml --profile prep run osrm-prep
docker compose -f docker-compose.geo.yml up -d nominatim osrm

# 2. Point the services at the local instances — zero code change (§1.3).
#    backend/config/settings.yaml `geo:` keys or env (env wins):
export GEO_NOMINATIM_URL=http://localhost:8080
export GEO_OSRM_URL=http://localhost:5000
#    → GeoService detects self-hosting and lifts the 1 req/s pause
#      (semaphore 1 → 20); UA header stays per OSM courtesy.

# 3. Free-tier keys (optional; everything degrades honestly without them)
export FIRECRAWL_API_KEY=fc-...
export OPENROUTER_API_KEY=sk-or-...

# 4. Verify end-to-end
python demo/e2e_free_stack_demo.py --offline
```

Definition of the switch: **public now** (fine until journey traffic >
~500 routes/day), **self-hosted before launch** — same classes, different URL.

### End-to-end free-stack demo — `demo/e2e_free_stack_demo.py`

One scenario wiring all four integrations through a single case:

`"The Governor announced construction of a new international airport in Lagos"`

| Stage | Service | Contribution visible in output |
|---|---|---|
| 1 | **Firecrawl** | Raw docs sourced per the §2.2 registry (`firecrawl_search`, dynamic domain groups); no key → source marked **stale with real age** and the pack's cached evidence stands (§2.4/§20) |
| 2 | **OpenRouter + inductive engine** | `MISLEADING / HIGH` — the single government release and 13 syndicated amplifications collapse into **2 independent of 14**; copy-chain analysis reports **2 text clusters, 13 articles tracing to one origin** (§1.6); 13 release-vs-announcement date conflicts (MODERATE) drive H4 |
| 3 | **Nominatim → OSRM → Leaflet** | Ikeja → Victoria Island at 18:30; live road geometry + true arrival clocks, or the honest `offline-fixture` corridor — hotspot: **Third Mainland Bridge approach @ 18:50** (hedged, §9) |
| 4 | **Budget engine** | Every metered attempt reserved→settled and attributed via `app.budget.context.current_case_id` (§2.1); `budget_tx_for_case` shows the full audit trail — $0.0000 realized in demo profile, non-zero with keys |
| 5 | **Analytics sheet** | The run lands in `demo_analytics.csv` (§4.2 Daily sheet) within seconds |

Reproduce the expected §2.2-style output offline (deterministic, no network):

```bash
python demo/e2e_free_stack_demo.py --offline \
    --db /tmp/e2e.db --out demo_analytics.csv
#   Verdict: MISLEADING · Confidence: HIGH · Sources: 2 independent of 14
#   Copy-chains detected: 2 clusters (largest chain = 13 articles …)
```

Failure-mode demonstrations (§2.4 — each dependency can fail without
corrupting conclusions):

```bash
python demo/e2e_free_stack_demo.py --offline --inject-fault osrm-down
#   → "Routing service unavailable — journey risk cannot be assessed
#      reliably." (UNDETERMINED; no timeline fabricated)
python demo/e2e_free_stack_demo.py --offline --inject-fault firecrawl-exhausted
#   → sources marked DEGRADED with staleness banner; the check still runs
#     on cached evidence
```

## Trust posture — [`TRUST.md`](TRUST.md)

Shipping discipline for agent-generated intelligence software: every
component is classified by **blast radius** (KYC/verdict logic = line-reviewed;
dashboard styling/docs = sampled), review lanes are **uncertainty-tiered**
(Part 18 D1: contradictions ≥2, copy-chain dominance, or confidence ≤
MODERATE always reach humans; high-confidence low-stakes auto-publish with a
5% audit sample), and source trust is **auto-scored** per ingest (§U1 health
scorecard — stale or echoing sources demote themselves and ping a curator).
The named next constraint is KYC reviewer capacity (4-hour SLA). A 4-week
production pilot with override tracking is the only accepted long-term
quality signal — test suites are necessary, not sufficient.

Admin visibility: `/api/v1/admin/review-queue` (tier lanes),
`/api/v1/admin/source-health` (+ `/refresh` to recompute).

## North star (spec §26)

> Facts separated from inference. Uncertainty stated honestly
> (UNVERIFIED ≠ FALSE). Provenance everywhere. Humans escalated when needed
> — the system admits what it doesn't know.

## Production hardening path

The demo profile intentionally swaps heavy infrastructure behind the spec's
repository/provider interfaces. `docker-compose.yml` restores the real stack:

- **Postgres + pgvector** for `VECTOR(1536)` semantic signal search (Part 4)
- **Neo4j** for the interactive evidence graph (Part 12)
- **Celery + Redis** for cron scraping beat (`scrape all every 15 min`,
  nightly retention maintenance, Part 4.2)
- **spaCy/sentence-transformers/Whisper** models behind `nlp_lite`'s
  interfaces (Part 3.1); **biometric providers** behind
  `MockBiometricProvider` (Part 5.2)
- TLS 1.3, WAF rate limits, Vault/KMS secrets, RBAC, audit log, GDPR erasure
  endpoints, alert rules (Parts 9, 14)
