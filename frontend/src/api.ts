// API client — relative paths only; the Vite dev proxy forwards /api → :8000
import type {
  AnalyticsSummary, FactCheckResponse, GraphData, JourneyResponse,
  KYCResponse, KYCFixture, RecentCheck, Statistics,
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
};

export interface ApiError {
  code: string;
  title: string;
  meaning: string;
  next_step: string;
}
