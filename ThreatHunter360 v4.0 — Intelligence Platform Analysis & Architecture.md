# ThreatHunter360 — Deep Research & Product-System Analysis

> Preserved verbatim (user-pasted, v4.0 single source of truth). External
> footnote links retained in §80's tail block.

After consolidating the ThreatHunter360 material across this chat and checking the current external ecosystem, the clearest conclusion is that the product should **not be built as a collection of an OSINT dashboard, safety map, fact checker, KYC tool, and AI-security scanner**.

The unifying product is stronger:

> **ThreatHunter360 is an evidence-driven intelligence and decision platform that turns fragmented signals into verified context, risk assessments, governed actions, and an auditable record of what happened.**

That distinction matters because it gives all of the seemingly different work in this project a common technical foundation.

The analysis below deliberately separates the concerns so the product does not collapse into overlapping features.

---

# 1. What ThreatHunter360 actually is

There are four layers to the product:

```text
                    THREATHUNTER360
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
     OBSERVE            UNDERSTAND          ACT
        │                  │                  │
   Data / signals       Intelligence       Decisions
   APIs / sources       Evidence           Workflows
   sensors              Reasoning           Controls
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ↓
                    ACCOUNTABILITY
                           │
             Evidence · Audit · Provenance
```

The product therefore has four fundamental questions:

**What is happening?**

**What evidence supports that?**

**What does the evidence imply?**

**What action is permitted or appropriate?**

This accommodates your three original conversational pillars—Fact Checker, Journey Advisor and KYC—while also accommodating the later OSINT, agent-security and governance work without turning them into disconnected applications.

---

# 2. The hidden common denominator across the entire project

Your conversations repeatedly converged on the same primitive:

## An investigation

A journey is an investigation.
A fact check is an investigation.
A KYC case is an investigation.
A website forensic review is an investigation.
An agent security audit is an investigation.
An incident review is an investigation.

That suggests that **Investigation** should be the primary backend object rather than "chat session."

For example:

```text
Investigation
│
├── Objective
├── Subject
├── Authorization
├── Context
├── Signals
├── Sources
├── Evidence
├── Findings
├── Hypotheses
├── Risk assessment
├── Actions
├── Approvals
├── Outcomes
└── Audit trail
```

This is arguably the most important architectural insight in the entire project.

---

# 3. Replace the chatbot-first architecture

The original concept begins with:

```text
User → Chatbot → Feature
```

I would change that to:

```text
User
 ↓
Intent + Entity Understanding
 ↓
Investigation Planner
 ↓
Evidence/Tool Orchestrator
 ↓
Evidence Normalization
 ↓
Reasoning Engine
 ↓
Policy Engine
 ↓
Human/Agent Decision
 ↓
Action
 ↓
Audit
```

The chatbot becomes the **interaction layer**, not the intelligence architecture. That prevents the LLM from becoming the source of truth.

---

# 4. ThreatHunter360's reasoning model

The earlier discussion around inductive-logical thinking should become a real product subsystem.

The reasoning engine should operate approximately as:

```text
OBSERVE → EXTRACT → NORMALIZE → CORRELATE → FORM HYPOTHESES →
TEST HYPOTHESES → IDENTIFY CONTRADICTIONS → WEIGHT EVIDENCE →
ASSESS CONFIDENCE → ASSESS RISK → GENERATE OPTIONS → POLICY CHECK →
ACTION / HUMAN REVIEW → UPDATE WHEN NEW EVIDENCE ARRIVES
```

This is much more defensible than asking an LLM: "Is this dangerous?" or "Is this claim true?"

---

# 5. Evidence has to be a first-class object

The project needs a distinction between:

- **Observation** — something a source reports or a system measures.
- **Evidence** — the actual supporting source/record.
- **Finding** — a structured interpretation of related evidence.
- **Hypothesis** — a possible explanation.
- **Assessment** — the reasoned interpretation of the findings.
- **Recommendation** — an available course of action.
- **Action** — what the user or authorized system actually did.
- **Outcome** — what subsequently happened.

This produces an evidence chain:

```text
SOURCE → OBSERVATION → EVIDENCE → FINDING → ASSESSMENT →
RECOMMENDATION → ACTION → OUTCOME
```

That chain should be queryable after the fact.

---

# 6. Source quality is not the same thing as source quantity

