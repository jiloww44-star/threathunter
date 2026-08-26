// Unified Ops Node v3 — spec A-01/A-15, §3.1–3.3, §6.
// Single-pane-of-glass: Conversational Cortex (dialogue → task trees) +
// Strategy Map + Task Matrix + Swarm Timeline + verdict-change alerts +
// Intel Feed + Sovereign KPIs. Canonical §6 spine on every report.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ApiError } from "../api";
import type {
  AgentInfo, CortexReply, MeshStatus, OpsKpis, OpsNotification,
  RecentCheck, StrategyMap, TaskStatus, UnifiedReport,
} from "../types";
import { ConfidenceMeter, ErrorPanel, TrustTag } from "../components/shared";

const STATUS_META: Record<TaskStatus, { icon: string; label: string }> = {
  COMPLETE: { icon: "✓", label: "done" },
  DEGRADED: { icon: "⚠", label: "degraded" },
  FAILED: { icon: "✕", label: "failed" },
  BLOCKED: { icon: "⛔", label: "blocked by governance" },
  AWAITING_HUMAN: { icon: "⏸", label: "awaiting human" },
  RUNNING: { icon: "…", label: "running" },
  PENDING: { icon: "·", label: "pending" },
};

interface ChatMsg {
  role: "user" | "cortex";
  text: string;
  progress?: string[];
  context?: Record<string, string | null>;
}

type Pane = "strategy" | "timeline" | "alerts" | "feed" | "kpis";

function newSessionId(): string {
  return `ui-${Math.random().toString(36).slice(2, 10)}-${Date.now()
    .toString(36)}`;
}

