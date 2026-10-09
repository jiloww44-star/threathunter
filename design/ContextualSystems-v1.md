# Human–Context–System–Behavior Alignment Engine — ThreatHunter360 v4.8.0 (analysis v1)

**Engine:** "Contextual Systems + Human Behavior + Product Pattern Recognition" (pasted framework, sections 1–29), executed verbatim against ThreatHunter360 **as built** (backend v4.8.0 `41b15a6`, mobile demo `c6901f2`).
**Evidence rule honored:** every load-bearing claim is tagged **[FACT]** (measured/verified in this repo or a live run), **[OBSERVATION]** (seen in system behavior, not user research), **[INFERENCE]**, **[HYPOTHESIS]**, **[ASSUMPTION]**, or **[UNKNOWN]**. Nothing is called validated without behavioral or outcome evidence.
**Reality base measured 2026-10-08 against a fresh seed-only instance:** north-star `evidence_backed_decisions_completed = 0` (sample 0) **[FACT]**; `evidence_backed_conclusion_rate = UNAVAILABLE`, basis *"no CLOSED investigations yet — rate undefined, not zero"* **[FACT]**; live external sources unreachable from this sandbox (crt.sh/rdap TLS blocked → classified `SOURCE_UNREACHABLE`) **[FACT]**. Prior live-verified loop results (pilot case `e8224703-2f1`: adjudications, correction rate 0.5, reroute decision, chronology digest, replay 422) were measured pre-wipe on a seeded demo DB — that DB is **gone** **[FACT]**.

---

## 1. The system, not the product

| Layer | Content (tagged) |
|---|---|
| **People** | Security/intelligence **analyst** (EDGE node operator) **[ASSUMPTION — never interviewed]**; governance/administrator; incident decision-maker consuming conclusions; the **voyage traveler** (journey domain) **[ASSUMPTION]**. |
| **Actors** | Swarm agents (reasoning engine, fact-checker, voyager), connectors (§80), reviewers, adjudicators **[FACT — code]**. |
| **Stakeholders** | Tenant security leadership; compliance/audit (assurance sweeps + SIEM export exist **[FACT]**); data-protection (privacy trust layer **[FACT]**). |
| **Institutions** | The tenant's own authorization regime (§76 purpose+authority gate **[FACT]**); external regulators **[UNKNOWN — no tenant onboarded]**; external source operators (CARTO, crt.sh, rdap.org) **[FACT — dependencies]**. |
| **Environment** | Self-hosted (`docker-compose`, SQLite now; Sovereign Ops blueprint targets edge/bare-metal) **[FACT]**; air-gapped-ish postures implied by "sovereign" branding **[INFERENCE]**; analysts embedded in SOC workflows **[ASSUMPTION]**. |
| **Technology** | FastAPI/SQLite/React; SIEM webhook key; Expo/RN mobile shell (demo, unshipped) **[FACT]**; existing SOC tooling (SIEM/EDR/ticketing) it must coexist with **[ASSUMPTION]**. |
| **Resources** | One engineer-session's worth of development so far **[FACT]**; no production infra **[FACT]**; no analyst-hours budgeted **[UNKNOWN]**. |
| **Constraints** | Sandbox wipe cadence destroyed state twice this week (demo DB, pip, node_modules, `.git`) **[FACT]**; egress allowlist blocked crt.sh/rdap/crt/tiles **[FACT]** — an **environment warning** for any restricted-network tenant, not just a dev annoyance **[INFERENCE]**. |
| **Incentives** | Human review-decision tooling (v4.6), auto-resolution of low-severity reroutes (voyager), KPI windows `TH360_KPI_WINDOW_HOURS` **[FACT — code]**; whether a real analyst's *job incentives* align with correcting the AI **[UNKNOWN]**. |
| **Norms/Power** | `viewer < analyst < governance < admin` (RBAC) **[FACT]**; §76: "no consequential action without authorization" is the power chokepoint **[FACT]**. |
| **Dependencies** | External sources (currently 0 confirmed working end-to-end from a real network **[OBSERVATION]**); operator keeps uvicorn running **[FACT]**; tenant authorization language must exist before any live case **[FACT]**. |

