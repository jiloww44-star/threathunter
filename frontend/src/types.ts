// API types mirroring backend/app/models/schemas.py (§19 response contract)
export type Confidence =
  | "VERY_HIGH" | "HIGH" | "MODERATE" | "LOW" | "VERY_LOW" | "UNDETERMINED";
export type Verdict =
  | "VERIFIED" | "MOSTLY_TRUE" | "PARTIALLY_TRUE" | "MISLEADING" | "FALSE" | "UNVERIFIED";
export type RiskLevel = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";

export interface EvidenceItem {
  source_id: string;
  url?: string | null;
  published_at?: string | null;
  fetched_at: string;
  reliability: string;
  reliability_score: number;
  authority: string;
  independence_group: string;
  supports_claim: boolean | null;
  excerpt: string;
  is_duplicate_copy: boolean;
}

export interface Contradiction {
  description: string;
  evidence_a_id: string;
  evidence_b_id: string;
  severity: RiskLevel;
}

export interface FactCheckResponse {
  verdict: Verdict;
  confidence: Confidence;
  claim: string;
  checked_at: string;
  check_id?: string | null;
  graph_url?: string | null;
  answer: string;
  interpretation: string;
  key_evidence: EvidenceItem[];
  contradictions: Contradiction[];
  recommended_action: string;
  sources_independent: number;
  sources_total: number;
  what_would_change_conclusion: string;
  reasoning_trace: string[];
  ai_narrative?: { text: string; model_used: string; mode: string } | null;
  copy_chain_clusters?: number | null;
  copy_chain_note?: string | null;
  review_route?: string | null;   // Part 18 D1 lane (always disclosed)
  /** v4.0 §49-51 — second axis beside Confidence; never a single risk %. */
  coverage?: "HIGH" | "MEDIUM" | "LOW" | null;
  coverage_basis?: string | null;
}

// ------------------------------------------------- v4.0 Investigation Core
export type InvestigationAuthority = "organization_owned" | "client_authorized"
  | "public_research" | "unchecked";

export interface InvestigationLink {
  id: string;
  kind: string;      // ops_tree | evidence | watch | finding | verification_case
  ref_id: string;
  created_at: string;
}

export interface Investigation {
  id: string;
  objective: string;
  subject_type: string;
  subject: string;
  purpose: string;
  authority: InvestigationAuthority;
  scope: string;
  allowed_sources: string[];
  expires_at: string;
  status: "OPEN" | "CLOSED";
  user_id: string;
  created_at: string;
  updated_at: string;
  links?: InvestigationLink[];
}

// ------------------------------------------------ v4.1 OSINT console V1.5
export interface Dork {
  name: string;
  objective: string;
  search_engine: string;
  syntax: string;
  intended_use: string;
  risk_level: "PASSIVE" | "PUBLIC_ACTIVE" | "AUTHORIZED_ACTIVE";
  authorized_scope: string;
  source: string;
  last_verified: string;
  why: string;
  expected_results: string;
  boundaries: string;
}

export interface DorkSet {
  subject: string;
  subject_type: string;
  dorks: Dork[];
  count: number;
  generated_at: string;
  degraded_note: string | null;
  execution_note: string;
  passive_first: string;
  investigation_id?: string | null;
}

export interface MediaForensics {
  media_ref: string | null;
  assessment: string;
  confidence: string;
  checks: Record<string, string | null>;
  note: string;
  trust_label: string;
  analyzed_at: string;
}

export interface LockerItem {
  id: string;
  source_id: string;
  url: string | null;
  title: string | null;
  excerpt: string;
  reliability: string | null;
  authority: string | null;
  independence_group: string | null;
  published_at: string | null;
  fetched_at: string | null;
  content_hash: string;
}

export interface LockerResponse {
  items: LockerItem[];
  count: number;
  total_stored: number;
  note: string;
}

// ---------------------------------------------- v4.2 governance planes V2
export interface ApprovalRecord {
  id: string;
  kind: string;          // promote_custom_agent | patch_apply | ...
  subject_ref: string;
  summary: string;
  requester: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  decided_by?: string | null;
  decided_at?: string | null;
  context: Record<string, unknown>;
  created_at: string;
}

export interface AgentInventoryCard {
  agent_id: string;
  name: string;
  owner: string;
  version: string;
  source: string;
  publisher: string;
  permissions: { api_functions: string[]; read_only_functions: string[] };
  credentials: string;
  trust_status: "TRUSTED" | "OBSERVED" | "QUARANTINED";
  last_reviewed: string;
  known_issue: string;
  runtime_exposure: string;
  data_classification: string;
  blast_radius_note: string;
  native: boolean;
  status: string;
}

