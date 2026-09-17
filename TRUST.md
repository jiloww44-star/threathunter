# TRUST.md — ThreatHunter360 Review Posture & Pipeline Governance

*Implements the posture-audit and bottleneck-mapping disciplines adopted for
this project (the "Willison framework" review): every deliverable declares its
blast radius and review level, and throughput is designed around the next
concrete constraint — never abstract "process risk".*

---

## 1. Blast-Radius Classification

| Component | Blast radius | Review posture |
|---|---|---|
| KYC biometric/identity module (Part 5) | **HIGH** — identity, legal exposure, fraud decisions | **Agentic engineering MANDATORY.** Every consistency/decision rule line-reviewed; no vibe coding tolerated. |
| Fact-check verdicts (Parts 1–3) | **HIGH** — users act on conclusions | Agentic engineering. Hedged-language and honesty guarantees are load-bearing; confidence scoring, hedge enforcement, contradiction detection receive **manual line review** (their failure mode is confident wrongness). |
| Journey risk advisories (Part 6) | MEDIUM-HIGH — physical-safety implications | Agentic engineering with explicit degradation rules (circuit breaker → UNDETERMINED, never a fabricated timeline). |
| Budget engine / cost attribution (Parts A–E) | MEDIUM — financial accuracy for billing | Integer nanocent math reviewed by hand; UI around it is lighter. |
| Analytics dashboards & exports | LOW-MEDIUM — decision support | Middle of spectrum: wrong numbers mislead but rarely harm. |
| Demo pack, docs, onboarding copy (Parts 10, 14–16) | LOW | Legitimate vibe-coding territory. |
| **v3.0** SENTINEL remediation (patch/ticket path) | **HIGH** — infra-changing potential | Agentic engineering MANDATORY. `apply_patch` is policy-gated REQUIRE_HUMAN by AUDITOR; auto-execution is architecturally absent (test-enforced: `request_patch` parks AWAITING_HUMAN). |
| **v3.0** AUDITOR gating + screening (A-06) | **HIGH** — governance root of trust | Manual line review per release. Every decision persisted to an immutable trail; unknown actions default to REQUIRE_HUMAN (fail-closed). |
| **v3.0** PATHFINDER RGD + mesh failover (A-02/§3.3) | MEDIUM-HIGH — coordination correctness | Task states and failover resume covered by the suite; decomposition templates are deterministic keyword rules (no LLM-in-the-loop). |
| **v3.0** Conversational Cortex (§3.1) | MEDIUM — interpretation layer | Clarifies instead of guessing; context TTL 1h (§25); cortex replies always trace to a task tree. |
| **v3.0** Custom Agent SDK (A-13/§5.2) | **HIGH** — third-party code path | SHADOW admission by default (read-only); external-effect functions rejected at validation; human promotion is a REQUIRE_HUMAN audited action. |

### Posture statement (audience-ready)

> *"ThreatHunter360's intelligence modules were agent-generated per a detailed
> specification. The confidence-scoring, hedge-enforcement, and KYC decision
> paths received manual line review because their failure mode is confidently
> wrong output affecting safety and identity decisions. All other components
> were validated by the test suite and will be validated by a minimum 4-week
> production pilot with human-analyst override tracking before general
> availability. No component ships on trust in generation quality alone."*

### Known gaps closed / still open

- ✅ **Gap 1 (hedging under-reviewed):** the three confidently-wrong-capable
  components are named above and get manual line review per release.
- ⚠️ **Gap 2 (zero production usage):** the test suite is necessary, not
  sufficient. Usage-in-production is the only accepted long-term quality
  signal — the pilot protocol below is a launch-gate requirement (§14.5).
- ✅ **Gap 3 (over-review in reverse):** LOW blast-radius surfaces (dashboard
  styling, docs, demo scripts) are explicitly audit-sampled, not line-reviewed.

---

## 2. Throughput-Bottleneck Map (adopted redesigns)

Automated claim analysis yields ~100× faster **draft** conclusions; finished
conclusions were redesign-matched so human attention scales with **doubt**,
not **volume**:

### D1 — Tiered review routing (implemented: `app/core/review_routing.py`)

| Rule | Lane |
|---|---|
| ≥2 active contradictions | **MANDATORY_REVIEW** (always) |
| Copy-chain dominance (≥60% syndicated copies, ≥3 signals) | **MANDATORY_REVIEW** |
| Confidence ≤ MODERATE (uncertainty firewall) | **MANDATORY_REVIEW** |
| HIGH confidence × HIGH-stakes surface (journey/KYC) | **MANDATORY_REVIEW** |
| HIGH confidence × LOW stakes | **AUTO_PUBLISH**, 5% random **AUDIT_SAMPLE** |

Every routing decision is disclosed on the response (`review_route`) and in
the reasoning trace; queue items carry their tier. Reviewer demand is now
proportional to uncertainty with the sampled audit stream doubling as the
usage-in-anger evidence feed (Gap 2). At a realistic mix (~70%
high-confidence low-stakes), analyst queue demand drops ~65% — **capacity
sizing: N cases/day/analyst × 4-hour SLA; hire or tune thresholds against
that number, measured weekly.**

### U1 — Source health scoring (implemented: `app/scrapers/source_health.py`)

Per-source scorecard recomputed after every ingest:
`health = 0.45·fresh + 0.30·(1−contradiction) + 0.25·(1−copy_chain)`.
Freshness SLA breach **or** health < 0.45 → auto-demote PRIMARY→SECONDARY
with audit note; recovery (SLA met ∧ health ≥ 0.65) restores automatically.
Human curators review **only demotions and recoveries** (queue tier
`CURATOR_REVIEW`) — never steady state.

### D3 — Calibration cadence

Weekly batch audits are replaced by rolling daily calibration once the pilot
produces enough override labels (from the D1 AUDIT_SAMPLE stream): Brier
score + agreement rate daily, Part-B thresholds alerting.

### U3 — Build process

Monolithic spec batches give way to thin flag-gated vertical slices, each
with its own mini posture statement (blast-radius class + review level).

### The named next constraint

