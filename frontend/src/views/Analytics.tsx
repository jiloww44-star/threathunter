// Analytics dashboard — spec §4.3 (in-app visualization) + §4.2 data-sheet
// export. Trust metrics first-class: source independence ratio, verdict mix,
// spend vs volume.
import { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip,
  XAxis, YAxis, ZAxis,
} from "recharts";
import { api } from "../api";
import type { AnalyticsSummary } from "../types";

const fmtUsd = (v: number) => v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;

function KPI({ label, value, delta }: {
  label: string; value: string | number; delta?: number | null | string;
}) {
  return (
    <div className="stat">
      <div className="n">{value}</div>
      <div className="l">{label}
        {delta !== undefined && delta !== null && (
          <span style={{
            marginLeft: 6,
            color: Number(delta) >= 0 ? "var(--color-risk-low)" : "var(--color-risk-mod)",
          }}>
            {Number(delta) >= 0 ? "▲" : "▼"} {Math.abs(Number(delta) * 100).toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
}

function ChartCard({ title, children }: {
  title: string; children: React.ReactNode;
}) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h4 style={{ margin: "0 0 10px" }}>{title}</h4>
      <div style={{ width: "100%", height: 260 }}>{children}</div>
    </div>
  );
}

export function Analytics() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [err, setErr] = useState(false);
  const [queue, setQueue] = useState<{ depth: number; by_tier: Record<string, number> } | null>(null);
  const [health, setHealth] = useState<Array<{
    source_id: string; health_score: number | null; health_note: string | null;
    authority: string; last_success_at: string | null;
  }> | null>(null);

  useEffect(() => {
    setErr(false);
    api.analyticsSummary(days).then(setData).catch(() => setErr(true));
  }, [days]);
  useEffect(() => {
    api.reviewQueue().then(setQueue).catch(() => {});
    api.sourceHealth().then((d) => setHealth(d.sources)).catch(() => {});
  }, []);

  const daily = useMemo(() => data?.daily ?? [], [data]);
  const text = {
    stroke: "#94a3b8", fontSize: 11, fontFamily: "var(--font-mono)",
  };

  return (
    <section aria-labelledby="an-title">
      <header className="view-head">
        <p className="view-kicker">Module · Operations &amp; cost telemetry</p>
        <h1 id="an-title">📊 Analytics</h1>
        <p className="view-lede">
          Checks, verdict mix, cost and trust metrics — the analytics_daily view
          (§4.1) feeding KPI cards and the exportable data sheet.
        </p>
      </header>

      <div className="btn-row">
        {[7, 30, 90].map((d) => (
          <button key={d}
                  className={days === d ? "btn" : "btn secondary"}
                  onClick={() => setDays(d)}>
            {d} days
          </button>
        ))}
        <a className="btn secondary" download
           href={api.analyticsExportUrl("csv", days)}>⬇ CSV</a>
        <a className="btn secondary" download
           href={api.analyticsExportUrl("xlsx", days)}>⬇ XLSX</a>
      </div>

      {err && (
        <p className="muted" style={{ marginTop: 12 }}>
          Analytics unavailable — run some checks first, then reload.
        </p>
      )}

      {data && (
        <>
          <div className="stats-strip">
            <KPI label={`Checks (${days}d)`} value={data.kpis.checks_total}
                 delta={data.kpis.wow_change} />
            <KPI label="Avg confidence" value={data.kpis.avg_confidence.toFixed(2)} />
            <KPI label="LLM + scrape spend" value={fmtUsd(data.kpis.llm_cost_usd)} />
            <KPI label="Cost / check" value={`$${data.kpis.cost_per_check.toFixed(4)}`} />
            <KPI label="Copy-chain ratio" value={data.kpis.copy_chain_ratio.toFixed(2)} />
            <KPI label="Human review queue" value={data.kpis.review_queue_depth} />
          </div>

          {daily.length === 0 && (
            <div className="card" style={{ marginTop: 16 }}>
              <p className="muted" style={{ margin: 0 }}>
                No activity in this window yet — run a fact check or journey
                assessment and the series appears here.
              </p>
            </div>
          )}

          {daily.length > 0 && (
            <>
              <ChartCard title="Verdict mix (stacked)">
                <ResponsiveContainer>
                  <AreaChart data={daily} margin={{ top: 6, right: 12, left: -18 }}>
                    <CartesianGrid stroke="#33415533" />
                    <XAxis dataKey="day" tick={text} tickFormatter={(d) => d.slice(5)} />
                    <YAxis allowDecimals={false} tick={text} />
                    <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Area type="monotone" dataKey="verified" stackId="v"
                          name="Verified" stroke="#22c55e" fill="#22c55e33" />
                    <Area type="monotone" dataKey="unverified" stackId="v"
                          name="Unverified" stroke="#94a3b8" fill="#94a3b833" />
                    <Area type="monotone" dataKey="false_or_misleading" stackId="v"
                          name="False / misleading" stroke="#ef4444" fill="#ef444433" />
                  </AreaChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard title="Cost vs volume (aim: spot expensive days early)">
                <ResponsiveContainer>
                  <ScatterChart margin={{ top: 6, right: 12, left: -10, bottom: 4 }}>
                    <CartesianGrid stroke="#33415533" />
                    <XAxis dataKey="checks_total" name="checks" tick={text}
                           allowDecimals={false} />
                    <YAxis dataKey="llm_cost_usd" name="cost $" tick={text}
                           tickFormatter={(v) => fmtUsd(v)} />
                    <ZAxis range={[60, 60]} />
                    <Tooltip cursor={{ strokeDasharray: "3 3" }}
                             contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} />
                    <Scatter data={daily.filter((d) => !d.outlier)} fill="#2563eb"
                             name="normal" />
                    <Scatter data={daily.filter((d) => d.outlier)} fill="#ef4444"
                             name="outlier" />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                  </ScatterChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard title="Independent source ratio (target ≥ 0.6 — §1.6 trust metric)">
                <ResponsiveContainer>
                  <LineChart data={daily} margin={{ top: 6, right: 12, left: -18 }}>
                    <CartesianGrid stroke="#33415533" />
                    <XAxis dataKey="day" tick={text} tickFormatter={(d) => d.slice(5)} />
                    <YAxis domain={[0, 1]} tick={text} />
                    <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} />
                    <ReferenceLine y={0.6} stroke="#f59e0b" strokeDasharray="4 4"
                                   label={{ value: "target 0.6", fill: "#f59e0b", fontSize: 11 }} />
                    <Line type="monotone" dataKey="avg_source_diversity"
                          stroke="#8b5cf6" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </ChartCard>

              <div className="card" style={{ marginTop: 16 }}>
                <h4 style={{ margin: "0 0 10px" }}>Spend ledger (Part E governance)</h4>
                <div className="mono" style={{ fontSize: ".8rem", display: "grid", gap: 4 }}>
                  <div>total: <b>{fmtUsd(data.budget.total_usd)}</b> across {data.budget.calls} call(s)</div>
                  {Object.entries(data.budget.by_purpose_usd).map(([k, v]) => (
                    <div key={k}>{k}: {fmtUsd(v)}</div>
                  ))}
                  {Object.keys(data.budget.by_purpose_usd).length === 0 && (
                    <div className="muted">zero spend — running fully on free/deterministic paths</div>
                  )}
                </div>
              </div>

              {queue && (
                <div className="card" style={{ marginTop: 16 }}>
                  <h4 style={{ margin: "0 0 10px" }}>Review lanes (Part 18 D1 — TRUST.md)</h4>
                  <p className="muted" style={{ margin: "0 0 10px", fontSize: ".85rem" }}>
                    Attention scales with uncertainty, not volume. KYC items are
                    never sampled — identity stays exhaustive by design.
                  </p>
                  <div className="mono" style={{ fontSize: ".8rem", display: "grid", gap: 4 }}>
                    <div>open items: <b>{queue.depth}</b></div>
                    {Object.entries(queue.by_tier).map(([tier, n]) => (
                      <div key={tier}>{tier}: <b>{n}</b></div>
                    ))}
                    {queue.depth === 0 && <div className="muted">queue empty</div>}
                  </div>
                </div>
              )}

              {health && health.length > 0 && (
                <div className="card" style={{ marginTop: 16 }}>
                  <h4 style={{ margin: "0 0 10px" }}>Source health scorecard (§U1)</h4>
                  <p className="muted" style={{ margin: "0 0 10px", fontSize: ".85rem" }}>
                    Auto-scored after every ingest; SLA breach or health &lt; 0.45
                    auto-demotes a PRIMARY source and pings a curator.
                  </p>
                  <div className="mono" style={{ fontSize: ".8rem", display: "grid", gap: 4 }}>
                    {health.map((s) => (
                      <div key={s.source_id}>
                        {s.source_id}: <b>{s.health_score?.toFixed(2) ?? "—"}</b>
                        {" "}{s.authority}
                        {s.health_note?.includes("auto-demoted") && (
                          <span style={{ color: "var(--color-risk-mod)" }}> · demoted</span>
                        )}
                        {s.health_note?.includes("auto-recovered") && (
                          <span style={{ color: "var(--color-risk-low)" }}> · recovered</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