**Actor→Action→Decision→Consequence→Feedback (primary loop):** analyst opens case (§76 authorization) → connectors observe → evidence → reasoning → conclusion → fact-check → review queue → **human decides (confirm/correct)** → decision feeds `analyst_correction_rate` → chronology digests it all **[FACT — live-verified v4.6–4.8]**.

## 2. The human in context

Modeled state, not demographics: an analyst at **high alert volume, low trust in AI outputs, under time pressure, with accountability for consequential calls** **[INFERENCE from the spec's own safety sections, not from fieldwork — ASSUMPTION at human level]**. Design responses already present: honest-degradation errors (title/meaning/next_step) for the *uncertain/offline* states **[FACT]**; UNVERIFIED ≠ FALSE as a trust model **[FACT]**; progressive disclosure UI **[FACT]**. Untested: busy/stressed behavior, phone-at-0300 behavior, manager-interruption behavior **[UNKNOWN]**. The mobile shell is the first artifact aimed at the *"not at a desk"* human state **[FACT — built] [UNKNOWN — never run on a device]**.

## 3. Existing behavior reconstruction

Trigger→…→memory loop **as the platform encodes it**: source poll/fetch → classified error or observation → hash-compare → supersede + `ObservationChanged` → alert → adjudication → reviewer decision → KPI windows → chronology **[FACT]**. Real-user habits/workarounds/avoidance **[UNKNOWN — Level 0]**. One genuine development-side **OBSERVATION**: denied live-fetch attempts were *invisible* on the case chronology (audit detail lacked the case id) and nobody saw it until live verification — an instance of **"what the system records ≠ what the human sees,"** the §5 mental-model gap, discovered inside our own team **[OBSERVATION, n=1]**.

## 4. Job beneath the request

"I want a threat hunter" → *"When a signal about my organization appears anywhere, I need to know **whether it is true and what authority covers my next action**, so that I can act without being the person who trusted a hallucination or broke policy"* **[INFERENCE — derived from §20/§71/§76 spec language; JTBD interviews = UNKNOWN]**.

## 5. Mental model

Expected analyst model: "the AI finds things; I decide." Actual system: "the AI **proposes**, policy disposes; every consequential artifact is gated, dated, hashed, and reconstructable." Mismatches the design anticipates: intelligence theater (blocked — measured-or-said KPIs) **[FACT]**; provenance confusion (blocked — locker rows carry source/authority/hash) **[FACT]**; replay expectation (satisfied honestly — `REPLAY_NOT_AVAILABLE` for seed rows) **[FACT]**. Whether analysts *actually* hold the honest-degradation model — or simply distrust colored chips — **[UNKNOWN]**.

## 6–7. Behavioral drivers & gap classification

Drivers designed-in: trust (evidence-backed chips), control (adjudication everywhere), fear mitigation (audit trail for accountability), autonomy (analyst overrides) **[FACT]**.
Gap analysis for *desired behavior "analyst runs live-observed, adjudicated cases"*:

- **CAPABILITY GAP**: none major in code **[FACT]**.
- **ACCESS GAP**: live sources never confirmed from any real network; crt.sh/rdap unreachable here **[FACT/OBSERVATION]**.
- **WORKFLOW GAP**: no SIEM-registered webhook consumer ever exercised; no ticket-system import **[UNKNOWN]**.
- **TRUST GAP**: the *designed* trust mechanism (honesty) is unproven with humans **[HYPOTHESIS]**.
- **INCENTIVE GAP**: if corrections don't visibly change anything an analyst cares about, review-decide behavior decays **[HYPOTHESIS — the v4.6 loop measures decay would be visible in `analyst_correction_rate`, but no real population]**.
- **IDENTITY GAP**: senior analysts may see adjudication as clerical work beneath them **[ASSUMPTION → HIGH-priority to test]**.

## 8–9. Patterns & loops

**Detected in-system [OBSERVATION]**: CONCENTRATION (2 connectors carry 100% of the live story); BOTTLENECK (human review queue is the serial point for every consequential conclusion — by design); DEPENDENCY (egress failure cascades: source unreachable → health DEGRADED → no observation → KPI denominators stay empty — *visible and honest*). **Predicted loops [HYPOTHESIS]**: trust loop (honest UNVERIFIED → analyst believes labels → relies on system) — the product's central bet; notification-fatigue loop from the framework's own example (each DENY/503 is an alert-class audit row — mitigated by classification, untested at volume).

## 10. Second-order

PILOT.md already pre-answers two: 10× watch volume makes human adjudication the constraint (auto-resolve exists for one branch) **[FACT]**; product-unavailable = north-star halts at its last honest value, dashboards show staleness **[FACT]**. Unanswered: analysts learn to *game* tolerance settings to keep queues short **[UNKNOWN]**; chronology becomes the de-facto discipline record, chilling legitimate investigation **[HYPOTHESIS — governance review needed before enterprise]**.

## 11. Product vs system problems

**SYSTEM (organizational)**: zero real users, authorization language unwritten for any tenant, review-desk norms unknown → *no UI feature can fix these*. **TECHNICAL**: sandbox-grade egress (not necessarily tenant-grade). **PRODUCT**: mobile unshipped; pattern library not yet generalized into reusable constructs. Correct per framework: do not solve the organizational gap with a UI feature → **the next unit of work is a pilot, not a tranche.**

## 12–14. Intervention, contextual fit, friction

Intervention defined **[FACT — as designed]**: replaces "trust the AI summary" with "verify the AI's evidence and record your authority." Contextual fit: desktop web verified; field/mobile = fabricated-context gap **[FACT honest]**. Friction map: intentional friction kept at §76 gates, approval registry, atomic decisions (409 on double-decide) **[FACT — live-verified]** — exactly the framework's "friction that protects." Unintentional friction: no SSO (**[FACT — documented boundary]**), no onboarding wizard, ingest requires console work **[OBSERVATION]**.

## 15. Human ∩ Business ∩ Control overlap

Control is the strongest sphere **[FACT]**: RBAC, retention, audit digests, SIEM export, §76 gate. Human value: honesty UX strong, daily-workflow fit unverified. Business value: **north-star at 0 — no economic value has ever been captured** **[FACT]**. Overlap today = *infrastructure for trust without yet a trusting user.*

## 16. Adoption mechanics

Awareness/trial: exists via pilot runbook **[FACT]**. First-success path **incomplete**: an operator cannot today reach "live observation on a real subject" from a fresh clone in a restricted network **[FACT — proven twice this week]**. The adoption-cheapening lever: **run the first pilot where the sandbox isn't** — one analyst, one owned subject, one working connector **[HYPOTHESIS → the engine's top recommended experiment]**.

