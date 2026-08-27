# Safety-by-Design Response — v3.2 tranche
*Input: "ThreatHunter360 UX & Safety-by-Design Review" (verdict: Do not
ship, 10/20, blockers E & G). This document maps every finding to what was
built. Review referenced UI names from a design mock ("Swarm/Fleet tabs",
"Crisis Override toggle", "Ethical AI Guardian") — implementation landed on
the actual v3 architecture (Ops Node, PATHFINDER, AUDITOR).*

## Blockers (both closed)

### E — User Control & Exit Ramps (was 0/2)
| Requirement | Shipped |
|---|---|
| Halt Execution | `POST /ops/tree/{id}/halt` → cooperative drain: unstarted tasks marked `HALTED`/`HALTED_BY_USER`, in-flight disclosed as "may complete — no false rollback claims". OpsNode strategy map shows a prominent **■ Halt Execution** button whenever non-final work exists. |
| Delete reports | `DELETE /ops/tree/{id}` removes tree+tasks+report, deletion itself audited. Per-tree 🗑 in the Timeline pane (with confirm). |
| Delete session/personal data | `DELETE /data/user/{user_id}` (prefs+watchlists+watches), `POST /cortex/session/{id}/purge` (chat context now, not at TTL). Settings → "Data & sessions" card with explicit scope + what stays (consent ledger = audit proof) and why. |

### G — Escalation & Crisis Pathways (was 0/2)
| Requirement | Shipped |
|---|---|
| Functional override | `POST /ops/incident/declare` (SEV1–3 + summary) → incident record + AUDITOR trail + notification center + real webhook delivery attempt (`TH360_INCIDENT_WEBHOOK`). Delivery state reported honestly: `delivered` / `unreachable` / `not_configured` — a cosmetic button is worse than none. |
| Crisis UX | OpsNode modal "Incident Declaration" (severity, summary, Declare & notify); ACTIVE incident renders a **calm banner + response checklist** (simplified, reduced emphasis — risk #10: no red screens, no feed acceleration). Resolve endpoint + button. |

## Checklist items (A–J)

| Item | Score→ | What changed |
|---|---|---|
| A Purpose clarity | 1→2 | Agent roster tooltips everywhere (strategy map agent chips carry role descriptions); demo goal renamed "⚡ Demo: security sweep (plan first)". |
| B Trust calibration | 1→2 | First-run **"AI Partnership"** banner (purpose + "not an oracle — verify before acting", must acknowledge; persists via localStorage). Footer limitation line. |
| C Privacy communication | 1→2 | Settings → Privacy card explains masking mechanics + retention in plain language; consent ledger shown with live chain-integrity badge. |
| D Choice & autonomy | 1→2 | **Plan Review gate**: `/ops/plan` decomposes without executing → OpsNode review card (task list, ethics flag, cost warning) → `Approve & Execute` / `Cancel`. Cortex dialogue path documented as progressive-consent. |
| E Exit ramps | 0→2 | see blockers. |
| F Non-advice | 1→2 | Every UnifiedReport carries `disclaimer` — "AI-generated output — verify all findings and recommendations with your team's protocols before taking action." Rendered as bordered notice atop every report. SENTINEL outputs stay "tickets await human sign-off". |
| G Crisis | 0→2 | see blockers. |
| H Persona cues | 1→2 | Buttons read "Approve & Execute" / "Review & Approve Plan", halt is sober gray; crisis mode *simplifies* (checklist only). |
| I Inclusion | 1→2 | **AUDITOR `sensitive_target_check`** pre-decomposition: person + intrusive intent ("home address of…", "dox", "track", family/religion/affiliation terms) → goal REFUSED with refocus guidance, zero fan-out, safety-logged. Jailbreak phrasing → REFUSED ("Operation halted" on trail). |
| J Measurement | 1→2 | Safety events (`halt_requested`, `plan_approved/rejected`, `incident_declared`, `ethics_flag`, `pii_masked`, `tree_deleted`, `user_data_deleted`, `session_purged`) on the audit trail; `/ops/kpis` exposes `safety_events`; KPI pane shows the learning loop. |

## Top-10 risks → status
1. **Weaponized OSINT** → ethics gate (REFUSED + logged) ✅
2. **Flawed remediation** → patching was never executable; outputs framed "verify before acting"; remediation scripts land in the human queue ✅
3. **False crisis security** → functional declaration pathway ✅
4. **Unstoppable swarm** → cooperative halt + HALTED visibility ✅
5. **PII via missed pattern** → card pattern added; masking output discloses coverage + "not a guarantee"; report disclaimer ✅
6. **Skill atrophy** → partial: disclaimers + interactive strategy map (raw I/O). "Training scenarios" deferred (needs scenario pack design).
7. **Compliance metric misread** → n/a in our build (no such composite metric shipped); Sovereign KPIs are explicitly scoped with a note.
8. **Black-box decisions** → agent role tooltips + per-task raw result `<details>` in the strategy map ✅
9. **No data sovereignty** → tree/report deletion + user data deletion ✅
10. **Crisis overload** → banner is calm/checklist-first; reduced-motion honored globally ✅

## Red-team plan → executable suite
`backend/tests/test_safety_by_design.py` (18 tests) encodes the plan:
#2 doxer → REFUSED, AUDITOR-only fan-out · #4 fleet-wide → cost warning ·
#5 card PII → `[payment-card]` · #6 halt → HALTED_BY_USER states ·
#7 crisis → record+notify+checklist+honest delivery · #8 skeptic → tooltips +
raw task I/O · #11 jailbreak → REFUSED + ethics_flag on trail ·
#12 delete-my-data → artifacts gone, ledger intact, scope disclosed.
#1 (over-trusting junior) & #10 (curious learner) are content-design items —
deferred to the docs/wiki tranche (linked-metadata work, not enforcement).
#3 (panicked user) & #9 (EU-region handling) noted for the next tranche:
cortex crisis-keyword detection; region-aware consent defaults.

## Verification
124/124 tests · tsc clean · vite build ✓ · live red-team sweep: plan-gate,
halt, REFUSED×2, declare/active/resolve, ethics_flag KPI all verified by curl.