export function OpsNode() {
  const [sessionId] = useState(newSessionId);
  const [messages, setMessages] = useState<ChatMsg[]>([{
    role: "cortex",
    text: "I'm the ThreatHunter360 cortex. Ask me to check a claim, advise "
      + "on a journey, screen an entity, or run a security sweep — in your "
      + "own words. One-shot goals decompose instantly; conversation keeps "
      + "context (§3.1).",
  }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [report, setReport] = useState<UnifiedReport | null>(null);
  const [tree, setTree] = useState<StrategyMap | null>(null);
  const [treeList, setTreeList] = useState<{ trees: Array<{
    tree_id: string; goal: string; status: string; peer_id: string;
    created_at: string; }> } | null>(null);
  const [mesh, setMesh] = useState<MeshStatus | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [alerts, setAlerts] = useState<OpsNotification[]>([]);
  const [feed, setFeed] = useState<RecentCheck[]>([]);
  const [kpis, setKpis] = useState<OpsKpis | null>(null);
  const [pane, setPane] = useState<Pane>("strategy");
  const chatEnd = useRef<HTMLDivElement>(null);

  const refreshPanels = useCallback(async () => {
    const [m, a, n, k, f, tl] = await Promise.all([
      api.opsMesh().catch(() => null),
      api.opsAgents().catch(() => null),
      api.opsNotifications().catch(() => null),
      api.opsKpis().catch(() => null),
      api.recent().catch(() => null),
      api.opsTrees().catch(() => null),
    ]);
    if (m) setMesh(m);
    if (a) setAgents(a.agents);
    if (n) setAlerts(n.notifications);
    if (k) setKpis(k);
    if (f) setFeed(f);
    if (tl) setTreeList(tl);
  }, []);

  useEffect(() => { refreshPanels(); }, [refreshPanels]);

  const loadTree = useCallback(async (treeId: string) => {
    const t = await api.opsTree(treeId).catch(() => null);
    if (t) setTree(t);
  }, []);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    try {
      const r: CortexReply = await api.cortexChat(sessionId, text);
      setMessages((m) => [...m, {
        role: "cortex", text: r.text, progress: r.progress,
        context: r.context,
      }]);
      if (r.report) setReport(r.report);
      if (r.tree_id) await loadTree(r.tree_id);
      refreshPanels();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const fireGoal = async (goal: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", text: `⚡ ${goal}` }]);
    try {
      const r = await api.opsGoal(goal);
      setReport(r);
      await loadTree(r.tree_id);
      setMessages((m) => [...m, {
        role: "cortex",
        text: `${r.answer}\n\nConfidence: ${r.confidence.replace("_", " ")}. `
          + r.recommended_action,
      }]);
      refreshPanels();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const runReassess = async () => {
    setBusy(true);
    try {
      await api.opsReassess();
      await refreshPanels();
      setPane("alerts");
    } finally {
      setBusy(false);
    }
  };

  const activeTrees = treeList?.trees ?? [];

  return (
    <section aria-labelledby="ops-title">
      <header className="view-head">
        <p className="view-kicker">v3.0 SOVEREIGN FUSION · Unified Ops Node</p>
        <h1 id="ops-title">◈ Ops Node</h1>
        <p className="view-lede">
          Talk to the swarm. Every message decomposes into a governed task
          tree; every report follows the canonical spine — answer, confidence,
          evidence, contradictions, action, sources (§6). Humans stay in
          command: external-effect actions always pause for approval (§27).
        </p>
      </header>

      {/* mesh strip (§3.3) */}
      {mesh && (
        <div className="mesh-strip" role="status"
             aria-label="Orchestration mesh status">
          <span className="mesh-peer primary">⬢ {mesh.primary}</span>
          {mesh.peers.filter((p) => p.peer_id !== mesh.primary).map((p) => (
            <span key={p.peer_id} className="mesh-peer">⬡ {p.peer_id}</span>
          ))}
          <span className="mesh-peer">failovers: {mesh.failovers}</span>
          <span className="mesh-peer mono">{mesh.policy_version}</span>
          {kpis && (
            <span className="mesh-peer">
              tasks {kpis.tasks_total} · queue {kpis.review_queue_depth} ·
              alerts {kpis.notifications_total}
            </span>
          )}
        </div>
      )}

      <div className="ops-grid">
        {/* ---------------- Conversational Cortex (§3.1) ---------------- */}
        <div className="card ops-chat" aria-label="Conversational Cortex">
          <h3 style={{ marginTop: 0 }}>💬 Conversational Cortex</h3>
          <div className="chat-log" aria-live="polite">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>
                <p>{m.text}</p>
                {m.context && (m.context.origin || m.context.intent) && (
                  <div className="context-chips">
                    {m.context.origin && (
                      <span className="chip">
                        {m.context.origin} → {m.context.destination ?? "?"}
                      </span>
                    )}
                    {m.context.departure_hint && (
                      <span className="chip">🕒 {m.context.departure_hint}</span>
                    )}
                    {m.context.journey_context === "active" && (
                      <span className="chip">journey context held</span>
                    )}
                  </div>
                )}
                {m.progress && m.progress.length > 0 && (
                  <details className="progress-lines">
                    <summary>Swarm activity ({m.progress.length})</summary>
                    <ul>
                      {m.progress.map((l, j) => <li key={j}>{l}</li>)}
                    </ul>
                  </details>
                )}
              </div>
            ))}
            {busy && (
              <div className="chat-msg cortex">
                <p className="muted">swarm working…</p>
              </div>
            )}
            <div ref={chatEnd} />
          </div>
          <form className="chat-input" onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}>
            <label className="sr-only" htmlFor="cortex-input">Message the cortex</label>
            <input id="cortex-input" type="text" value={input}
                   placeholder="e.g. I'm travelling tomorrow · Is the airport rumour true? · Secure the IoT fleet"
                   onChange={(e) => setInput(e.target.value)} />
            <button className="btn" type="submit" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
          <div className="btn-row">
            <button type="button" className="demo-btn" disabled={busy}
                    onClick={() => fireGoal("Secure the Lagos IoT deployment — scan for vulnerabilities")}>
              ⚡ Demo: security sweep
            </button>
            <button type="button" className="demo-btn" disabled={busy}
                    onClick={() => send("I'm traveling tomorrow")}>
              ⚡ Demo: journey dialogue
            </button>
            <button type="button" className="demo-btn" disabled={busy}
                    onClick={runReassess} title="§1.10 continual reassessment">
              ↻ Reassess now
            </button>
          </div>
        </div>

        {/* ------------------- right pane: tabs ------------------- */}
        <div className="ops-side">
          <nav className="pane-tabs" aria-label="Ops panes">
            {(["strategy", "timeline", "alerts", "feed", "kpis"] as Pane[]).map((p) => (
              <button key={p} type="button"
                      className={pane === p ? "active" : ""}
                      onClick={() => setPane(p)}>
                {{ strategy: "Strategy Map", timeline: "Timeline",
                   alerts: `Alerts${alerts.length ? ` (${alerts.length})` : ""}`,
                   feed: "Intel Feed", kpis: "KPIs" }[p]}
              </button>
            ))}
          </nav>

          {error && <ErrorPanel error={error} />}

          {pane === "strategy" && (
            <div className="card" aria-label="Strategy Map">
              {tree ? (
                <>
                  <h3 style={{ marginTop: 0 }}>🗺 Strategy Map</h3>
                  <p className="muted" style={{ marginTop: 0 }}>
                    <span className="mono">{tree.tree_id}</span> · peer{" "}
                    <span className="mono">{tree.peer_id}</span> · status{" "}
                    <strong>{tree.status}</strong>
                  </p>
                  <p style={{ fontWeight: 600 }}>{tree.goal}</p>
                  <ol className="strategy-tree">
                    {tree.tasks.map((t) => {
                      const meta = STATUS_META[t.status] ?? STATUS_META.PENDING;
                      return (
                        <li key={t.task_id}
                            className={`task-item st-${t.status.toLowerCase()}`}
                            style={{
                              marginLeft: t.parent_id ? 22 : 0,
                            }}>
                          <span className="task-icon" aria-hidden="true">
                            {meta.icon}
                          </span>
                          <span className="task-agent">{t.agent}</span>
                          <span className="task-title">{t.title}</span>
                          <span className="task-status">{meta.label}
                            {t.classified_error
                              ? ` · ${t.classified_error}` : ""}
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                </>
              ) : (
                <p className="muted">Run a goal or chat with the cortex — the
                Strategy Map renders the live task tree here (A-15).</p>
              )}
            </div>
          )}

          {pane === "timeline" && (
            <div className="card" aria-label="Swarm Timeline and Task Matrix">
              <h3 style={{ marginTop: 0 }}>⏱ Swarm Timeline</h3>
              {activeTrees.length === 0 && (
                <p className="muted">No task trees yet.</p>
              )}
              <ol className="timeline" role="list">
                {activeTrees.map((t) => (
                  <li key={t.tree_id} className="risk-MODERATE"
                      style={{ cursor: "pointer" }}
                      onClick={() => { loadTree(t.tree_id); setPane("strategy"); }}>
                    <time className="mono">{t.tree_id.slice(0, 8)}</time>
                    <strong>{t.status}</strong>
                    <span className="badge moderate">{
                      t.peer_id}</span>
                    <p className="why">{t.goal}</p>
                  </li>
                ))}
              </ol>
              {tree && (
                <>
                  <h4>Task Matrix — {tree.tree_id.slice(0, 8)}</h4>
                  <table className="task-matrix">
                    <thead>
                      <tr><th>Agent</th><th>Function</th><th>Status</th></tr>
                    </thead>
                    <tbody>
                      {tree.tasks.map((t) => (
                        <tr key={t.task_id}>
                          <td>{t.agent}</td>
                          <td className="mono">{t.function}</td>
                          <td>{STATUS_META[t.status]?.icon} {
                            STATUS_META[t.status]?.label ?? t.status}
                            {t.classified_error
                              ? <span className="muted"> · {t.classified_error}</span>
                              : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}

          {pane === "alerts" && (
            <div className="card" aria-label="Verdict-change alerts">
              <h3 style={{ marginTop: 0 }}>🔔 Verdict-change alerts (§1.10)</h3>
              {alerts.length === 0 && (
                <p className="muted">No changes detected yet. When new evidence
                moves a verdict or a monitored journey's risk, it lands here —
                never silently.</p>
              )}
              {alerts.map((n) => (
                <div key={n.id} className="evidence-item">
                  <div className="head">
                    <span className={`badge ${n.kind === "RISK_ELEVATION" ||
                      n.kind === "VERDICT_CHANGE" ? "high" : "low"}`}>
                      {n.kind.replace("_", " ")}
                    </span>
                    <strong>{n.title}</strong>
                  </div>
                  <p className="excerpt">{n.body}</p>
                  <div className="meta">{new Date(n.created_at)
                    .toLocaleString()}</div>
                </div>
              ))}
            </div>
          )}

          {pane === "feed" && (
            <div className="card" aria-label="Intel Feed">
              <h3 style={{ marginTop: 0 }}>📡 Intel Feed (restored v1 §3)</h3>
              {feed.map((c) => (
                <div key={c.check_id} className="evidence-item">
                  <div className="head">
                    <span className="badge moderate">{c.module}</span>
                    <strong>{c.outcome}</strong>
                  </div>
                  <p className="excerpt">{c.subject}</p>
                  <div className="meta">
                    confidence {c.confidence.replace("_", " ")} ·{" "}
                    {new Date(c.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}

          {pane === "kpis" && kpis && (
            <div className="card" aria-label="Sovereign KPIs">
              <h3 style={{ marginTop: 0 }}>📊 Sovereign statistics (§3.3)</h3>
              <div className="kpi-grid">
                <div className="kpi"><b>{kpis.tasks_total}</b>tasks</div>
                <div className="kpi"><b>{kpis.review_queue_depth}</b>human queue</div>
                <div className="kpi"><b>{kpis.mesh_failovers}</b>failovers</div>
                <div className="kpi"><b>{kpis.notifications_total}</b>alerts</div>
              </div>
              <h4>Per-agent latency</h4>
              <table className="task-matrix">
                <thead><tr><th>Agent</th><th>Tasks</th><th>Avg latency</th></tr></thead>
                <tbody>
                  {Object.entries(kpis.per_agent).map(([a, v]) => (
                    <tr key={a}>
                      <td>{a}</td><td>{v.tasks}</td>
                      <td className="mono">{v.avg_latency_s}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h4>Task status mix</h4>
              <p className="muted mono" style={{ fontSize: ".8rem" }}>
                {Object.entries(kpis.task_status_mix)
                  .map(([k, v]) => `${k}=${v}`).join("  ")}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ------------- canonical spine report (§6, progressive §19) -------- */}
      {report && (
        <article className="result-card" aria-label="Unified report">
          <header className="result-head">
            <h2 style={{ margin: 0, fontSize: "1.15rem" }}>Unified Report</h2>
            <ConfidenceMeter level={report.confidence} />
          </header>
          <p className="answer">{report.answer}</p>
          <p className="interpretation">
            <TrustTag kind="INFERENCE" />
            {report.interpretation.replace(/^INFERENCE:\s*/, "")}
          </p>
          <p className="recommended">
            <strong>Recommended:</strong> {report.recommended_action}
          </p>

          {report.degraded.length > 0 && (
            <div className="detail-section" role="status">
              <h4>⚠ Honest degradation (§20)</h4>
              {report.degraded.map((d, i) => (
                <p key={i} className="muted" style={{ margin: "4px 0" }}>
                  {d.agent}.{d.function} — {d.state}
                  {d.classified_error ? ` (${d.classified_error})` : ""}: {d.note}
                </p>
              ))}
            </div>
          )}

          <div className="detail-section">
            <h4>Key evidence</h4>
            {report.key_evidence.map((e, i) => (
              <div key={i} className="evidence-item">
                <div className="head">
                  <TrustTag kind={e.trust_label === "FACT" ? "FACT" : "INFERENCE"} />
                  <span className="task-agent">{e.agent}</span>
                </div>
                <p className="excerpt">{e.text}</p>
              </div>
            ))}
            {report.key_evidence.length === 0 && (
              <p className="muted">No evidence items — see task states.</p>
            )}
          </div>

          {report.contradictions.length > 0 && (
            <div className="detail-section">
              <h4>Contradictions (global §1.8 monitor)</h4>
              {report.contradictions.map((c, i) => (
                <div key={i} className="evidence-item">
                  <div className="head">
                    <span className={`badge ${c.severity.toLowerCase()}`}>
                      {c.severity}
                    </span>
                    <span className="task-agent">{c.agent}</span>
                  </div>
                  <p className="excerpt">{c.description}</p>
                </div>
              ))}
            </div>
          )}

          {report.compliance_notices.length > 0 && (
            <div className="detail-section">
              <h4>Compliance & governance notices (AUDITOR overlay)</h4>
              <ul>
                {report.compliance_notices.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}

          <p className="sources-line">
            SOURCES: agents consulted — {report.sources.agents_consulted.join(", ")}
            {" "}· policy {report.sources.policy_version}
          </p>
          <p className="caveat">
            What would change this: {report.what_would_change_conclusion}
          </p>
        </article>
      )}

      {/* ------------------------- agent roster strip ---------------------- */}
      <details className="card" style={{ marginTop: 18 }}>
        <summary><strong>Agent roster & A-14 function allowlists</strong></summary>
        <div className="roster-grid">
          {agents.map((a) => (
            <div key={a.agent_id} className="roster-card">
              <div className="head">
                <strong>{a.name}</strong>
                <span className={`badge ${a.status === "ACTIVE" ? "low" : "moderate"}`}>
                  {a.status}
                </span>
              </div>
              <p className="muted" style={{ margin: "4px 0" }}>{a.role}</p>
              <p style={{ margin: "4px 0", fontSize: ".85rem" }}>{a.description}</p>
              <p className="mono" style={{ fontSize: ".72rem", margin: "4px 0" }}>
                {a.api_functions.join(" · ")}
              </p>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