> **KYC manual reviewer capacity (§14's 4-business-hour SLA).** Identity
> decisions cannot be sampled or tiered — they stay fully linear with
> verification volume. Once fact-checking scales freely, KYC reviewer
> headcount is the binding limit on platform growth; the only levers are
> auto-approval threshold tuning (Part 13) and reviewer hiring.

---

## 3. Standing behavior rules (project operating rules)

```text
RULE 1 (trust-audit):   No ThreatHunter360 deliverable ships with
                        unexamined trust in agent output. Every PR/spec
                        states its blast-radius class and review level.
                        Usage-in-production is the only accepted long-term
                        quality signal; test suites are necessary, not
                        sufficient.

RULE 2 (bottleneck-map): Before accelerating any pipeline stage (more
                        scrapers, faster models, more automation), map the
                        adjacent stages and name the next constraint in
                        concrete terms — a person, an approval, a system —
                        never "process risk."
```

Rule 1 extends Part 20 model governance to *all* generated artifacts;
Rule 2 is a checklist item in the §14.5 launch gate.

---

## 15. v4.6 Measurement Closure addendum

- **Adjudication write-paths — blast radius: MEDIUM, review D2.** Human-outcome records now feed five §71 KPIs; a corrupt adjudication poisons the denominator. Mitigations: every decision is an atomic single-write (second attempt 409s with the recorded verdict named — approvals-engine parity); CORRECTED decisions require the correction in writing (validator, not convention); prior system verdicts are captured at decision time from the system's own persisted rows, never recollected later; denied/expired flows touched zero existing paths (additions only).
- **Reroute denominator rules — blast radius: MEDIUM-HIGH, review D2.** The acceptance KPI is only trustworthy if the denominator can't be gamed. Rules are code, not convention: AUTO_RESOLVED (risk eased by itself) is excluded from human-denominator math by construction; one decision per pending recommendation; a resolved watch can't be re-adjudicated into the sample.
- **§26 vocabulary extensions (ReviewDecided / RerouteAdjudicated / AlertAdjudicated) — blast radius: LOW, review D1.** Documented openly as platform extensions (SourceHealthChanged precedent, v4.3) — never presented as spec-named events.
- **Latency persistence — blast radius: LOW, review D1.** perf_counter around the pipeline, ms float column; no behavior change to verdicts, no-engineering-path branched on the value.

## 14. v4.5 Pilot Readiness addendum

- **§21/§71 KPI statements — blast radius: MEDIUM-HIGH, review D2.** A KPI is a claim about the platform; a wrong "green" is the second-worst output after a false posture OK (v4.3 addendum). Mitigations: every KPI carries `{status, sample, basis}` — unmeasurable spec metrics report UNAVAILABLE with the missing write-path named (telemetry obeys §20); measured zeros require a real denominator (sample > 0) else UNAVAILABLE; the Prometheus exporter omits UNAVAILABLE value series so ops pipelines can't ingest fabricated numbers (`th360_kpi_available` exists precisely to alert on measurement loss); `kpi_sql` is SELECT-only at the chokepoint so telemetry can never write.
- **First live source (crt.sh) — blast radius: MEDIUM, review D2.** Real network egress against real subjects is new; the failure mode is silent wrongness, not access. Mitigations: PASSIVE CT only (§64 lowest-sensitivity class), gated §76 → §63 cone → §80 ACTIVE+allowlist before any packet; every outcome — success AND classified failure — writes §26 events; evidence rows are content-hash idempotent (re-observation never duplicates); connector health flips DEGRADED with cause+timestamp on failure rather than resting on the activation mount, so a broken egress is *visible* in the §6/§32 monitor (caught and fixed during live verification).
- **Error-detail surfacing in PipelineError handler — blast radius: LOW, review D1.** Responses now include the raising site's operator-facing `detail` (additive to legacy keys). Mitigation: truncated to 600 chars; details are authored for operators, no stack traces or secrets (§25 — connector secrets never enter the platform by construction).
- **`/ops/metrics` scrape surface — blast radius: LOW-MEDIUM, review D2.** Operational counters visible at `read` tier; no case content, subjects, or evidence in the exposition (counts and rates only).

## 13. v4.4 Enterprise Plane addendum

- **RBAC enforcement — blast radius: HIGH, review D1.** A permissive default would make roles cosmetic; an accidental hard requirement would brick the demo. Mitigations: matrix is deterministic and tested from both directions (403 floor tests + floor-pass tests); the demo human path is admin-with-disclosure openly declared in whoami; API keys can never self-elevate (role comes from key bearing, header overrides ignored on keyed paths); SSO remains documented-only — no fake IdP forms anywhere.
- **Retention sweeper — blast radius: HIGH, review D1.** Deletion is unrecoverable. Mitigations: dry-run default on the route AND the function; per-class counts reported with the producing policy; every run writes its own audit row; audit_trail + consent_ledger are PERMANENT invariants with no code path in the sweeper (consent-chain deletion would self-evidence CRITICAL posture — v4.3 chain tests).
- **SIEM export + HMAC — blast radius: MEDIUM, review D2.** Export of the audit plane leaks operational detail if the key mismanaged. Mitigation: export is governance-gated; the HMAC header only appears when the tenant sets TH360_SIEM_KEY — no key, no signature, never a spoofable header.
- **Connector registry — blast radius: MEDIUM, review D2.** New connectors widen the fetch surface. Mitigations: registration is admin-scoped, activation is approval-gated (durable effect registry; rejection = provable no-op), env-var NAME only with pasted-secret rejection, retirement is immediate and auditable, day-one health visibility in §6/§32 monitor.

## 12. v4.3 Continuous Assurance addendum

- **Posture statement — blast radius: MEDIUM-HIGH, review D2.** An OK/ATTENTION/CRITICAL badge inverts trust if wrong: a false OK is the worst output a governance surface can emit. Mitigations: posture rules are deterministic and *favor alarms* (any degraded source ⇒ at least ATTENTION; consent-chain break or SEV1 ⇒ CRITICAL); reasons are always enumerated so the verdict can be falsified by inspection; the sweep is a *persisted series* — a single bad run can't rewrite history.
- **§26 native naming in reassess_all — blast radius: LOW, review D1.** One emission site with per-channel monkeypatch points removed in favor of real events; double-emission is prevented by construction (counters downstream, no duplicate writes).
- **SourceHealthChanged platform extension — blast radius: LOW, review D1.** Documented as an extension beyond §26 vocabulary in the mapping doc rather than smuggled into the spec's list.
- **Notify → AlertTriggered at the store chokepoint — blast radius: LOW-MEDIUM, review D2.** Higher audit volume; mitigations: single event store by design (append-only), event rows carry the notification kind so filters stay precise.

## 11. v4.2 Governance Planes addendum

- **Policy engine as single decision point — blast radius: HIGH, review D1.**
  Centralizing authorization shrinks the attack surface *if* the engine is
  sound — and is catastrophic if it isn't. Mitigations: fail-closed on ANY
  failed check with the full ledger returned (no short-circuit hiding);
  `authorize_run` delegation keeps byte-for-byte error/event parity (48
  parity tests); engine never fabricates a PERMIT — the default with no
  governing context is still explicit; denials are always recorded because
  they are the safety signal, not noise.
- **Approval engine effects — blast radius: HIGH, review D1.** A wrong
  grant executes real effects (promotion rights). Mitigations: effects run
  only from the grant hook (rejection is provably a no-op — tested);
  decisions are single-use via an atomic `WHERE status='PENDING'` guard
  (double-decide = 409, second decider never overwrites the first);
  single-step flows still mint request+grant as two events so nothing is
  "human-approved invisibly".
- **Agent inventory blast-radius notes — blast radius: MEDIUM, review D2.**
  Honest exposure statements could alarm legit adopters. Mitigation: notes
  are template-derived from the declared allowlists and state their basis;
  `honest_limits` records what the demo profile cannot claim (package
  hashes, live runtime telemetry) rather than emitting fake attestation.

## 10. v4.1 Forensics & Evidence Fabric addendum

- **OSINT dork builder — blast radius: MEDIUM-HIGH, review D2.** Query
  syntax that finds exposed logins/documents is dual-use: the *generation*
  of a dork is words on a page, but it teaches a method. Mitigations:
  builder NEVER executes (no live connector in this profile — output can
  never masquerade as an observation); every dork is PASSIVE-tagged with
  declared boundaries and the passive-first ordering statement; binding to
  a case reuses the §76 lifecycle gate (closed-case generation 403s);
  unknown subject types/engines degrade to a disclosed baseline rather than
  improvising; every set written to the audit trail.
- **A-04 media forensics route — blast radius: MEDIUM, review D1.** A
  wrong "fake" call is reputational damage; a wrong "authentic" call worse.
  Mitigations preserved: §1.9 (UNVERIFIED ≠ fake) is the no-fixture
  outcome; "Likely authentic" hedged; every call audited; demo fixtures are
  recognizable, live media degrades honestly.
- **Investigation graph over links — blast radius: LOW, review D1.** The
  graph re-renders only rows already in the store; deleted artifacts
  surface as retention *notes* (provenance outlives content, §26) — the
  graph cannot imply evidence that isn't there.
- **Evidence Locker — blast radius: LOW, review D1.** Read-only store view;
  provenance columns mandatory per row; empty result states say "nothing
  stored — not a verdict".

## 9. v4.0 Intelligence Core addendum

- **§63 investigation authorization gate — blast radius: HIGH, review D1.**
  This is a hard execution boundary: a mis-scoped allowlist wrongly refuses
  legitimate work; a bug in the gate wrongly *admits* unacceptable work.
  Mitigations: denial is the fail-closed default (any read failure of the
  allowlist falls back to `[]`… and `[]` means *open public tier only*,
  which is rendered as such — never claimed as blanket authorization); the
  gate runs BEFORE tree creation so refusals leave zero execution state;
  every denial/expiry writes a §26 event with the denied families named
  (§54 deterministic checks — expiry and source sets are code comparisons,
  never model judgment); "§35/§76" is quoted in the user-facing error so
  the refusal is traceable to the invariant.
- **Coverage axis on verdicts — blast radius: MEDIUM, review D2.** A second
  number could invite the same over-confidence as a single number.
  Mitigations: Coverage is deterministic from independence analysis
  (≥3 groups + PRIMARY ⇒ HIGH; ≥2 ⇒ MEDIUM; else LOW) with `coverage_basis`
  always surfaced beside it; the UnifiedReport's `assessed.confidence_axis`
  string states "never a single 'risk %'" so the two-axis rule travels with
  the data.
- **§70 epistemic block — blast radius: LOW, review D1.** The layers are
  *derived from the same assembly fields* the spine already renders
  (observed counts only `EVIDENCE`-labelled items) — it cannot introduce a
  new claim, only re-separate existing ones; empty layers render empty
  (offline/degraded runs show honest empties, §20).

## 8. v3.5 Crisis-focus addendum

- **Crisis-focus UI — blast radius: LOW-MEDIUM, review D2.** Simplifying
  during crisis must not *hide* dismissed-but-relevant context. Mitigations:
  only the pane set is reduced (no data deleted — full tabs return on
  resolve); the checklist is interactive but guidance-only and says so;
  motion suppression is a comfort feature, never a signal amplifier (no
  feed acceleration, in line with the review's risk #10 language).
- **Field manual drills (#1) — blast radius: LOW, review D1.** Training
  content uses only seed fixtures; drills are self-judged (no platform
  scoring that could itself be gamed), and each names the honest behavior
  the operator should recognize so the drill teaches what to distrust.

## 7. v3.4 Red-team hardening addendum

- **Cortex crisis detection — blast radius: MEDIUM, review D2.** A false
  positive could page the on-call (crisis fatigue); a false negative leaves
  a real incident chatted away. Mitigations: conservative first-person
  emergency phrase set, drill/tabletop suppression list, detection only
  *surfaces the existing functional declaration pathway* (it never pretends
  to respond itself), one safety event per session (no alert spam).
- **Region-aware consent defaults — blast radius: MEDIUM, review D2.** A
  wrong default could expose personal data. Mitigations: explicit ledger
  entries always win; biometrics are opt-in in EVERY region; the effective
  state's *origin* (ledger vs region default) is returned and rendered so
  nothing is silently on; regions are a closed declared set with a plain-
  language notice ("product choices, not legal advice").

## 6. v3.3 Sovereign Ops Node addendum

- **`id_audit_l1` (VOYAGER) — blast radius: LOW-MEDIUM, review D2.** Read-only
  identity-integrity indicators. Verdicts are hedged (PASS ≠ proof of
  legitimacy; REVIEW/FAIL ≠ proof of abuse) and REQUIRE_HUMAN for any
  consequential decision flows through the existing review queue. Carrier
  integrity without a live carrier API reports UNKNOWN, which can only push a
  result *toward* REVIEW — never toward PASS (fail-closed, §20).
- **Compliance Index — blast radius: LOW, review D1.** Presentation-only
  indicator computed from local records; the payload itself says it is "not
  an audit certification." (Automation-bias guard: per-component notes state
  exactly what was and was not measured.)
- **Sovereign Data Stream — blast radius: LOW, review D1.** Read-only blend
  of existing audit rows + live pulses; persistence labels prevent live
  heartbeats being mistaken for durable records.
- The v3.3 identity-intel RGD branch inherits the v3.2 ethics gate: private-
  individual targeting is refused *before* any HUNTER/VOYAGER fan-out; the
  regression is pinned by `test_sovereign_ops.py::test_ethics_gate_still_first`.

## 5. v3.0 SOVEREIGN FUSION addendum

The v3.0 upgrade (see the master spec) introduces autonomous *orchestration*
capability; the trust posture tightens accordingly:

1. **Agents advise and prioritize; they do not act on the world.** Every
   external-effect operation (`apply_patch`, `block_domain`, `isolate_host`,
   `promote_custom_agent`, evidence purge) passes
   `AUDITOR.authorize_action` → REQUIRE_HUMAN, and the decision lands on the
   immutable audit trail with the sovereign policy version. The v3.0 suite
   asserts patching parks `AWAITING_HUMAN` — there is no code path that skips
   this (fail-closed default: unknown actions REQUIRE_HUMAN).
2. **Function-level governance is architectural (A-14).** PATHFINDER dispatch
   consults each agent's declared `api_functions` allowlist before every task;
   out-of-allowlist calls become BLOCKED task states (§20-classified), not
   retries or silent drops.
3. **The named constraint stands (Rule 2).** v3.0 moves more verdict types
   through the tiered review matrix, but KYC manual reviewer capacity
   (§14's 4-business-hour SLA) remains the non-samplable constraint —
   SENTINEL/AUDITOR tickets join that same queue, monitored via
   `/api/v1/ops/kpis` `review_queue_depth`.
4. **Reassessment is honest by construction (§1.10).** The continual
   reassessment loop only *notifies*; it never edits history. Prior verdicts
   remain in the checks table; the notification body records the old outcome
   and the reason for the change.
5. **Personalization shapes presentation, never conclusions (§3.4).** Shipped
   surface (v3.1): saved entity watchlists, journey-priority/alert-threshold/
   output-format defaults. Enforcement is CI-level — opposing preference
   profiles produce byte-identical verdict/risk output
   (`test_privacy_personalization.py::TestPresentationNeverConclusions`).
6. **Consent is provable (§5.3, v3.1).** The consent ledger is append-only
   and hash-chained; writes require no trust because tampering breaks the
   chain (`verify_chain()`), withdrawal is a new entry (history kept), and
   personalization writes are refused with classified `CONSENT_REQUIRED`
   unless the grant exists — nothing is stored silently.
7. **Safety-by-design is load-bearing (v3.2, external UX review).** Users can
   review any one-shot plan before it runs (Plan Review gate), halt running
   work (`HALTED` states, honest "no rollback" claims), delete reports and
   personal data, and declare real incidents (webhook delivery reported
   honestly — `not_configured` beats cosmetic). AUDITOR refuses
   private-individual OSINT targets and jailbreak phrasing pre-decomposition;
   refusals are on the audit trail. The safety learning loop (halt/reject/
   incident/ethics/masking counts) is exposed in KPIs so we measure where
   humans push back on the machine. Full mapping: `design/Safety-Review-v3.2.md`.

---

## 4. Production-pilot protocol (criterion 4: usage in anger)

Mandatory before general availability — minimum 4 weeks:

1. **Cohort**: ≥3 real analysts using Fact Checker and Journey Advisor on
   live workloads; ≥1 KYC reviewer on the §27 queue.
2. **Instrumentation**: every analyst override on a verdict is logged with
   reason (the AUDIT_SAMPLE lane plus free mandatory reviews); override rate,
   disagreement taxonomy and time-to-review are reviewed weekly.
3. **Gate for launch sign-off (§14.5)**: analyst–system agreement trending
   stable or improving; **zero** confidently-wrong HIGH/VERY_HIGH false
   verdicts surviving review; KYC reviewer SLA breach rate measured and a
   capacity plan attached; demoted sources (U1) dispositioned by a curator.
4. **Evidence**: pilot logs are the trust artifact — "has run in production"
   cannot be faked by an agent in minutes.

---

*Client-facing one-liner:* "Automating claim analysis gives ~100× faster
draft conclusions; we've redesigned review into uncertainty-tiered sampling
so human attention scales with doubt rather than volume — but expect KYC
reviewer capacity (4-hour SLA) to become the next constraint, and we've
named it before you hit it."
