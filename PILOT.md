# ThreatHunter360 — Production Pilot Runbook (v4.5)

This runbook takes a tenant from `git clone` to a **governed, measurable
pilot**: one real data source live, five §71 KPI families reporting, honest
boundaries stated. Everything here is aligned to the master spec
(v4.0 §71–§76) — where the platform cannot do something, this document says
so instead of implying it.

## 1. What a pilot IS

| In scope (working today, tested) | Stated boundaries (documented, NOT faked) |
|---|---|
| Investigation core + §63/§76 gates | SSO is documentation-only in the demo profile (no IdP) — RBAC is real, identity federation is not claimed |
| Five §71 KPI families + §72 north-star | KPIs whose write-paths don't exist report UNAVAILABLE with the gap named (see §5 below) |
| First REAL live source (crt.sh) via the §80 connector registry | All other live sources onboard the same way; none are pre-wired |
| Audit trail, hash-chain, SIEM NDJSON export (optional HMAC) | Scheduled cadence (beat) runs only when the celery worker/beat services are up |
| Approval engine + override instrumentation | Two-person production rule is a documented policy pattern (§37), not enforced defaults |

## 2. Bring the stack up

```bash
cp .env.example .env            # never commit real secrets
docker compose up -d api        # api + db + redis
curl -s localhost:8000/healthz
```

Frontend (Ops Node): `docker compose up -d dashboard` → http://localhost:5173.
Prometheus scraping for pilot ops: `GET /api/v1/ops/metrics`
(`th360_kpi_value`, `th360_kpi_sample`, `th360_kpi_available`; alert on
`th360_kpi_available == 0` — a KPI that's stopped being measurable).

## 3. Onboard the first live source (crt.sh) — the governed path

Live sources enter ONLY through the §80 registry: **admin registers →
governance approves → connector ACTIVE → fetches allowed.** No back door.

```bash
# 3.1 admin registers (demo key ships role=governance; use a role header
#     on the demo human path or a tenant admin key in production)
curl -X POST localhost:8000/api/v1/ops/connectors \
  -H 'content-type: application/json' -H 'X-TH360-Role: admin' \
  -d '{"name":"crtsh","kind":"C_data_api","base_url":"https://crt.sh"}'
# → { "id": "conn-…", "status": "PENDING_APPROVAL", "approval": {"id": …} }

# 3.2 governance approves (the durable effect flips it ACTIVE)
curl -X POST localhost:8000/api/v1/ops/approvals/<approval_id>/approve \
  -H 'content-type: application/json' -H 'X-TH360-Role: governance' \
  -d '{"decided_by":"pilot-governance"}'
```

`connector:crtsh` now appears in **GET /api/v1/feed/source-health** (§6/§32)
from day one. Its state is *earned by real outcomes*: after activation it is
`ACTIVE` (mounted, approved); the first failed live fetch flips it
`DEGRADED` with the classified cause (e.g. `SOURCE_UNREACHABLE`,
`SOURCE_TIMEOUT`) and a timestamp; the first successful observation restores
`ACTIVE` with the observed-name count in the note. A locked-down egress
environment therefore shows an honestly DEGRADED connector — never a fake
healthy one and never a fabricated observation.

## 4. Run the first governed observation

```bash
# 4.1 open a case (§63 authorization object) bound to the domain in scope
curl -X POST localhost:8000/api/v1/investigations -H 'content-type: application/json' \
  -H 'X-TH360-Role: analyst' \
  -d '{"objective":"Map public attack surface","subject_type":"domain",
       "subject":"example.com","purpose":"pilot","authority":"organization_owned",
       "scope":"passive CT only","expires_days":14}'

# 4.2 execute the PASSIVE observation against the living case
curl -X POST localhost:8000/api/v1/osint/live/crtsh \
  -H 'content-type: application/json' -H 'X-TH360-Role: analyst' \
  -d '{"investigation_id":"<inv_id>","domain":"example.com"}'

# 4.3 (v4.7) second source, same governed path — register+approve once more,
#     then: POST /api/v1/osint/live/rdap with the same body. RDAP answers
#     from the registry of record; HTTP 404 ("unregistered") is stored as a
#     HONEST observation — when the name registers later, the content hash
#     changes, the new row supersedes, and event:ObservationChanged fires
#     (§67 change detection across BOTH sources; watch the
#     observation_changes KPI).
```

Gate order (each failure is classified, §20): **§76 living-case → §63 scope
binding (queried domain must be the case subject or in its subdomain cone) →
ACTIVE on-allowlist connector → fetch.** Success stores one provenance-
stamped evidence row (content-hash idempotent — re-running never duplicates)
and emits `event:SourceQueried` + `event:ObservationReceived` (§26).

## 5. Watch the right KPIs

`GET /api/v1/ops/kpis` → `v71` block (or standalone
`GET /api/v1/ops/kpis/v71`, or the Ops Node **KPIs** pane).

Pilot success thresholds (recommended):

| KPI | Watch for | Trip wire |
|---|---|---|
| §72 north-star | rising count of evidence-backed closed cases | any CLOSED case with 0 linked evidence |
| governance.policy_decisions | REQUIRE_HUMAN share not collapsing | REQUIRE_HUMAN = 0 for days (gate bypass?) |
| governance.override_exceptions | low, explained | any override without written basis |
| governance.evidence_completeness | always 1.0 | 0.0 = halt pilot, hash chain broken |
| governance.reconstruction_time | stable ms | >5s growth = retention/archival time |
| governance.approvals_pending_over_72h | 0 | governance is the bottleneck |
| intelligence_quality.freshness | hours since newest evidence | staleness beyond your SLA (24h sweeps) |

**UNAVAILABLE KPIs**: as of v4.6 every spec-named §71 metric has a real
write-path. UNAVAILABLE now means exactly one thing: *nobody has decided
anything in the window yet* (empty denominator is undefined, never 0). The
basis string names the write-path that's awaiting use
(`/ops/review/{id}/decide`, `/ops/notifications/{id}/adjudicate`,
`/ops/watches/{id}/reroute`). Alert hygiene for pilots: adjudicate every
alert, answer every reroute — or accept that the KPI stays honestly blank.

## 6. Smoke checklist (run after every deploy)

```bash
python3 -m pytest tests -q                 # 297 green at tag v4.5
curl -s localhost:8000/ | jq .version      # 4.5.0 PILOT READINESS
curl -s localhost:8000/api/v1/ops/kpis/v71 | jq .north_star.status   # OK
curl -s localhost:8000/api/v1/ops/metrics | head -5                  # exposition text
```

## 7. Rollback

`git revert` the v4.5 commit; all v4.5 data lives in additive columns/tables
only — no migration, no destructive change. The SIEM export, KPI engine and
live-source routes are guarded by RBAC and fail closed.
