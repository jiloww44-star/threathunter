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
