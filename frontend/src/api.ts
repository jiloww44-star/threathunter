// API client — relative paths only; the Vite dev proxy forwards /api → :8000
import type {
  AgentInfo, AnalyticsSummary, ConsentLedgerView, ConsentStateView,
  CortexReply, FactCheckResponse, GraphData, Incident, JourneyResponse,
  KYCResponse, KYCFixture, MeshStatus, OpsKpis, OpsNotification, PlanProposal,
  Prefs, RecentCheck, Statistics, StrategyMap, TreeSummary, UnifiedReport,
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
    request<{ depth: number; by_tier: Record<string, number> }>(
      "/api/v1/admin/review-queue"),
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
  opsGoal: (goal: string) =>
    request<UnifiedReport>("/api/v1/ops/goal", {
      method: "POST",
      body: JSON.stringify({ goal }),
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
  getPrefs: (userId: string) => request<Prefs>(`/api/v1/prefs/${userId}`),
  savePrefs: (userId: string, patch: Partial<Prefs>) =>
    request<Prefs>(`/api/v1/prefs/${userId}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  // ---- v3.2 safety-by-design: plan gate, halt, crisis, data ramps ----
  planGoal: (goal: string) =>
    request<PlanProposal>("/api/v1/ops/plan", {
      method: "POST",
      body: JSON.stringify({ goal }),
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
};

export interface ApiError {
  code: string;
  title: string;
  meaning: string;
  next_step: string;
}
