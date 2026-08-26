// Journey Advisor view — spec Parts 1.6, 2.5, 5-8. Conversational
// clarification (§14-15), §7 risk timeline, §8 route trade-offs, §9 hedged
// predictions.
import { useState } from "react";
import { api, type ApiError } from "../api";
import type { JourneyResponse, JourneySegmentRisk, RiskLevel } from "../types";
import {
  ConfidenceMeter, ErrorPanel, LoadingStages, ReasoningTrace, TrustTag,
} from "../components/shared";
import { JourneyMap } from "../components/JourneyMap";

const RISK_COLOR: Record<RiskLevel, string> = {
  LOW: "#22c55e", MODERATE: "#f59e0b", HIGH: "#ef4444", CRITICAL: "#b91c1c",
};

export function JourneyAdvisor() {
  const [origin, setOrigin] = useState("Lagos");
  const [destination, setDestination] = useState("Ibadan");
  const [departure, setDeparture] = useState("2026-08-24T07:00");
  const [priority, setPriority] = useState("balanced");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<JourneyResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const assess = async (payload: Record<string, unknown>) => {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.journey(payload));
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    assess({
      origin, destination,
      departure_time: departure ? new Date(departure).toISOString() : undefined,
      priority,
    });
  };

  return (
    <section aria-labelledby="ja-title">
      <header className="view-head">
        <p className="view-kicker">Module · Movement risk</p>
        <h1 id="ja-title">🛡️ Journey Advisor</h1>
        <p className="view-lede">
          “Is my journey safe?” — weather, incident history and congestion fused
          into a per-segment risk timeline; every change is explained (§7).
        </p>
      </header>

      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="origin">Origin</label>
          <input id="origin" type="text" value={origin}
                 onChange={(e) => setOrigin(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="destination">Destination</label>
          <input id="destination" type="text" value={destination}
                 onChange={(e) => setDestination(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="dep">Departure time</label>
          <input id="dep" type="datetime-local" value={departure}
                 onChange={(e) => setDeparture(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="prio">Priority</label>
          <select id="prio" value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="balanced">Balanced</option>
            <option value="safest">Safest</option>
            <option value="fastest">Fastest</option>
            <option value="lowest_exposure">Lowest exposure</option>
          </select>
        </div>
        <div className="btn-row">
          <button className="btn" type="submit" disabled={loading}>
            Assess journey
          </button>
          <button type="button" className="demo-btn"
                  onClick={() => assess({
                    origin: "Lagos", destination: "Ibadan",
                    departure_time: "2026-08-24T21:00:00Z", priority,
                  })}>
            Demo: night departure 21:00
          </button>
          <button type="button" className="demo-btn"
                  onClick={() => assess({ origin: "Lagos", destination: "Ibadan" })}>
            Demo: conversational flow (no time)
          </button>
        </div>
      </form>

      <LoadingStages active={loading} />
      {error && <ErrorPanel error={error} />}

      {result?.status === "CLARIFICATION_NEEDED" && (
        <div className="card" role="status">
          <TrustTag kind="INFERENCE" />{" "}
          <strong>{result.question}</strong>
          <p className="muted" style={{ marginBottom: 0 }}>
            Your route (<b>{result.context_retained.origin}</b> →{" "}
            <b>{result.context_retained.destination}</b>) is retained — only the
            missing detail is requested (§14-15). Pick a departure time above
            and re-submit.
          </p>
        </div>
      )}

      {result?.status === "COMPLETE" && (
        <article className="result-card">
          <header className="result-head">
            <h2 style={{ margin: 0, fontSize: "1.15rem" }}>Journey assessment</h2>
            <ConfidenceMeter level={result.confidence} />
          </header>
          <p className="answer">{result.answer}</p>
          <p className="interpretation">
            <TrustTag kind="INFERENCE" />
            {result.interpretation.replace(/^INFERENCE:\s*/, "")}
          </p>
          {result.ai_narrative && (
            <p className="interpretation">
              <TrustTag kind="INFERENCE" />
              {result.ai_narrative.text}{" "}
              <span className="muted mono" style={{ fontSize: ".72rem" }}>
                ({result.ai_narrative.model_used} · {result.ai_narrative.mode} mode)
              </span>
            </p>
          )}
          <p className="recommended"><strong>Recommended:</strong> {result.recommended_action}</p>

          {result.review_route && (
            <p className="review-route" title="Part 18 D1 — journey advisories are a high-stakes surface and stay human-gated">
              🧭 Review lane: <strong>{result.review_route === "MANDATORY_REVIEW"
                ? "human review queue (high-stakes surface)"
                : result.review_route === "AUDIT_SAMPLE"
                ? "published + random 5% QA audit"
                : "auto-published (high confidence · low stakes)"}</strong>
            </p>
          )}
          {result.data_mode === "offline-fixture" && (
            <p className="muted" role="status" style={{ fontSize: ".85rem", margin: "8px 0 0" }}>
              ⚠ Live map services unavailable — shown using the seeded corridor
              (staleness visible, §20). Results remain hedged.
            </p>
          )}
          {result.route_summary && (
            <p className="sources-line" style={{ marginTop: 8 }}>
              ROUTE: {result.route_summary.total_km} km · ~
              {Math.round(result.route_summary.total_min)} min ·{" "}
              {result.route_summary.origin} → {result.route_summary.destination}
            </p>
          )}

          <div className="detail-section">
            <h4>Journey map (§1.5 — OpenStreetMap & Leaflet)</h4>
            <JourneyMap geometry={result.route_geometry ?? null}
                        segments={result.risk_timeline}
                        dataMode={result.data_mode} />
          </div>

          <div className="detail-section">
            <h4>Risk timeline</h4>
            <RiskTimeline segments={result.risk_timeline} />
          </div>

          <div className="detail-section">
            <h4>Route options — explicit trade-offs (§8)</h4>
            {result.route_options.map((o, i) => (
              <div key={o.route} className={`route-card ${i === 0 ? "recommended" : ""}`}>
                <strong>{i === 0 ? "★ Recommended — " : ""}{o.route}</strong>
                <div className="route-grid">
                  <div>Travel time<b>{o.travel_time_min} min</b></div>
                  <div>Safety score<b>{o.safety_score.toFixed(3)}</b> (lower = safer)</div>
                  <div>High-risk exposure<b>{o.exposure_km_high_risk} km</b></div>
                </div>
                <p className="muted" style={{ margin: 0 }}><em>{o.trade_off}</em></p>
              </div>
            ))}
          </div>

          <div className="detail-section">
            <h4>Predictive outlook (hedged — §9)</h4>
            {result.prediction.map((p) => (
              <div key={p.segment} className="evidence-item">
                <div className="head" style={{ gap: 10 }}>
                  <strong>{p.segment}</strong>
                  <span className={`badge ${p.predicted_risk.toLowerCase()}`}>
                    {p.predicted_risk}
                  </span>
                  <span className="muted mono" style={{ fontSize: ".75rem" }}>
                    model confidence: {p.confidence}
                  </span>
                </div>
                <p className="excerpt">{p.language}</p>
                <div className="meta">basis: {p.basis} · factors —
                  day {p.factors.day_of_week}, time {p.factors.time_of_day},
                  trend {p.factors.recent_trend}, weather {p.factors.weather}</div>
              </div>
            ))}
          </div>

          <div className="detail-section">
            <h4>Reasoning trace</h4>
            <ReasoningTrace steps={result.reasoning_trace} />
          </div>
          <p className="caveat">What would change this: {result.what_would_change_conclusion}</p>
        </article>
      )}
    </section>
  );
}

export function RiskTimeline({ segments }: { segments: JourneySegmentRisk[] }) {
  return (
    <ol className="timeline" role="list">
      {segments.map((s, i) => (
        <li key={i} className={`risk-${s.risk}`}
            style={{ borderLeftColor: RISK_COLOR[s.risk] }}>
          <time>{s.time}</time>
          <strong>{s.segment}</strong>
          <span className={`badge ${s.risk.toLowerCase()}`}>{s.risk}</span>
          <p className="why">{s.why}</p>
        </li>
      ))}
    </ol>
  );
}
