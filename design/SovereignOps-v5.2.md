# Sovereign Ops Node v5.2 — Implementation Mapping (v3.3)

The v5.2 blueprint ("Tactical Swarm Edition") names a prototyper stack
(Next.js/Tailwind/ShadCN, Genkit/Gemini) and mocked capabilities. Per the
established convention for this repo, the blueprint is treated as the
**product/design single source of truth**; its capabilities are implemented
on the platform's production-shaped, zero-key architecture (React+Vite design
tokens, FastAPI native swarm). Nothing is faked: "mocked" prototyper calls
become real bounded implementations with honest degradation (§20).

| Blueprint v5.2 item | Implementation in v3.3 |
| --- | --- |
| §3.A Dark Tactical HUD palette (#020408 / #CFFF00 / #1A5454 / #DC2626) | `frontend/src/styles/tokens.css` v3.3 override — lime primary, teal secondary, crisis red; evidence semantics (FACT/EVIDENCE/INFERENCE) deliberately untouched |
| §3.A Space Grotesk / Inter / Mono | `index.html` Google Fonts + `--font-display`, headings/nav set in Space Grotesk |
| §3.B mobile-first fixed bottom-nav | `App.tsx` `.bottomnav` (≤900px, safe-area aware); desktop keeps top nav |
| §3.B "Sovereign Data Stream" (agent API calls + heartbeats) | `GET /api/v1/ops/stream` — persisted audit-trail rows blended with live volatile heartbeat pulses; each row labelled PERSISTED/LIVE so the durable source of truth is never ambiguous (§20). Ops Node "Data Stream" pane |
| §4 registry names/roles | Registry already models PATHFINDER (Brain), SENTINEL (Shield), HUNTER (Eye), AUDITOR (Gate); VOYAGER remains external interface per master spec §2 |
| §5 `/scan_cve` | SENTINEL `scan_cves` (v3.0 — fixture-fed, VPR-scored) |
| §5 `/mask_pii` | AUDITOR `mask_pii` (v3.2 — detects payment cards incl. 14–19-digit runs) |
| §5 `/id_audit_l1` | **NEW** VOYAGER `id_audit_l1` + `POST /api/v1/privacy/id-audit` — domain-integrity heuristics (TLD risk, est. age, registrar) + carrier probe (`sim_swap_probe`; UNKNOWN ≠ PASS, §20); verdicts PASS/REVIEW/FAIL with hedge + provenance + AI disclaimer; A-14-allowlisted to VOYAGER only |
| §5 `/decompose_goal` | PATHFINDER RGD (`backend/app/swarm/pathfinder.py`) |
| §6.A 4-step onboarding wizard | Ops Node wizard: (1) Sovereign/control, (2) swarm boundaries, (3) privacy & AUDITOR, (4) operator duty to verify |
| §6.B functional Crisis Override | v3.2 incident declaration (SEV1–3, webhook delivery honestly reported) — retained unchanged |
| §6.C Govern tab (privilege logs, delete sessions, Compliance Index) | "Govern" tab (`#/govern`, Settings view renamed). **NEW** `GET /api/v1/privacy/compliance-index`: 4 transparent components ×25 (consent-chain integrity, human gate, PII defense, ethics gate + disclaimer coverage) with per-component notes and an explicit "indicator, not certification" notice. Deletion + consent ledger retained from v3.1/v3.2 |
| §6.D permanent AI disclaimers | `AI_DISCLAIMER` on every synthesis and on `id_audit_l1` output; compliance component 4 measures disclaimer coverage |
| §7 RGD example (identity + leaks) | New `identity_intel` intent: HUNTER `footprint_scan` → VOYAGER `id_audit_l1` → AUDITOR `mask_pii` + `compliance_overlay`. Identifier-first entity extraction (`_identity_target`) avoids NER latching onto lead verbs. The v3.2 ethics gate still runs **before** any fan-out, so doxxing-flavoured goals refuse with a single AUDITOR task |

## Honest notes (§20)

- `id_audit_l1` uses bounded deterministic heuristics in the demo profile — a
  REVIEW/FAIL is an *indicator*, explicitly hedged ("not proof of abuse").
- Carrier integrity without a live carrier API reports UNKNOWN, which forces
  REVIEW — never a silent PASS. `TH360_SIM_FIXTURES` can feed bounded demo
  signals, exactly like the feed fixtures.
- The Compliance Index is computed only from local records and says nothing
  about the outside world; each component states what it measured.

Tests: `backend/tests/test_sovereign_ops.py` — 17 tests (141 passing total).