Cyber Detective's OSINT collection contains 1,000+ services and explicitly warns that many tools become obsolete, unsupported or nonfunctional over time. Max Intel aggregates links rather than owning the underlying datasets.

Therefore: **ThreatHunter360 should never treat "source exists" as "source is trustworthy."**

Every source needs metadata: source_id, name, category, provider, type, authority, freshness, coverage, geography, method, independence, cost, rate_limit, terms, privacy_class, availability, last_verified.

The system must distinguish 5 independent sources from 5 websites repeating one original source.

---

# 7. Source registry is the real heart of OSINT

The Cyber Detective materials should become a **source catalogue**, not a collection of hard-coded links: Research methodology; API ecosystem (IOT/IP, search, social, vulnerabilities, geolocation, reverse image, news, flights, webcams); tool aggregation (maps, social, domains/IP, image ID, crypto, messengers, code, search engines, IoT, archives, emails, usernames); practical research utilities (code-search, osint-map, pastebin-search, cache-and-archive-search, geolocation-search, web-archive-viewer, webcam-search).

The appropriate ThreatHunter abstraction is: **Research Connector** — not "tool page."

---

# 8. The URL ecosystem should become a controlled capability graph

Five types: **A Methodology** (teach the system how to investigate) · **B Discovery connectors** · **C Data APIs** (machine-readable evidence: Shodan, Netlas, Censys, VirusTotal, Mapbox, Open-Meteo, Google Fact Check) · **D Research distribution** (Substack/GitHub/Medium/Bluesky/Mastodon/Telegram/X — research updates, not automatic evidence) · **E Commercial/engineering ecosystem references** (AI Made Tools → engineering side of Agent Security Readiness).

---

# 9-12. Second product dimension: AI Agent Security Readiness

AI Made Tools organizes AI engineering around architecture, APIs, workflows, reliability, coding agents, data infrastructure, testing, MCP, deployment, operations, security, credentials, identity, permissions.

Commercial offering = **AI Agent Security Readiness + Engineering Assurance.**

Agent Security as separate operating plane: agent/model/tool inventory, identity, permissions, credentials, context, memory, integrations, dependencies, MCP, A2A, runtime telemetry, human approval.

Agent supply chain = Agent Dependency Graph; per node: owner, version, source, publisher, permissions, credentials, trust status, last reviewed, known issue, runtime exposure, data classification. Key question: "What could this agent reach if compromised?"

Readiness audit = Discover → Map → Measure → Manage (NIST AI RMF: Govern, Map, Measure, Manage).

---

# 13. Do not turn NIST into a checkbox

NIST says its Playbook is neither a checklist nor an ordered set of steps. So no "NIST compliant: 83%". Instead per function: Evidence / Gap / Owner / Control / Status.

---

# 14-17. Journey Advisor mechanics

Problem: decision support under changing environmental conditions.
Flow: USER INTENT → ORIGIN/DESTINATION → ROUTE GENERATION → ENVIRONMENTAL SIGNALS → SECURITY SIGNALS → TEMPORAL CONTEXT → ROUTE SEGMENTATION → RISK ASSESSMENT → OPTIONS → USER DECISION → LIVE MONITORING.

- Not "Route A = 83% safe". Multidimensional: traffic, weather, road condition, reported incidents, time of day, evidence freshness, coverage, isolation, hazards → "Assessment: Elevated concern; Confidence: Moderate; Primary reasons: ...".
- Open-Meteo forecasts are time-dependent evidence: store weather_source, forecast_generated_at, valid_for, model, location, variable.
- Segment-based risk: Journey = Segment 1..N + destination; each segment inherits weather/traffic/security/lighting/road-type/assistance/time/confidence → defensible Risk Timeline.

---

# 18-19. Fact Checker = claim-resolution system

Flow: CLAIM EXTRACTION → ENTITY RESOLUTION → TEMPORAL NORMALIZATION → SOURCE DISCOVERY → SOURCE CORRELATION → CLAIM DECOMPOSITION → CONTRADICTION TEST → EVIDENCE WEIGHTING → VERDICT → EXPLANATION.

- Google Fact Check Tools API + Schema.org ClaimReview = baseline evidence source, NOT the complete truth engine.
- Claim decomposition is critical ("Company X launched the first African AI bank in 2026" → 5 sub-claims); one well-supported element must not credit the whole statement.

---

# 20-21. KYC boundary

