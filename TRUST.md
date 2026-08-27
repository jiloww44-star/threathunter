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
