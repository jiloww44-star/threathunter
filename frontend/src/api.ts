// API client — relative paths only; the Vite dev proxy forwards /api → :8000
import type {
  AgentInfo, AnalyticsSummary, ComplianceIndex, ConsentLedgerView,
  ConsentStateView, CortexReply, FactCheckResponse, GraphData, IdAuditResult,
  Incident, JourneyResponse, KYCResponse, KYCFixture, MeshStatus, OpsKpis,
  OpsNotification, PlanProposal, Prefs, RecentCheck, RegionsView, Statistics,
  StrategyMap, StreamResponse, TreeSummary, UnifiedReport, Investigation,
  DorkSet, MediaForensics, LockerResponse, ApprovalRecord,
  AgentInventoryResponse, AssuranceStatus, Whoami, Connector,
  RetentionReport, ReviewItem, RerouteRow, LiveObservation,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    // §20 — backend returns {error_code,title,meaning,next_step} or detail
    const body = await res.json().catch(() => ({}));
    throw {
      code: body.error_code || `HTTP_${res.status}`,
      title: body.title || "Something went wrong",
      meaning: body.meaning || body.detail || "The request could not be completed",
      next_step: body.next_step || "Please retry",
    };
  }
  return (await res.json()) as T;
}

export const api = {
  factCheck: (claim: string) =>
    request<FactCheckResponse>("/api/v1/factcheck", {
      method: "POST",
      body: JSON.stringify({ claim }),
    }),
  reassess: (checkId: string) =>
    request<FactCheckResponse>(`/api/v1/factcheck/${checkId}/reassess`, {
      method: "POST",
    }),
  journey: (payload: Record<string, unknown>) =>
    request<JourneyResponse>("/api/v1/journey/assess", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  kycVerify: (payload: Record<string, unknown>) =>
    request<KYCResponse>("/api/v1/kyc/verify", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  kycFixtures: () => request<{ fixtures: KYCFixture[] }>("/api/v1/kyc/fixtures"),
  recent: () => request<RecentCheck[]>("/api/v1/feed/recent"),
  statistics: () => request<Statistics>("/api/v1/feed/statistics"),
  caseGraph: (checkId: string) =>
    request<GraphData>(`/api/v1/graph/case/${checkId}`),
  analyticsSummary: (days = 30) =>
    request<AnalyticsSummary>(`/api/v1/admin/analytics/summary?days=${days}`),
  reviewQueue: () =>
    request<{ queue: ReviewItem[]; depth: number;
              by_tier: Record<string, number>; sla?: string }>(
      "/api/v1/admin/review-queue"),
  // ---- v4.6 §71 human-outcome write-paths (analyst tier) ----
  decideReview: (reviewId: string, decision: "CONFIRMED" | "CORRECTED",
                 correctedOutcome?: string) =>
    request<ReviewItem>(`/api/v1/ops/review/${reviewId}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision,
                             corrected_outcome: correctedOutcome ?? null }),
    }),
  adjudicateAlert: (notificationId: string,
                    verdict: "TRUE_POSITIVE" | "FALSE_POSITIVE") =>
    request<OpsNotification>(
      `/api/v1/ops/notifications/${notificationId}/adjudicate`, {
        method: "POST", body: JSON.stringify({ verdict }),
      }),
  decideReroute: (watchId: string, decision: "ACCEPT" | "DECLINE") =>
    request<RerouteRow>(`/api/v1/ops/watches/${watchId}/reroute`, {
      method: "POST", body: JSON.stringify({ decision }),
    }),
  reroutes: () =>
    request<{ reroutes: RerouteRow[]; pending: number; note: string }>(
      "/api/v1/ops/watches/reroutes"),
  // ---- v4.5/4.7 governed live observations (§80 registry-backed) ----
  observeLive: (source: "crtsh" | "rdap", investigationId: string,
                domain: string) =>
    request<LiveObservation>(`/api/v1/osint/live/${source}`, {
      method: "POST",
      body: JSON.stringify({ investigation_id: investigationId, domain }),
    }),
  sourceHealth: () =>
    request<{ sources: Array<{
      source_id: string;
      health_score: number | null;
      health_note: string | null;
      authority: string;
      last_success_at: string | null;
    }> }>("/api/v1/admin/source-health"),
  analyticsExportUrl: (format: "csv" | "xlsx", days = 30) =>
    `/api/v1/admin/analytics/export?format=${format}&days=${days}`,
  spokenSummary: (result: Record<string, unknown>) =>
    request<{ spoken_text: string }>("/api/v1/voice/spoken-summary", {
      method: "POST",
      body: JSON.stringify({ result }),
    }),

  // ---- v3.0 SOVEREIGN FUSION — Unified Ops Node (spec §2/A-01) ----
  cortexChat: (sessionId: string, message: string) =>
    request<CortexReply>("/api/v1/cortex/chat", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, message }),
    }),
  opsGoal: (goal: string, investigationId?: string | null) =>
    request<UnifiedReport>("/api/v1/ops/goal", {
      method: "POST",
      body: JSON.stringify(
        investigationId ? { goal, investigation_id: investigationId } : { goal }),
    }),
  opsTree: (treeId: string) =>
    request<StrategyMap>(`/api/v1/ops/tree/${treeId}`),
  opsTrees: () => request<{ trees: TreeSummary[] }>("/api/v1/ops/trees"),
  opsResume: (treeId: string) =>
    request<UnifiedReport>(`/api/v1/ops/tree/${treeId}/resume`, {
      method: "POST",
    }),
  opsMesh: () => request<MeshStatus>("/api/v1/ops/mesh"),
  opsAgents: () =>
    request<{ agents: AgentInfo[]; policy_version: string }>(
      "/api/v1/ops/agents"),
  opsNotifications: () =>
    request<{ notifications: OpsNotification[] }>("/api/v1/ops/notifications"),
  opsReassess: () =>
    request<{ emitted: number }>("/api/v1/ops/reassess", { method: "POST" }),
  opsKpis: () => request<OpsKpis>("/api/v1/ops/kpis"),

  // ---- §5.3 consent ledger + §3.4 personalization ----
  consent: (userId: string, purpose: string, state: "granted" | "withdrawn") =>
    request<{ entry_id: string }>("/api/v1/privacy/consent", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, purpose, state }),
    }),
  consentState: (userId: string) =>
    request<ConsentStateView>(`/api/v1/privacy/consent/${userId}`),
  consentLedger: () => request<ConsentLedgerView>("/api/v1/privacy/ledger"),
  /* v3.4 red-team #9 — region-aware consent defaults */
  listRegions: () => request<RegionsView>("/api/v1/privacy/regions"),
  setRegion: (userId: string, region: string) =>
    request<{ user_id: string; region: string; mode: string; notice: string }>(
      "/api/v1/privacy/region", {
        method: "PUT",
        body: JSON.stringify({ user_id: userId, region }),
      }),
  getPrefs: (userId: string) => request<Prefs>(`/api/v1/prefs/${userId}`),
  savePrefs: (userId: string, patch: Partial<Prefs>) =>
    request<Prefs>(`/api/v1/prefs/${userId}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  // ---- v3.2 safety-by-design: plan gate, halt, crisis, data ramps ----
  planGoal: (goal: string, investigationId?: string | null) =>
    request<PlanProposal>("/api/v1/ops/plan", {
      method: "POST",
      body: JSON.stringify(
        investigationId ? { goal, investigation_id: investigationId } : { goal }),
    }),
  approveTree: (treeId: string) =>
    request<UnifiedReport>(`/api/v1/ops/tree/${treeId}/approve`, {
      method: "POST",
    }),
  rejectTree: (treeId: string) =>
    request<{ status: string }>(`/api/v1/ops/tree/${treeId}/reject`, {
      method: "POST",
    }),
  haltTree: (treeId: string) =>
    request<{ note: string }>(`/api/v1/ops/tree/${treeId}/halt`, {
      method: "POST",
    }),
  deleteTree: (treeId: string) =>
    request<{ deleted: boolean }>(`/api/v1/ops/tree/${treeId}`, {
      method: "DELETE",
    }),
  declareIncident: (severity: string, summary: string, declaredBy: string) =>
    request<Incident>("/api/v1/ops/incident/declare", {
      method: "POST",
      body: JSON.stringify({ severity, summary, declared_by: declaredBy }),
    }),
  activeIncident: () =>
    request<{ incident: Incident | null }>("/api/v1/ops/incident/active"),
  resolveIncident: (incidentId: string) =>
    request<{ status: string }>(`/api/v1/ops/incident/${incidentId}/resolve`, {
      method: "POST",
    }),
  deleteUserData: (userId: string) =>
    request<{ deleted: boolean }>(`/api/v1/data/user/${userId}`, {
      method: "DELETE",
    }),
  /* v3.3 — SOVEREIGN OPS NODE (blueprint v5.2) */
  opsStream: (limit = 60) =>
    request<StreamResponse>(`/api/v1/ops/stream?limit=${limit}`),
  complianceIndex: () => request<ComplianceIndex>("/api/v1/privacy/compliance-index"),
  idAudit: (identity: string, identifierType = "auto") =>
    request<IdAuditResult>("/api/v1/privacy/id-audit", {
      method: "POST",
      body: JSON.stringify({ identity, identifier_type: identifierType }),
    }),

  // ---- v4.0 §2 Investigation Core — the §63 authorization object ----
  createInvestigation: (body: {
    objective: string; subject_type: string; subject: string;
    purpose: string; authority: string; scope?: string;
    allowed_sources?: string[]; expires_days?: number; user_id?: string;
  }) =>
    request<Investigation>("/api/v1/investigations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listInvestigations: (userId?: string) =>
    request<{ investigations: Investigation[] }>(
      `/api/v1/investigations${userId ? `?user_id=${encodeURIComponent(userId)}` : ""}`),
  getInvestigation: (invId: string) =>
    request<Investigation>(`/api/v1/investigations/${invId}`),
  linkInvestigation: (invId: string, kind: string, refId: string) =>
    request<{ link_id: string }>(`/api/v1/investigations/${invId}/link`, {
      method: "POST",
      body: JSON.stringify({ kind, ref_id: refId }),
    }),
  closeInvestigation: (invId: string, reason = "") =>
    request<Investigation>(`/api/v1/investigations/${invId}/close`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  sourceHealthMonitor: () =>
    request<{ sources: Array<{ source_id: string; state: string;
      health_score: number | null; note: string; checked_at: string | null;
      last_success_at: string | null; authority: string | null }>;
      count: number; states_present: string[];
      states_vocabulary: string[] }>("/api/v1/feed/source-health"),

  // ---- v4.1 OSINT console (§73 V1.5) + Evidence Locker (V1) ----
  buildDorks: (body: { objective: string; subject: string;
    subject_type?: string; search_engine?: string;
    investigation_id?: string }) =>
    request<DorkSet>("/api/v1/osint/dorks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  mediaForensics: (mediaRef: string, linkToInvestigation?: string) =>
    request<MediaForensics>("/api/v1/osint/forensics/media", {
      method: "POST",
      body: JSON.stringify(
        linkToInvestigation
          ? { media_ref: mediaRef, link_to_investigation: linkToInvestigation }
          : { media_ref: mediaRef }),
    }),
  investigationGraph: (invId: string) =>
    request<GraphData & { note: string }>(
      `/api/v1/investigations/${invId}/graph`),
  evidenceLocker: (q?: string, source?: string, limit = 60) =>
    request<LockerResponse>(
      `/api/v1/evidence/locker?limit=${limit}`
      + (q ? `&q=${encodeURIComponent(q)}` : "")
      + (source ? `&source=${encodeURIComponent(source)}` : "")),

  // ---- v4.2 governance planes (§73 V2): approvals + agent inventory ----
  listApprovals: (status?: string) =>
    request<{ approvals: ApprovalRecord[] }>(
      `/api/v1/ops/approvals${status ? `?status=${status}` : ""}`),
  decideApproval: (approvalId: string, approved: boolean,
                   decidedBy = "operator") =>
    request<ApprovalRecord>(
      `/api/v1/ops/approvals/${approvalId}/${approved ? "approve" : "reject"}`,
      { method: "POST", body: JSON.stringify({ decided_by: decidedBy }) }),
  agentInventory: () =>
    request<AgentInventoryResponse>("/api/v1/ops/agents/inventory"),

  // ---- v4.3 continuous assurance (§73 V2.5) ----
  assuranceSweep: () =>
    request<Record<string, unknown> & { posture: string; run_id: string }>(
      "/api/v1/ops/assurance/sweep", { method: "POST" }),
  assuranceStatus: () =>
    request<AssuranceStatus>("/api/v1/ops/assurance/status"),

  // ---- v4.4 enterprise plane (§73 Enterprise) ----
  whoami: () => request<Whoami>("/api/v1/ops/whoami"),
  retentionApply: (dryRun = true) =>
    request<RetentionReport>("/api/v1/ops/retention/apply", {
      method: "POST",
      body: JSON.stringify({ dry_run: dryRun }),
    }),
  listConnectors: () =>
    request<{ connectors: Connector[]; kinds: string[]; note: string }>(
      "/api/v1/ops/connectors"),
  registerConnector: (body: { name: string; kind: string; base_url: string;
    auth_env?: string | null }) =>
    request<Connector & { approval: ApprovalRecord }>(
      "/api/v1/ops/connectors", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  retireConnector: (connectorId: string) =>
    request<Connector>(`/api/v1/ops/connectors/${connectorId}/retire`, {
      method: "POST",
    }),
  siemExportUrl: (sinceHours = 24, limit = 500) =>
    `/api/v1/ops/siem/export?since_hours=${sinceHours}&limit=${limit}`,
  // v4.5 pilot ops — Prometheus exposition of the §71 KPIs. UNAVAILABLE
  // series are omitted by design; alert on th360_kpi_available==0.
  metricsUrl: (windowHours = 168) =>
    `/api/v1/ops/metrics?window_hours=${windowHours}`,
};

export interface ApiError {
  code: string;
  title: string;
  meaning: string;
  next_step: string;
}