COLLECT → VALIDATE → EXTRACT → COMPARE → AUTHENTICATE → MANUAL REVIEW WHEN REQUIRED → DECISION → RETENTION/DELETION.
Public OSINT is exploratory; KYC processing is regulated and identity-sensitive (NDPA 2023: access, rectification, objection, restriction, portability, erasure, limits on automated decision-making). Needs: purpose limitation, consent/lawful basis, minimization, access control, retention, deletion, audit, subject rights, human review.
**Identity Investigation ≠ Identity Verification** — separate at UI and permission levels.

---

# 22-23. Unified data architecture & entity graph

Domain model: Tenant, User, Investigation, Subject (Person/Organization/Domain/IP/URL/Location/Agent), Source, Observation, Evidence, Finding, Hypothesis, RiskAssessment, Action, Approval, Incident, Journey, Route, VerificationCase, Agent, Tool, Identity, AuditEvent.
Internal relationship graph (ORG → domain → IP → certificate → subdomain → tech; Person; AI Agent → model → MCP → API → credential → datastore) reused across OSINT, forensics, agent-security, investigations, governance.

---

# 24-26. Backend architecture

React/TanStack → API Gateway → Investigation Orchestrator → Entity/Evidence/Policy engines → Source/Tool Broker (Mapbox/Weather/OSINT/TI/KYC) → Postgres/PostGIS (+ object storage, vector index, event log, audit store).

Postgres+PostGIS = natural core (relational guarantees + geospatial). Graph DB optional later — relational first.

Event architecture (§26): InvestigationCreated, SourceQueried, ObservationReceived, EvidenceStored, FindingCreated, RiskRecalculated, ApprovalRequested, ApprovalGranted, ActionExecuted, JourneyStarted, JourneyConditionChanged, AlertTriggered, IncidentCreated, InvestigationClosed.

---

# 27-32. API Broker / providers

Normalize external systems to one internal Observation object (observation_id, source, type, observed_at, freshness, confidence, subject, data, provenance) — provider independence, not per-provider dashboards.

Shodan/Netlas/Censys/VirusTotal are complementary: same subject → all → normalization → correlation → confidence.

Change Intelligence: website current snapshot + historical snapshots → diff → classify (content, infrastructure, technology, identity, security, third-party deps).

Passive-first design: PASSIVE → PUBLIC ACTIVE → AUTHORIZED ACTIVE. Default = DNS, RDAP, certificates, archives, public pages, HTTP metadata, public tech indicators.

Dorking = methodology engine, stored as {objective, search_engine, syntax, intended_use, risk_level, authorized_scope, source, last_verified}; dork builder explains what/why/expected results/boundaries.

Source Health Monitor per integration: API reachable? schema changed? auth valid? rate limits changed? quality changed? discontinued? terms changed? Status: ACTIVE | DEGRADED | AUTH_REQUIRED | SCHEMA_CHANGED | DEPRECATED | UNAVAILABLE.

---

# 33-40. Max Intel lesson & LLM division of responsibility

Orchestration lesson, not product copy: Max Intel = discovery/aggregation; ThreatHunter360 = discovery + correlation + evidence + reasoning + risk + governance + action.

§34: LLM = understand intent, decompose claims, plan research, synthesize, explain. Deterministic systems = permissions, policy, scoring constraints, schema validation, timestamps, audit, execution controls. External tools = observations. Human = accountable decision-maker.

§35 Agent orchestration: Intent → Planner → Tool Selection → Permission Check → Execution → Result Validation → Evidence Store → Next-Step Planning. LLM must not invent/escalate tool permissions: LLM proposes "query Shodan" → policy engine: "authorized for this subject?" → YES execute / NO reject-request-authorization.

§36 Prompt/context injection model: classify content as TRUSTED/UNTRUSTED/MIXED/UNKNOWN; can untrusted content influence system behavior/tool selection/permissions/data access/external actions?

§37 Human approval = policy object: Action → risk class → required approval level → approver → expiry → execution (e.g. refund thresholds, credential rotation, two-person production deletion).

§38 Kill switch must be real: agent.status = SUSPENDED, tool_permission = REVOKED, credential.status = REVOKED; audit explains who/what/when/why/what stopped.

§39 Rollback: action, before_state, after_state, rollback_method, rollback_owner, rollback_expiry.

§40 Continuous governance across design/development/testing/deployment/operation/incident/retirement → Continuous Agent Assurance, not annual PDF.

---

# 41-45. Product planes & user classes