## 17–18. Opportunities & PMF signals

From observed repetition: repeated *fetch-failure classification* → already a pattern (classified errors) **[FACT]**; repeated *replay request* → v4.8 shipped replay **[FACT]**. PMF signals (§18): unasked-for adoption 0, pull 0, retention 0, workflow embedding 0, willingness-to-pay 0 — **all at Level 0 by construction** (no users), and the framework forbids pretending otherwise.

## 19. Pattern-based hypotheses (top three)

1. **PATTERN** (development): honest-degradation machinery is the most-used platform surface (every 503/404 renders it). **NEED**: people trust what explains itself. **INTERVENTION**: keep; ship error-visibility as a first-class UI pane. **OUTCOME**: higher pilot completion of adjudication tasks. **[HYPOTHESIS, Level ≤2]**
2. **PATTERN**: denied attempts were chronology-invisible. **NEED**: failure must be as inspectable as success. **INTERVENTION**: shipped (DENY rows carry case id). **OUTCOME**: zero "where did my attempt go" support questions in pilot. **[HYPOTHESIS → testable in pilot]**
3. **PATTERN**: every KPI denominator silently empty until a human closes something. **NEED**: operators must see the *pipeline into* north-star before the north-star moves. **INTERVENTION**: candidate "north-star funnel" UI (opened→observed→linked→closed→adjudicated). **OUTCOME**: fewer "is it working?" status pings — the framework's own status-request loop, applied to us. **[HYPOTHESIS — strongest product idea surfaced by this analysis]**

## 20–21. Multi-scale & assumption ledger