export interface AgentInventoryResponse {
  generated_at: string;
  agents: AgentInventoryCard[];
  dependency_graph: { edges: Array<{ from: string; to: string; kind: string;
    note?: string }>; note: string };
  readiness: { govern: string; map: string; measure: string; manage: string };
  honest_limits: string;
  policy_version: string;
}

// -------------------------------------------- v4.3 continuous assurance V2.5
export interface AssuranceRun {
  id: string;
  actor: string;
  posture: "OK" | "ATTENTION" | "CRITICAL";
  summary: {
    run_id: string;
    posture: "OK" | "ATTENTION" | "CRITICAL";
    posture_reasons: string[];
    events_emitted: { RiskRecalculated: number;
      JourneyConditionChanged: number; AlertTriggered: number };
    source_states: Record<string, string>;
    degraded_or_worse: string[];
    stale_sources: string[];
    source_transitions: Array<{ source_id: string; from: string; to: string;
      reason?: string }>;
    consent_chain_valid: boolean | null;
    consent_chain_entries: number | null;
    pending_approvals: number;
    active_incident: string | null;
    reassessment_degraded: string | null;
    engine_version: string;
  };
  started_at: string;
  finished_at: string;
}

export interface AssuranceSweepResponse extends Omit<AssuranceRun, "id"> {
  run_id: string;
}

export interface AssuranceStatus {
  latest: AssuranceRun | null;
  series: Array<{ id: string; posture: string; started_at: string }>;
  note: string;
}

// ------------------------------------------------ v4.4 enterprise plane
export interface Whoami {
  id: string;
  role: string;
  auth_class: string;
  org_scope?: string;
  permissions_granted: string[];
  roles_vocabulary: string[];
  note: string;
}

export interface Connector {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  auth_env: string | null;
  status: "PENDING_APPROVAL" | "ACTIVE" | "RETIRED";
  registered_by: string;
  approval_id: string | null;
  created_at: string;
  retired_at?: string | null;
}

export interface RetentionClassReport { count: number; action: string }

export interface RetentionReport {
  dry_run: boolean;
  policy: Record<string, number>;
  permanent_classes: string[];
  applied_at: string;
  policy_version: string;
  classes: Record<string, RetentionClassReport>;
  note: string;
}

export interface JourneySegmentRisk {
  time: string;
  segment: string;
  risk: RiskLevel;
  why: string;
  lat?: number | null;
  lon?: number | null;
  incident_count: number;
  max_severity: string;
}

export interface RouteOption {
  route: string;
  safety_score: number;
  travel_time_min: number;
  exposure_km_high_risk: number;
  trade_off: string;
}

export interface JourneyPrediction {
  segment: string;
  predicted_risk: RiskLevel;
  language: string;
  confidence: Confidence;
  basis: string;
  factors: Record<string, number>;
}

export interface JourneyResponse {
  status: "COMPLETE" | "CLARIFICATION_NEEDED";
  answer: string;
  confidence: Confidence;
  missing_fields: string[];
  question?: string | null;
  context_retained: Record<string, string>;
  risk_timeline: JourneySegmentRisk[];
  route_options: RouteOption[];
  prediction: JourneyPrediction[];
  interpretation: string;
  recommended_action: string;
  what_would_change_conclusion: string;
  reasoning_trace: string[];
  data_mode: "live" | "offline-fixture";
  review_route?: string | null;
  route_geometry?: { coordinates: [number, number][] } | null;
  route_summary?: {
    total_km: number; total_min: number;
    origin: string; destination: string;
  } | null;
  ai_narrative?: { text: string; model_used: string; mode: string } | null;
}

export interface KYCAnomaly {
  type: string;
  severity: RiskLevel;
  detail: string;
  action: string;
}

export interface KYCResponse {
  case_id: string;
  decision:
    | "VERIFIED"
    | "VERIFIED_WITH_ADDITIONAL_REVIEW"
    | "PENDING"
    | "UNABLE_TO_VERIFY"
    | "REQUIRES_MANUAL_REVIEW";
  confidence: Confidence;
  anomalies: KYCAnomaly[];
  checks: Record<string, boolean | string | number>;
  answer: string;
  interpretation: string;
  recommended_action: string;
  what_would_change_conclusion: string;
  reasoning_trace: string[];
  routed_to_human_review: boolean;
}

export interface KYCFixture {
  id: string;
  label: string;
  designed_to_test: string;
  document: Record<string, unknown>;
  user_input: Record<string, unknown>;
  selfie_ref: string;
}