Planes: 1 Safety (journey/monitoring/alerts/crisis/safe locations) · 2 Intelligence (investigations/OSINT/forensics/evidence/fact checking/GEOINT) · 3 Verification (fact/KYC/document/identity/consistency) · 4 Agent Security (agents/models/tools/permissions/supply chain/injection/runtime) · 5 Governance (policies/approvals/controls/exceptions/incidents/audit).

User classes: Consumer/citizen (never sees MCP/CenQL/privileges unless advanced mode) · Investigator/analyst ("What are you investigating?" — subject, what's known, what to determine, what authority) · Enterprise security (agent environment dashboard → graph).

---

# 46-51. Reporting, provenance, coverage

Reports: Intelligence Report (objective/scope/sources/timeline/evidence/findings/confidence/contradictions/assessment) · Security Readiness Report · Journey Brief.

Provenance graph: Finding → Source A → observation; Source B → observation; timestamp. "Why did the system reach this conclusion?" = inspectable interface.

Evidence freshness visually explicit (Observed 12 min ago · Source Mapbox · Freshness Current).

**Coverage ≠ confidence** (§49): "Confidence: High, Coverage: Low" means reliable but possibly incomplete observation. 2×2 (§50). Better risk representation (§51): risk + evidence + coverage + freshness + confidence + primary drivers — not "Risk = 76%".

---

# 52-55. Stack & determinism boundaries

Recommended stack (reference): TanStack Start / React 19 / Tailwind 4 / Vite; Nitro server; Cloudflare Workers-compatible services; Postgres; PostGIS; Redis/KV; object storage; queue/events; Model Gateway (primary reasoning / fast classification / extraction / embedding) — no single-model hardwire.

Storage roles: PostgreSQL = transactional truth; PostGIS = geospatial truth; object storage = files/screenshots/docs; vector store = semantic retrieval; relationship tables/graph = entity relationships; event store = audit/chronology.

§54 Deterministic: authorization, permissions, credential validation, source timestamps, identity fields, audit events, retention, policy enforcement, approval requirements, tool invocation permissions, risk thresholds, data deletion.
§55 AI: intent detection, claim decomposition, entity extraction, research-plan generation, semantic source comparison, summarization, explanation, hypothesis generation, question generation, report drafting — every substantive conclusion linked back to evidence.

---

# 56-58. Integration strategy & source care

Tier 1 core runtime: Mapbox (directions/traffic/matrix/isochrone/matching), Open-Meteo, OpenStreetMap.
Tier 2 intelligence: Netlas, Shodan, Censys, urlscan, VirusTotal, Wayback (CDX).
Tier 3 verification: Google Fact Check Tools (claim discovery + ClaimReview; NOT the brain), licensed KYC provider.

§57: don't rely on Google Fact Check as general truth API — still need primary research, source comparison, date validation, decomposition, contradiction detection, context analysis.
§58: social channels = research/monitoring channels, not automatic high-confidence evidence; store source role, account identity, publication date, originality, corroboration, media provenance.

---

# 59-62. LOG_ON commercial ladder & social impact

ThreatHunter360 = platform; LOG_ON = ASSESS/BUILD/SECURE/GOVERN/MONITOR: 1 AI Agent Security Readiness Audit · 2 Agent Hardening · 3 Agent Governance Implementation · 4 Agent Supply-Chain Review · 5 Continuous Agent Assurance · 6 Custom ThreatHunter Deployment.

Social impact shapes architecture: local relevance (mixed-mode Lagos journeys: walk/BRT/danfo/keke/okada/train/ferry/ride-hail where data permits), low-bandwidth design (map progressive load, text primary, voice optional, offline cached journey later), accessibility (clear language; localized conversational experiences).

§61 Privacy layer: DATA CLASSIFICATION → PURPOSE → LEGAL BASIS → ACCESS → RETENTION → SHARING → DELETION (KYC, location history, journey tracking, personal investigations, identity data, images, biometrics, org security data).
§62 "Right to explain" as universal UX: Why did you flag this? → Reason/Evidence/Source/Date/Confidence/Uncertainty.

---

# 63-65. Authority model, policy sensitivity, templates

Investigation authority object (§63): purpose, subject type, authority, scope, expiration, allowed sources, allowed actions — e.g. "Purpose: Corporate security assessment; Scope: example.org; Authority: organization-owned; Expires: 2026-10-01" — controls which connectors can be used.

OSINT policy is source-sensitive (§64): public website (low) / public social post (contextual) / public infrastructure record (technical) / personal information (sensitive) / credential-leak data (highly restricted) / KYC document (highly restricted). Same "OSINT" label ≠ identical handling.

Investigation templates (§65): [Investigate Domain] [Verify Claim] [Assess Journey] [Assess AI Agent] [Investigate Incident] [Verify Identity] — each creates an appropriate workflow.

---

# 66-72. Canvas, timeline, reproducibility, KPIs

Investigation Canvas (interactive evidence graph) · immutable investigation chronology (§67) · source-change detection (response, retrieved_at, content hash, parser version, source version) · reproducibility (query, source, params, timestamp, tool/parser version, authorization, result hash → "Re-run investigation").

Reports separate Observed / Interpreted / Assessed / Recommended (§70).

KPIs (§71) — intelligence quality (evidence-backed conclusion rate, contradiction detection rate, freshness, diversity, analyst correction rate); journey (completion, reroute acceptance, false-alarm rate, freshness, decision latency); fact checker (evidence coverage, agreement, correction rate, latency); agent security (inventory counts, remediated findings, coverage); governance (policy coverage, evidence completeness, reconstruction time, exceptions).

North-star (§72): **evidence-backed decisions successfully completed.**

---

# 73-76. Boundaries & the invariant

§73 Roadmap: V1 = Investigation Core + Fact Checker + Journey Advisor + basic OSINT domain investigation + Evidence Locker + Audit trail · V1.5 = website forensics, footprint, dork builder, source health, investigation graph · V2 = agent inventory, readiness, supply chain, policy engine, approval engine · V2.5 = continuous assurance, live monitoring, real-time TI, advanced governance · Enterprise = SSO/RBAC/private deployment/custom connectors/SIEM/SOAR/retention/policies.
§74 NOT V1: 1000 OSINT tools, full autonomous pentesting, all social APIs, custom face recognition, national identity infra, full SIEM, full SOAR, proprietary map engine, custom LLM — integrate instead.
§75 Learn from investigation methodology (plan, tools, evidence, hypotheses, rationale, assessment), not hidden chain-of-thought.

§76 **THE INVARIANT**: "No consequential conclusion without evidence; no consequential action without authorization." Finding requires evidence; action requires policy; sensitive action requires approval; post-action requires audit.

---

# 77-82. Identity & final architecture

ThreatHunter360 = "A conversational intelligence and safety platform for investigating situations, verifying information, assessing risk, and governing AI-enabled actions." Three questions: Investigate (what is happening?) · Assess (what does the evidence indicate?) · Act (what can safely and legitimately be done next?) — plus Prove (what evidence/decision/authority/action trail exists?).

Final architecture (§78): EXPERIENCE LAYER (citizen/analyst/enterprise) + GOVERNANCE LAYER (policy/approval/audit) → INVESTIGATION CORE (intent/entity/workflow planner) → EVIDENCE FABRIC (sources/tools/APIs via broker) → NORMALIZATION → REASONING/CORRELATION → RISK/ASSESSMENT → POLICY ENGINE → HUMAN/AGENT ACTION → EVENT LOG → PROVENANCE/REPORT.

§79 Ecosystem confirmation: NIST AI Agent Standards Initiative (Feb 2026); OWASP Agentic Top 10; NIST AI RMF continuous lifecycle; Cyber Detective/Max Intel show why tool directories decay; Mapbox primitives serve Journey; NDPA frames KYC/location privacy.

§80 Source map (external references): Cyber Detective website & GitHub collections (methodology, APIs, tools, cheat sheets), /codesearch, /osintmap, /pastebin (policy-gated), /quickcacheandarhivesearch, /quickgeolocationsearch, /webarchiveviewer (Wayback CDX), /webcamcse (strict controls), Dorks Collections List, Max Intel, AI Made Tools — retained as external research knowledge base. Social profiles = research distribution/methodology monitoring, not authoritative evidence.

§81 Strategic role: THREATHUNTER360 (Consumer Safety/Intelligence/Verification/Agent Security/Governance) → LOG_ON (Audit/Build/Govern → Assess/Harden/Monitor) — commercial loop: Audit → Discover → Remediate → Deploy → Govern → Monitor.

§82 Final thesis: the differentiator is the combination of evidence, reasoning, authorization, action and accountability in one conversational intelligence architecture — the project's single source of truth.