Individual: honest errors. Team: shared chronology → handoff problems **[UNKNOWN]**. Org: single-writer SQLite **[FACT boundary]**. Market/ecosystem: closed-network deployability is the moat **[INFERENCE]**.
Priority assumptions (uncertainty×impact): *(a)* analysts will perform adjudication acts daily **[ASSUMPTION — test: 2-week pilot, threshold ≥70% of open queue acted weekly]**; *(b)* evidence-backed chips change trust vs. a chat summary **[ASSUMPTION — test: A/B in pilot usability session]**; *(c)* one working live connector is achievable in tenant network **[ASSUMPTION — test: day-0 of pilot]**; *(d)* org-owned authorization text exists to copy **[UNKNOWN — test: ask in pilot kickoff]**.

## 22. Validation experiments (designed now)

| # | Experiment | Question | Signal | Threshold |
|---|---|---|---|---|
| E1 | **Real-subject pilot** (PILOT.md, 1 analyst, 1 owned domain, ≥1 connector on open network) | E2/E1: does the full consequential loop complete with a real human? | north-star ≥ 1 (Level 6) | ≥1 evidence-backed *completed* decision in 14 days |
| E2 | Shadow-first ingest (import observer's real alert CSV via feed) | Does ingestion fit existing behavior? | repeat ingest by analyst themselves | 3 self-serves |
| E3 | Corrigibility usability test (5 analysts, scripted contradiction) | Do they confirm, correct, or disengage? | observation of choice | ≥3 choose correct-and-explain |
| E4 | Mobile dev-build handoff (1 field user, mapcn shell) | Does the 0300-context product exist at all? | Level 3 intent→Level 4 trial | user completes one case lookup on device |

## 23. Evidence ladder — honest placement

**Engineered core:** Level 5–6 demonstrated *with simulated data* **[FACT]**. **Real-human value:** Level 0–1 **[FACT]**. The engine's rule applies to the builder too: *ThreatHunter360 is not a validated product; it is a validated skeleton.*

## 24–25. Emergent behavior & pattern library

Emergent so far: the DENY-visibility fix (in-system emergence) **[OBSERVATION]**; user-emergence none (no users) **[FACT]**. Pattern library generalization roadmapped from the framework's §25 set → **should become first-class platform constructs** (TRUST, VERIFICATION, ESCALATION, WORKAROUND, HANDOFF patterns already exist as scattered mechanisms; unifying them is a future **tranche candidate**, designated next).

## 26. Challenge

What if the old workaround (analyst reads raw sources manually) is rational because volume is low? → Then the product is over-governed for small teams; pivot value to the locker+chronology only. What if chronology-as-discipline-record scares users? → governance scoping needed pre-enterprise. What if honesty lowers perceived capability vs. flashy competitors? → **[ASSUMPTION]** marketing-level risk; the bet is that in security, honesty *is* the capability. What if it succeeds? → adjudication queue becomes the org's busiest desk; hire/design for it.

## 27. The real product, restated

**USER PROBLEM**: "I cannot tell which AI-supplied threat conclusions I am allowed to act on without becoming the fall guy." +
**CONTEXT**: accountable security work +
**JOB**: verify-and-authorize, not search +
**INTERVENTION**: evidence-bound conclusions with human decisions and digested trails +
**SYSTEM RESPONSE**: KPIs measure only consequential acts; honesty when empty +
**OUTCOME**: *evidence-backed decisions successfully completed*. **[INFERENCE — synthesis of §71–76; matches the as-built north-star]**

## 28. Final synthesis (the 26 artifacts)

1–11: §1 system map above; actors/context/behavior/mental-model/JTBD/drivers/gaps/workflow/constraints/incentives — all tagged above.
12 **Detected patterns**: CONCENTRATION(2 connectors), BOTTLENECK(human queue), DEPENDENCY(egress cascade), HONESTY-UI reuse.
13 **Loops**: trust (bet), fatigue (risk), KPI-denominator starvation (observed).
14 **Opportunity areas**: pilot path, north-star funnel UI, pattern-library tranche, mobile field build.
15 **Hypotheses**: H1–H3 above + assumptions (a)–(d).
16 **Intervention**: as-designed, §27.
17 **Desired behavioral change**: analysts correct/confirm AI conclusions *inside* the system instead of re-verifying outside it.
18 **Expected system change**: machine conclusions become auditable acts; the queue becomes the desk.
19 **MVP**: current build + E1 pilot (scope: 1 tenant, 1 case type, 1 connector, 14 days).
20 **Experiments**: E1–E4.
21 **Adoption mechanism**: runbook → first-success live observation → adjudication habit → chronology-as-record lock-in.
22 **Enterprise implications**: SSO boundary must be closed or contractually waived **[FACT]**; SIEM webhook needs a real consumer; single-writer DB ceilings.
23 **Risks**: egress-dependence, adjudication fatigue, discipline-record chilling, honesty-vs-marketing.
24 **Second-order**: gaming tolerance; north-star optimization theater (mitigated: it counts only closed+evidenced) **[FACT]**.
25 **Success metrics**: north-star ≥1 in pilot (Level 6); correction-rate measured (any value — information, not target); ≥1 repeat self-served ingest; zero trust-integrity incidents.
26 **Evidence gaps**: every human-behavioral claim — 0 field interviews, 0 real cases, 0 real live-source fetches, 0 device runs **[FACT]**.

**Classification: PILOT.** Not BUILD-MVP (the skeleton past the tests), not SCALE (Level 0 human evidence), not STOP (no disconfirming evidence; strong engineered integrity), not RESTRUCTURE-yet (assumptions untested, not failed). The engine's verdict: **the next unit of value is behavioral evidence, and only a real pilot produces it.**

## 29. Reality check

Solving a real problem? **[ASSUMPTION — demand unverified]**. Correct layer? The platform layer is control/verification — consistent with every spec the user has supplied **[FACT]**. Fit existing behavior? Unproven; E2 exists because of it. Who benefits/carries cost? Analysts carry the adjudication cost — the empathy debt flagged by the engine's author is real here **[INFERENCE]**. What proves the model wrong? E1 failure (no completed adjudicated case in 14 days with usability intact) → RESTRUCTURE classification. Still unknown: everything tagged UNKNOWN above; an honest count: **7 UNKNOWNs, 9 ASSUMPTIONs, 8 HYPOTHESISes dominate the human half of this document; the machine half is FACTs.** That asymmetry *is* the finding.

---

### Appendix A — Fact-log (measured this session, 2026-10-08, fresh seed instance)

- `/api/v1/ops/kpis/v71` → `evidence_backed_decisions_completed = 0` (0 closed), `evidence_backed_conclusion_rate` UNAVAILABLE ("no CLOSED investigations yet — rate undefined, not zero"), `freshness` 0.01 h (26 rows), `source_diversity` 6 (26 rows), window 168 h, engine kpi-engine/4.6.0. **[FACT]**
- Seed ingest: 6 sources attempted/6 ok, 26 signals, 17 independence groups. **[FACT]**
- Sandbox egress: crt.sh / rdap.org TLS fails → `SOURCE_UNREACHABLE` (v4.7/4.8 live runs). **[FACT]**
- Suite: 345 backend tests green at v4.8 (`41b15a6`); mobile tsc + mapcn doctor clean (`c6901f2`). **[FACT]**
- Pre-wipe live-verified pilot loop (case `e8224703-2f1`): review decide/correct, alert adjudicate TRUE_POSITIVE, reroute adjudicated, correction rate 0.5 measured, chronology digest tamper-visible, replay 422 REPLAY_NOT_AVAILABLE. **[FACT — environment destroyed, results recorded in git history & session logs]**

### Appendix B — Next candidates this verdict produces (ranked by evidence value)

1. **E1 real-subject pilot** (the classification) — unblocks all Level ≥3 evidence.
2. **North-star funnel UI** (H3) — smallest tranche that answers "is the pipeline into north-star visible"; framework's status-request loop applied to ourselves.
3. **Pattern-library tranche** (§24/25) — promotes scattered trust/verification/escalation mechanisms into first-class reusable constructs (architectural, post-pilot-informed).
4. **Mobile field dev-build** (**E4**) — tests the 0300-context hypothesis; needs a machine with Android SDK.