export interface RecentCheck {
  check_id: string;
  module: string;
  subject: string;
  outcome: string;
  confidence: Confidence;
  created_at: string;
}

export interface Statistics {
  total_checks: number;
  verdict_mix: Record<string, number>;
  avg_confidence_score: number;
  sources_active: number;
  evidence_items: number;
  signals_indexed: number;
  copy_chain_ratio: number;
  review_queue_depth: number;
  source_freshness_lag_min: Record<string, number>;
  model_versions: Record<string, string>;
}

export interface GraphData {
  nodes: Array<{ id: string; type: string; label: string; [k: string]: unknown }>;
  edges: Array<{ id: string; source: string; target: string; type: string }>;
}

// Analytics (§4)
export interface AnalyticsDay {
  day: string;
  checks_total: number;
  verified: number;
  unverified: number;
  false_or_misleading: number;
  kyc_cases: number;
  journeys: number;
  avg_confidence: number;
  avg_source_diversity: number;
  llm_cost_usd: number;
  llm_calls: number;
  outlier?: boolean;
}

export interface AnalyticsSummary {
  days: number;
  daily: AnalyticsDay[];
  kpis: {
    checks_total: number;
    avg_confidence: number;
    llm_cost_usd: number;
    cost_per_check: number;
    llm_calls: number;
    wow_change: number | null;
    copy_chain_ratio: number;
    review_queue_depth: number;
  };
  budget: {
    total_usd: number;
    calls: number;
    by_purpose_usd: Record<string, number>;
  };
}

// ---------------- v3.0 SOVEREIGN FUSION (Ops Node, spec §2/§3/§6) ---------
export type TaskStatus =
  | "PENDING" | "RUNNING" | "COMPLETE" | "DEGRADED" | "FAILED"
  | "BLOCKED" | "AWAITING_HUMAN" | "HALTED";

export interface OpsTask {
  task_id: string;
  tree_id: string;
  parent_id?: string | null;
  agent: string;
  function: string;
  title: string;
  status: TaskStatus;
  classified_error?: string | null;
  result: Record<string, unknown>;
  started_at?: string | null;
  ended_at?: string | null;
  position: number;
}

export interface TreeSummary {
  tree_id: string;
  goal: string;
  status: string;
  peer_id: string;
  created_at: string;
  updated_at: string;
}

export interface StrategyMap extends TreeSummary {
  dispatch_plan: Record<string, unknown>;
  report?: UnifiedReport | null;
  tasks: OpsTask[];
}

export interface UnifiedReport {
  answer: string;
  confidence: Confidence;
  /** v4.0 §70 — Observed / Interpreted / Assessed / Recommended layers,
   *  never blended into one stream or single number. */
  epistemic?: {
    observed: string[];
    interpreted: string[];
    assessed: {
      confidence: Confidence;
      confidence_axis: string;
      contradiction_count: number;
      degraded_branch_count: number;
    };
    recommended: string[];
  };
  key_evidence: Array<{ trust_label: string; agent: string; text: string }>;
  contradictions: Array<{
    trust_label: string; agent: string; description: string; severity: string;
  }>;
  interpretation: string;
  recommended_action: string;
  sources: { agents_consulted: string[]; policy_version: string };
  what_would_change_conclusion: string;
  trust_labels: string[];
  compliance_notices: string[];
  degraded: Array<{
    agent: string; function: string; state: TaskStatus;
    classified_error?: string | null; note: string;
  }>;
  tree_status: string;
  tree_id: string;
  goal: string;
  peer_id: string;
  // v3.2 safety-by-design
  disclaimer?: string;
  refusal?: { flag: string; message: string } | null;
  halted?: boolean;
}

export interface CortexReply {
  text: string;
  question: string | null;
  context: Record<string, string | null>;
  tree_id: string | null;
  confidence?: Confidence;
  report?: UnifiedReport;
  progress: string[];
  speakable?: boolean;
  /** v3.4 red-team #3 — present when crisis language was detected. */
  crisis?: { phrase: string; action: "declare_incident" };
}

export interface AgentInfo {
  agent_id: string;
  name: string;
  role: string;
  description: string;
  api_functions: string[];
  native: boolean;
  status: string;
  policy_version: string;
  shadow_tree_count?: number;
}

export interface OpsNotification {
  id: string;
  kind: "VERDICT_CHANGE" | "RISK_ELEVATION" | "RISK_RESOLUTION" | "GOVERNANCE";
  title: string;
  body: string;
  ref?: string | null;
  created_at: string;
}

