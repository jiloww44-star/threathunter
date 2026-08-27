// Home — spec §18: three capabilities immediately visible + Part 1 "Recent
// Checks & Statistics" module + Part 4.4 monitoring metrics.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { RecentCheck, Statistics } from "../types";

const CAPABILITIES = [
  {
    icon: "🔍", title: "Fact Checker", qs: "“Is this claim true?”",
    body: "Verdict + confidence against provenanced, independence-scored evidence.",
    href: "#/fact-check",
  },
  {
    icon: "🛡️", title: "Journey Advisor", qs: "“Is my journey safe?”",
    body: "Per-segment risk timeline fused from weather, incidents and traffic.",
    href: "#/journey",
  },
  {
    icon: "🪪", title: "KYC Verify", qs: "“Verify my identity”",
    body: "Guided 6-step verification. Anomalies trigger review — never accusations.",
    href: "#/kyc",
  },
];

export function Home() {
  const [stats, setStats] = useState<Statistics | null>(null);
  const [recent, setRecent] = useState<RecentCheck[]>([]);

  useEffect(() => {
    api.statistics().then(setStats).catch(() => {});
    api.recent().then(setRecent).catch(() => {});
  }, []);

  return (
    <section>
      <div className="hero">
        <p className="view-kicker">Inductive intelligence platform</p>
        <h1>Welcome to ThreatHunter360</h1>
        <p>
          Fragmented information → evidence-based conclusions → honest
          uncertainty → actionable decisions. Facts stay separated from
          inference; we admit what we don't know.
        </p>
      </div>

      <div className="capability-grid">
        {CAPABILITIES.map((c) => (
          <a key={c.title} className="cap-card" href={c.href}>
            <div className="icon" aria-hidden="true">{c.icon}</div>
            <h3>{c.title}</h3>
            <span className="qs">{c.qs}</span>
            <p>{c.body}</p>
          </a>
        ))}
      </div>

      <h2 className="section-title">Live platform statistics</h2>
      <div className="stats-strip">
        <Stat n={stats?.total_checks ?? "—"} l="Intelligence checks run" />
        <Stat n={stats?.sources_active ?? "—"} l="Active sources" />
        <Stat n={stats?.evidence_items ?? "—"} l="Evidence items indexed" />
        <Stat n={stats ? stats.copy_chain_ratio : "—"} l="Copy-chain ratio" mono />
        <Stat n={stats?.review_queue_depth ?? "—"} l="Human review queue (§27)" />
        <Stat
          n={stats ? `${Math.round(stats.avg_confidence_score * 100)}%` : "—"}
          l="Avg. confidence score"
        />
      </div>

      {stats && (
        <div className="card" style={{ marginTop: 14 }}>
          <h4 style={{ margin: "0 0 8px" }}>Source freshness & model governance</h4>
          <div className="mono" style={{ fontSize: ".78rem", display: "grid", gap: 4 }}>
            {Object.entries(stats.source_freshness_lag_min).map(([s, lag]) => (
              <div key={s}>
                {s}: {lag < 0 ? "never fetched" : `${lag} min ago`}
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize: ".78rem", marginTop: 8 }}>
            models: {Object.entries(stats.model_versions)
              .map(([k, v]) => `${k}@${v}`).join(" · ")}
          </div>
        </div>
      )}

      <h2 className="section-title">Recent checks</h2>
      <div className="card" style={{ marginTop: 0 }}>
        {recent.length === 0 && (
          <p className="muted">No checks yet — run your first fact check above.</p>
        )}
        {recent.map((c) => (
          <div className="recent-item" key={c.check_id}>
            <span className="mod">{c.module}</span>
            <span>{c.subject.length > 70 ? c.subject.slice(0, 68) + "…" : c.subject}</span>
            <strong>{c.outcome.replace(/_/g, " ")}</strong>
            <span className="time">{new Date(c.created_at).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Stat({ n, l, mono }: { n: number | string; l: string; mono?: boolean }) {
  return (
    <div className="stat">
      <div className="n">{typeof n === "number" && mono ? n.toFixed(2) : n}</div>
      <div className="l">{l}</div>
    </div>
  );
}
