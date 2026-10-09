# ThreatHunter360 — Five Scripted Demo Scenarios (spec Part 10.6)

Run backend: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (auto-seeds on
first boot). API docs: http://localhost:8000/docs

---

## 1. FACT CHECK — copy-chain trap (§1.6)

```bash
curl -s -X POST http://localhost:8000/api/v1/factcheck \
  -H 'Content-Type: application/json' \
  -d '{"claim": "Company X was sanctioned in August 2026"}'
```

**Expected:** `MOSTLY_TRUE`, confidence `HIGH`,
`sources_independent` < `sources_total` (wire_a + wire_b count as ONE —
copy-chain detected), contradiction flagged (subsidiary vs holding entity,
14 vs 17 August date conflict).

## 2. FACT CHECK — unverifiable claim (§1.9)

```bash
curl -s -X POST http://localhost:8000/api/v1/factcheck \
  -H 'Content-Type: application/json' \
  -d '{"claim": "A celebrity secretly married in Lagos last week"}'
```

**Expected:** `UNVERIFIED` / `UNDETERMINED` with honest "no reliable source
found" messaging — **never** a fabricate FALSE verdict.

## 3. JOURNEY — night vs day comparison (§7)

```bash
curl -s -X POST http://localhost:8000/api/v1/journey/assess \
  -H 'Content-Type: application/json' \
  -d '{"origin": "Lagos", "destination": "Ibadan", "departure_time": "2026-08-24T21:00:00Z"}'

curl -s -X POST http://localhost:8000/api/v1/journey/assess \
  -H 'Content-Type: application/json' \
  -d '{"origin": "Lagos", "destination": "Ibadan", "departure_time": "2026-08-24T07:00:00Z"}'
```

**Expected:** night route shows HIGH at "Lagos-Ibadan Expressway km 42";
day route LOW/MODERATE there. Every segment explains *why* (§7).
Omit `departure_time` to see §14-15 conversational clarification.

## 4. KYC — anomaly, not fraud (§12)

```bash
curl -s http://localhost:8000/api/v1/kyc/fixtures | jq '.fixtures[1]'  # kyc-fix-002
curl -s -X POST http://localhost:8000/api/v1/kyc/verify \
  -H 'Content-Type: application/json' \
  -d '<fixture payload from above>'
```

**Expected:** `VERIFIED_WITH_ADDITIONAL_REVIEW` — a date inconsistency is an
anomaly, never an automatic denial. Case lands in `/api/v1/kyc/queue` (§27).

## 5. LIVE UPDATE — continuous reassessment (§1.10)

```bash
python seed/seed_script.py --confirm   # ingest official gazette confirmation
curl -s -X POST http://localhost:8000/api/v1/factcheck/<check_id_from_scenario_1>/reassess
```

**Expected:** same claim now returns `VERIFIED` / `VERY_HIGH` — the PRIMARY
official source resolves the secondary-source conflict.