// ---------------- v4.5 §71/§72 pilot KPI plane ----------------
/** One KPI value with its own provenance (§20 applied to telemetry):
 *  status OK = measured from persisted rows (basis says which);
 *  UNAVAILABLE = the write-path is missing (basis names the gap). */
export interface KpiValue {
  value: number | Record<string, number> | null;
  unit: string;
  status: "OK" | "UNAVAILABLE";
  sample: number;
  basis: string;
}

export interface OpsKpisV71 {
  kpi_version: string;
  spec: string;
  computed_at: string;
  window_hours: number;
  north_star: KpiValue & { id: string; spec: string };  // §72
  families: Record<string, Record<string, KpiValue>>;   // §71 five families
  honesty_note: string;
}

export interface OpsKpis {
  tasks_total: number;
  task_status_mix: Record<string, number>;
  per_agent: Record<string, { tasks: number; avg_latency_s: number }>;
  tree_outcomes: Record<string, number>;
  mesh_failovers: number;
  review_queue_depth: number;
  notifications_total: number;
  safety_events?: Record<string, number>;   // v3.2 checklist J
  policy_version: string;
  v71?: OpsKpisV71;                         // v4.5 pilot read-out
}

export interface MeshStatus {
  peers: Array<{ peer_id: string; role: string; alive: boolean }>;
  primary: string;
  peer_count: number;
  failovers: number;
  policy_version: string;
}

// --------------- §5.3 consent ledger + §3.4 personalization ----------------
export interface ConsentStateView {
  user_id: string;
  /** v3.4 red-team #9 — the user's region scoping consent defaults. */
  region?: string;
  region_notice?: string;
  purposes: Record<string, string>; // purpose -> granted | withdrawn | never_asked
  /** v3.4 — effective state per purpose, with honest origin. */
  effective?: Record<string,
    { purpose: string; state: string; origin: "ledger" | "region_default";
      region: string }>;
  ledger: Array<{
    id: string; user_id: string; purpose: string; state: string;
    detail: string; entry_hash: string; created_at: string;
  }>;
}

export interface RegionsView {
  regions: Record<string,
    { label: string; mode: "opt-in" | "opt-out";
      defaults: Record<string, string> }>;
  notice: string;
}

export interface ConsentLedgerView {
  verification: { entries: number; chain_intact: boolean; note: string };
  entries: ConsentStateView["ledger"];
  purposes: string[];
}

export interface Prefs {
  user_id: string;
  watchlists: string[];
  journey_priority: string;
  notify_tolerance: string;
  output_format: string;
  consent: string;
  source: "defaults" | "stored";
}

// ---------------- v3.2 Safety-by-design (UX review blockers) ---------------
export interface PlanProposal {
  tree_id: string;
  status: "PROPOSED";
  goal: string;
  peer_id: string;
  /** v4.0 §2 — set when the plan is bound to an investigation's §63
   *  authorization object. */
  investigation_id?: string | null;
  plan: Array<{ agent: string; function: string; title: string; parent: boolean }>;
  task_count: number;
  ethics_flag: { flag: string; message: string } | null;
  cost_warning: string | null;
  disclaimer: string;
  note: string;
}

export interface Incident {
  incident_id: string;
  severity: "SEV1" | "SEV2" | "SEV3";
  summary: string;
  declared_by: string;
  status: "ACTIVE" | "RESOLVED";
  delivery: { state: string; note?: string; channel?: string | null };
  created_at: string;
  checklist?: string[];
  /** v3.5 risk #10 — honest guidance that rides with the active state. */
  ui_guidance?: string;
}

/* v3.3 — SOVEREIGN OPS NODE (blueprint v5.2) */
export interface StreamEvent {
  kind: "audit" | "heartbeat";
  persistence: "persisted" | "live";
  ts: string;
  actor: string;
  text: string;
  detail?: string;
}

export interface StreamResponse {
  events: StreamEvent[];
  mesh: MeshStatus;
  note: string;
}

export interface ComplianceComponent {
  key: string;
  label: string;
  spec: string;
  score: number;
  max: number;
  note: string;
}

export interface ComplianceIndex {
  index: number;
  grade: "A" | "B" | "C" | "REVIEW";
  components: ComplianceComponent[];
  indicator_notice: string;
  tree_statuses: Record<string, number>;
}

export interface IdAuditResult {
  identity: string;
  identifier_type: string;
  level: string;
  verdict: "PASS" | "REVIEW" | "FAIL";
  risk_points: number;
  signals_total: number;
  checks: {
    check: string;
    source: string;
    verdict: string;
    signals: string[];
    detail: Record<string, unknown>;
  }[];
  hedge: string;
  disclaimer: string;
  provenance: { checks: string[]; degraded: string };
}
