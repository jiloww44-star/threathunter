// Unified Ops Node v3 — spec A-01/A-15, §3.1–3.3, §6.
// Single-pane-of-glass: Conversational Cortex (dialogue → task trees) +
// Strategy Map + Task Matrix + Swarm Timeline + verdict-change alerts +
// Intel Feed + Sovereign KPIs. Canonical §6 spine on every report.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ApiError } from "../api";
import type {
  AgentInfo, CaseChronology, CortexReply, DorkSet, GraphData, Incident,
  Investigation, KpiValue, LiveObservation, LockerResponse, MeshStatus,
  OpsKpis, OpsKpisV71, OpsNotification, PlanProposal, RecentCheck,
  RerouteRow, ReviewItem, StrategyMap, TaskStatus, UnifiedReport,
} from "../types";
import { ConfidenceMeter, ErrorPanel, TrustTag } from "../components/shared";
import { EvidenceGraph } from "../components/EvidenceGraph";

const STATUS_META: Record<TaskStatus, { icon: string; label: string }> = {
  COMPLETE: { icon: "✓", label: "done" },
  DEGRADED: { icon: "⚠", label: "degraded" },
  FAILED: { icon: "✕", label: "failed" },
  BLOCKED: { icon: "⛔", label: "blocked by governance" },
  AWAITING_HUMAN: { icon: "⏸", label: "awaiting human" },
  HALTED: { icon: "■", label: "halted by user" },
  RUNNING: { icon: "…", label: "running" },
  PENDING: { icon: "·", label: "pending" },
};

const ONBOARD_KEY = "th360.onboarded";

interface ChatMsg {
  role: "user" | "cortex";
  text: string;
  progress?: string[];
  context?: Record<string, string | null>;
}

type Pane = "strategy" | "timeline" | "alerts" | "feed" | "kpis" | "stream"
  | "cases" | "locker" | "governance";

/** v4.0 §2 subject types — mirrors backend core.investigation.SUBJECT_TYPES */
const SUBJECT_TYPES = ["person", "organization", "domain", "ip", "url",
                       "location", "claim", "agent"];

function newSessionId(): string {
  return `ui-${Math.random().toString(36).slice(2, 10)}-${Date.now()
    .toString(36)}`;
}

// ---------- v4.5 §71/§72 pilot KPI read-out ----------
// Every metric renders its measurement basis (hover/full line). UNAVAILABLE
// is a first-class state: the platform says "we do not measure this" instead
// of showing a fabricated zero (§20 applied to telemetry itself).
const FAMILY_LABELS: Record<string, string> = {
  intelligence_quality: "🧠 Intelligence quality",
  journey: "🧭 Journey",
  fact_checker: "✅ Fact checker",
  agent_security: "🛡 Agent security",
  governance: "⚖️ Governance",
};

function V71Metric({ name, kv }: { name: string; kv: KpiValue }) {
  const label = name.replace(/_/g, " ");
  if (kv.status !== "OK" || kv.value === null) {
    return (
      <li className="v71-metric" title={kv.basis}>
        <span className="v71-name">{label}</span>
        <span className="v71-unavail">UNAVAILABLE</span>
        <span className="v71-basis">{kv.basis}</span>
      </li>
    );
  }
  return (
    <li className="v71-metric" title={kv.basis}>
      <span className="v71-name">{label}</span>
      {typeof kv.value === "number" ? (
        <b className="v71-val">
          {kv.value}
          <small className="v71-unit">{kv.unit}</small>
        </b>
      ) : (
        <span className="v71-dict mono">
          {Object.entries(kv.value)
            .map(([k, v]) => `${k}=${v}`).join(" · ")}
        </span>
      )}
      <span className="v71-sample">n={kv.sample}</span>
    </li>
  );
}

function V71Panel({ v71 }: { v71: OpsKpisV71 }) {
  const ns = v71.north_star;
  return (
    <div className="v71" aria-label="§71 platform KPIs — v4.5 pilot plane">
      <div className="v71-north" title={ns.basis}>
        <span className="v71-north-label">★ NORTH-STAR (§72)</span>
        <b>{typeof ns.value === "number" ? ns.value : "—"}</b>
        <span>evidence-backed decisions completed</span>
        <span className="v71-sample">of {ns.sample} closed cases</span>
      </div>
      {Object.entries(v71.families).map(([fam, metrics]) => (
        <section key={fam} className="v71-family">
          <h4 style={{ margin: "0 0 .3rem" }}>
            {FAMILY_LABELS[fam] ?? fam}
          </h4>
          <ul className="v71-list">
            {Object.entries(metrics).map(([m, kv]) => (
              <V71Metric key={m} name={m} kv={kv} />
            ))}
          </ul>
        </section>
      ))}
      <p className="dim" style={{ fontSize: ".75rem" }}>
        {v71.honesty_note}
      </p>
      <p className="dim mono" style={{ fontSize: ".72rem" }}>
        {v71.kpi_version} · window {v71.window_hours}h · computed{" "}
        {new Date(v71.computed_at).toLocaleString()} ·{" "}
        <a href={api.metricsUrl(v71.window_hours)} target="_blank"
           rel="noreferrer">Prometheus ↗</a>
      </p>
    </div>
  );
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
  // v3.2 safety-by-design state
  const [plan, setPlan] = useState<PlanProposal | null>(null);
  const [incident, setIncident] = useState<Incident | null>(null);
  // v4.0 §2 Investigation Core — the active case's §63 authorization
  // binds every plan/goal fired from this session.
  const [cases, setCases] = useState<Investigation[]>([]);
  const [activeCase, setActiveCase] = useState<string | null>(null);
  const [caseForm, setCaseForm] = useState({
    objective: "", subject_type: "domain", subject: "", purpose: "",
    authority: "public_research", scope: "", allowed_sources: "",
    expires_days: 30,
  });
  // v4.1 — per-case evidence-chain graphs + generated dork sets
  const [caseGraphs, setCaseGraphs] = useState<Record<string, GraphData | null>>({});
  const [caseDorks, setCaseDorks] = useState<Record<string, DorkSet | null>>({});
  // v4.1 — §73 V1 Evidence Locker pane
  const [locker, setLocker] = useState<LockerResponse | null>(null);
  const [lockerQ, setLockerQ] = useState("");
  // v4.2 — §73 V2 governance planes: approvals queue + agent inventory
  const [approvalsList, setApprovalsList] =
    useState<import("../types").ApprovalRecord[] | null>(null);
  const [inventory, setInventory] =
    useState<import("../types").AgentInventoryResponse | null>(null);
  // v4.3 — §73 V2.5 continuous assurance
  const [assurance, setAssurance] =
    useState<import("../types").AssuranceStatus | null>(null);
  const [sweepBusy, setSweepBusy] = useState(false);
  // v4.4 — §73 Enterprise plane
  const [whoami, setWhoami] =
    useState<import("../types").Whoami | null>(null);
  const [connectorsList, setConnectorsList] =
    useState<import("../types").Connector[] | null>(null);
  const [retentionRep, setRetentionRep] =
    useState<import("../types").RetentionReport | null>(null);
  // v4.6 — §71 human-outcome write-paths surfaced in Governance + Alerts
  const [reviews, setReviews] = useState<ReviewItem[] | null>(null);
  const [correctionText, setCorrectionText] = useState("");
  const [reroutes, setReroutes] = useState<RerouteRow[] | null>(null);
  const [connForm, setConnForm] = useState({
    name: "", kind: "C_data_api", base_url: "", auth_env: "" });
  // v3.5 risk #10 — interactive checklist progress (local, guidance-only)
  const [checkedSteps, setCheckedSteps] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!incident) { setCheckedSteps({}); return; }
    try {
      const raw = localStorage.getItem(
        `th360.checklist.${incident.incident_id}`);
      setCheckedSteps(raw ? JSON.parse(raw) : {});
    } catch { setCheckedSteps({}); }
  }, [incident?.incident_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleStep = (idx: number) => {
    if (!incident) return;
    const next = { ...checkedSteps, [idx]: !checkedSteps[idx] };
    setCheckedSteps(next);
    try {
      localStorage.setItem(`th360.checklist.${incident.incident_id}`,
                           JSON.stringify(next));
    } catch { /* storage unavailable — state stays in-memory */ }
  };

  // v3.5 risk #10 — crisis SIMPLIFIES the interface: only essential panes
  const crisisPanes: Pane[] = ["stream", "alerts"];
  useEffect(() => {
    if (incident && !crisisPanes.includes(pane)) setPane("stream");
  }, [incident]); // eslint-disable-line react-hooks/exhaustive-deps
  const [crisisOpen, setCrisisOpen] = useState(false);
  const [crisisSignal, setCrisisSignal] = useState<
    { phrase: string; action: string } | null>(null);  // v3.4 red-team #3
  const [sev, setSev] = useState("SEV2");
  const [sevSummary, setSevSummary] = useState("");
  const [onboarded, setOnboarded] = useState(
    () => localStorage.getItem(ONBOARD_KEY) === "1");
  const [wizardStep, setWizardStep] = useState(0);   // v3.3 §6.A
  const [stream, setStream] = useState<import("../types").StreamResponse | null>(null);

  const refreshPanels = useCallback(async () => {
    const [m, a, n, k, f, tl, inc, st] = await Promise.all([
      api.opsMesh().catch(() => null),
      api.opsAgents().catch(() => null),
      api.opsNotifications().catch(() => null),
      api.opsKpis().catch(() => null),
      api.recent().catch(() => null),
      api.opsTrees().catch(() => null),
      api.activeIncident().catch(() => null),
      api.opsStream(80).catch(() => null),     // v3.3 §3.B data stream
    ]);
    if (m) setMesh(m);
    if (a) setAgents(a.agents);
    if (n) setAlerts(n.notifications);
    if (k) setKpis(k);
    if (f) setFeed(f);
    if (tl) setTreeList(tl);
    if (inc) setIncident(inc.incident);
    if (st) setStream(st);
    api.listInvestigations().then((c) => setCases(c.investigations))
      .catch(() => null);
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
      // v3.4 red-team #3 — crisis language surfaces the REAL pathway
      if (r.crisis) setCrisisSignal(r.crisis);
      if (r.report) setReport(r.report);
      if (r.tree_id) await loadTree(r.tree_id);
      refreshPanels();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  // v3.2 checklist D — one-shot goals go through the Plan Review gate:
  // decompose → user approves → execute. Nothing runs before approval.
  const fireGoal = async (goal: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.planGoal(goal, activeCase);
      setPlan(p);
      setPane("strategy");
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  // v4.0 §2 — case lifecycle helpers
  const createCase = async () => {
    setBusy(true); setError(null);
    try {
      const inv = await api.createInvestigation({
        objective: caseForm.objective,
        subject_type: caseForm.subject_type,
        subject: caseForm.subject,
        purpose: caseForm.purpose,
        authority: caseForm.authority,
        scope: caseForm.scope,
        allowed_sources: caseForm.allowed_sources
          ? caseForm.allowed_sources.split(",").map((s) => s.trim())
              .filter(Boolean)
          : undefined,
        expires_days: caseForm.expires_days,
        user_id: "demo-user",
      });
      setCases((c) => [inv, ...c]);
      setActiveCase(inv.id);
      setCaseForm({ objective: "", subject_type: "domain", subject: "",
                    purpose: "", authority: "public_research", scope: "",
                    allowed_sources: "", expires_days: 30 });
    } catch (e) { setError(e as ApiError); } finally { setBusy(false); }
  };

  const linkCurrentTree = async (invId: string) => {
    if (!tree) return;
    setError(null);
    try {
      await api.linkInvestigation(invId, "ops_tree", tree.tree_id);
      const fresh = await api.getInvestigation(invId);
      setCases((c) => c.map((x) => (x.id === invId ? fresh : x)));
    } catch (e) { setError(e as ApiError); }
  };

  const closeCase = async (invId: string) => {
    setError(null);
    try {
      const fresh = await api.closeInvestigation(invId, "closed from Ops Node");
      setCases((c) => c.map((x) => (x.id === invId ? fresh : x)));
      if (activeCase === invId) setActiveCase(null);
    } catch (e) { setError(e as ApiError); }
  };

  // v4.1 §73 V1.5 — investigation graph: the §5 evidence chain rendered
  // with the existing EvidenceGraph (same GraphData model).
  const toggleCaseGraph = async (invId: string) => {
    if (caseGraphs[invId]) {
      setCaseGraphs((g) => ({ ...g, [invId]: null }));
      return;
    }
    try {
      const g = await api.investigationGraph(invId);
      setCaseGraphs((s) => ({ ...s, [invId]: g }));
    } catch (e) { setError(e as ApiError); }
  };

  // v4.5/4.7 — governed live observations bound to the case (§80 registry;
  // failures surface through the global ErrorPanel with their classified
  // next step, per the §20 contract).
  const [caseObs, setCaseObs] =
    useState<Record<string, LiveObservation | null>>({});
  const observeCase = async (inv: Investigation,
                             source: "crtsh" | "rdap") => {
    setError(null);
    try {
      const o = await api.observeLive(source, inv.id, inv.subject);
      setCaseObs((s) => ({ ...s, [inv.id]: o }));
    } catch (e) { setError(e as ApiError); }
  };

  // v4.8 — §68 replay from stored provenance; §67 chronology viewer
  const rerunObs = async (inv: Investigation, evidenceId: string) => {
    setError(null);
    try {
      const o = await api.rerunLive(evidenceId);
      setCaseObs((s) => ({ ...s, [inv.id]: o }));
    } catch (e) { setError(e as ApiError); }
  };
  const [caseChrono, setCaseChrono] =
    useState<Record<string, CaseChronology | null>>({});
  const toggleChronology = async (invId: string) => {
    if (caseChrono[invId]) {
      setCaseChrono((s) => ({ ...s, [invId]: null }));
      return;
    }
    try {
      const c = await api.caseChronology(invId);
      setCaseChrono((s) => ({ ...s, [invId]: c }));
    } catch (e) { setError(e as ApiError); }
  };

  // v4.1 — dork builder bound to the case's §63 scope (generation only)
  const buildCaseDorks = async (inv: Investigation) => {
    if (caseDorks[inv.id]) {
      setCaseDorks((d) => ({ ...d, [inv.id]: null }));
      return;
    }
    try {
      const d = await api.buildDorks({
        objective: inv.objective, subject: inv.subject,
        subject_type: inv.subject_type, investigation_id: inv.id,
      });
      setCaseDorks((s) => ({ ...s, [inv.id]: d }));
    } catch (e) { setError(e as ApiError); }
  };

  // v4.1 — Evidence Locker (V1): provenance-first store browser
  const loadLocker = useCallback(async (q?: string) => {
    const l = await api.evidenceLocker(q).catch(() => null);
    if (l) setLocker(l);
  }, []);

  useEffect(() => {
    if (pane === "locker" && !locker) void loadLocker();
  }, [pane, locker, loadLocker]);

  // v4.2 — governance pane loaders
  const loadGovernance = useCallback(async () => {
    const [a, i, s, w, c, q, r] = await Promise.all([
      api.listApprovals().catch(() => null),
      api.agentInventory().catch(() => null),
      api.assuranceStatus().catch(() => null),
      api.whoami().catch(() => null),
      api.listConnectors().catch(() => null),
      api.reviewQueue().catch(() => null),
      api.reroutes().catch(() => null),
    ]);
    if (a) setApprovalsList(a.approvals);
    if (i) setInventory(i);
    if (s) setAssurance(s);
    if (w) setWhoami(w);
    if (c) setConnectorsList(c.connectors);
    if (q) setReviews(q.queue);
    if (r) setReroutes(r.reroutes);
  }, []);

  // v4.4 — enterprise plane actions
  const runRetention = async (dryRun: boolean) => {
    setError(null);
    try { setRetentionRep(await api.retentionApply(dryRun)); }
    catch (e) { setError(e as ApiError); }
  };

  const registerConn = async () => {
    if (!connForm.name.trim() || !connForm.base_url.trim()) return;
    setError(null);
    try {
      await api.registerConnector({
        name: connForm.name, kind: connForm.kind,
        base_url: connForm.base_url,
        auth_env: connForm.auth_env || null,
      });
      setConnForm({ name: "", kind: "C_data_api", base_url: "", auth_env: "" });
      await loadGovernance();
    } catch (e) { setError(e as ApiError); }
  };

  const retireConn = async (connectorId: string) => {
    setError(null);
    try {
      await api.retireConnector(connectorId);
      await loadGovernance();
    } catch (e) { setError(e as ApiError); }
  };

  // v4.3 — run an assurance sweep, then refresh the series
  const runSweep = async () => {
    if (sweepBusy) return;
    setSweepBusy(true);
    setError(null);
    try {
      await api.assuranceSweep();
      await loadGovernance();
    } catch (e) { setError(e as ApiError); } finally { setSweepBusy(false); }
  };

  useEffect(() => {
    if (pane === "governance" && !inventory) void loadGovernance();
  }, [pane, inventory, loadGovernance]);

  const decide = async (approvalId: string, approved: boolean) => {
    setError(null);
    try {
      await api.decideApproval(approvalId, approved);
      await loadGovernance();
    } catch (e) { setError(e as ApiError); }
  };

  // v4.6 — human-outcome adjudications (§71 write-paths); every decision
  // is single-use server-side, the buttons simply surface the 409 honest.
  const decideReview = async (reviewId: string,
                              decision: "CONFIRMED" | "CORRECTED") => {
    setError(null);
    if (decision === "CORRECTED" && !correctionText.trim()) {
      setError({ code: "INPUT",
                title: "Correction needs to be in writing",
                meaning: "CORRECTED without the corrected outcome is not an " +
                  "analyst correction (§71 needs the diff, §76 needs the " +
                  "words).",
                next_step: "Set the correction note, then press Correct." });
      return;
    }
    try {
      await api.decideReview(reviewId, decision,
                             decision === "CORRECTED"
                               ? correctionText.trim() : undefined);
      setCorrectionText("");
      await loadGovernance();
    } catch (e) { setError(e as ApiError); }
  };

  const adjudicate = async (notificationId: string,
                            verdict: "TRUE_POSITIVE" | "FALSE_POSITIVE") => {
    setError(null);
    try {
      await api.adjudicateAlert(notificationId, verdict);
      const n = await api.opsNotifications().catch(() => null);
      if (n) setAlerts(n.notifications);
    } catch (e) { setError(e as ApiError); }
  };

  const decideReroute = async (watchId: string,
                               decision: "ACCEPT" | "DECLINE") => {
    setError(null);
    try {
      await api.decideReroute(watchId, decision);
      await loadGovernance();
    } catch (e) { setError(e as ApiError); }
  };

  const approvePlan = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", text: `⚡ ${plan.goal}` }]);
    try {
      const r = await api.approveTree(plan.tree_id);
      setPlan(null);
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

  const rejectPlan = async () => {
    if (!plan) return;
    await api.rejectTree(plan.tree_id).catch(() => {});
    setPlan(null);
    refreshPanels();
  };

  // v3.2 blocker E — Halt Execution for the currently selected tree
  const haltCurrentTree = async () => {
    if (!tree) return;
    await api.haltTree(tree.tree_id).catch(() => {});
    await loadTree(tree.tree_id);
    refreshPanels();
  };

  const declareCrisis = async () => {
    setBusy(true);
    try {
      const inc = await api.declareIncident(
        sev, sevSummary, localStorage.getItem("th360.user") || "demo-operator");
      setIncident(inc);
      setCrisisOpen(false);
      setSevSummary("");
      refreshPanels();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const resolveCrisis = async () => {
    if (!incident) return;
    await api.resolveIncident(incident.incident_id).catch(() => {});
    setIncident(null);
    refreshPanels();
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
    <section aria-labelledby="ops-title"
             className={incident ? "crisis-active" : undefined}>
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

      {/* v3.3 (blueprint v5.2 §6.A) — 4-step onboarding wizard: establishes
          trust and sets boundaries BEFORE the first goal is dispatched. */}
      {!onboarded && (
        <div className="card wizard" role="dialog" aria-modal="false"
             aria-label="Sovereign onboarding wizard">
          <div className="wizard-steps" aria-hidden="true">
            {[0, 1, 2, 3].map(i => (
              <div key={i} className={`wizard-dot${i <= wizardStep ? " on" : ""}`} />
            ))}
          </div>
          {wizardStep === 0 && (<>
            <h3>Welcome, Sovereign — you command, the fleet advises</h3>
            <p>
              <strong>ThreatHunter360 is an AI-powered assistant</strong> for
              threat intelligence and security operations. You define a goal;
              the governed agent swarm decomposes it, gathers evidence and
              drafts recommendations. It is not an oracle and never acts on
              your behalf without an approved plan.
            </p>
          </>)}
          {wizardStep === 1 && (<>
            <h3>Step 2 — The swarm's boundaries</h3>
            <p>
              Agents hold <strong>enumerated, least-privilege capabilities</strong>
              (registry A-14). Patching, messaging and any external effect pause
              for human approval. The swarm can be halted mid-run at any time —
              the <em>Halt Swarm</em> control is always visible on running plans.
            </p>
          </>)}
          {wizardStep === 2 && (<>
            <h3>Step 3 — Privacy &amp; the AUDITOR gate</h3>
            <p>
              Personal data is masked at the source by the AUDITOR agent;
              identity lookups produce hedged indicators, never verdicts on
              persons. Your consent decisions live on an immutable ledger, and
              the <em>Govern</em> tab lets you inspect or permanently delete
              your session data. AI output is always labelled as such.
            </p>
          </>)}
          {wizardStep === 3 && (<>
            <h3>Step 4 — Your part of the partnership</h3>
            <p>
              AI can be wrong or incomplete. <strong>Verify all AI-generated
              insights and plans with your team's protocols before taking
              action.</strong> Review each plan, check the raw evidence behind
              any node, and treat scores as indicators — not certainty.
            </p>
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Keep the habit sharp: the <strong>Field Manual</strong>
              (<span className="mono">docs/field-manual/</span>) has three
              ten-minute operator drills — spot the fabrication, halt the
              swarm, withdraw consent.
            </p>
          </>)}
          <div className="wizard-actions">
            {wizardStep > 0 && (
              <button className="btn ghost" type="button"
                      onClick={() => setWizardStep(s => s - 1)}>
                Back
              </button>
            )}
            {wizardStep < 3 ? (
              <button className="btn" type="button"
                      onClick={() => setWizardStep(s => s + 1)}>
                Next
              </button>
            ) : (
              <button className="btn" type="button"
                      onClick={() => {
                        localStorage.setItem(ONBOARD_KEY, "1");
                        setOnboarded(true);
                      }}>
                Understood — I'll verify before acting
              </button>
            )}
          </div>
        </div>
      )}

      {/* v3.2 blocker G — functional crisis banner (simplifies, never
          accelerates: review risk #10) */}
      {incident && (
        <div className="card crisis-banner" role="alert">
          <h3 style={{ marginTop: 0 }}>
            🚨 ACTIVE INCIDENT · {incident.severity}
          </h3>
          <p style={{ margin: "4px 0" }}>{incident.summary}</p>
          <p className="muted" style={{ fontSize: ".82rem", margin: "4px 0" }}>
            Declared by {incident.declared_by} · external delivery:{" "}
            <strong>{incident.delivery?.state}</strong>
            {incident.delivery?.note ? ` — ${incident.delivery.note}` : ""}
          </p>
          {incident.checklist && (
            <>
              {/* v3.5 risk #10 — interactive response checklist */}
              <p className="crisis-progress mono">
                {incident.checklist.filter((_, i) => checkedSteps[i]).length}
                /{incident.checklist.length} response steps complete
              </p>
              <ul className="crisis-checklist interactive">
                {incident.checklist.map((c, i) => (
                  <li key={i}>
                    <label>
                      <input type="checkbox" checked={!!checkedSteps[i]}
                             onChange={() => toggleStep(i)} />
                      <span className={checkedSteps[i] ? "done" : ""}>
                        {c}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              {incident.ui_guidance && (
                <p className="muted" style={{ fontSize: ".78rem" }}>
                  {incident.ui_guidance}
                </p>
              )}
            </>
          )}
          <button className="demo-btn" type="button" onClick={resolveCrisis}>
            Mark resolved
          </button>
        </div>
      )}

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
                    onClick={() => fireGoal("Secure the Lagos IoT deployment — scan for vulnerabilities")}
                    title="Decomposes first — you approve the plan before anything runs">
              ⚡ Demo: security sweep (plan first)
            </button>
            <button type="button" className="demo-btn" disabled={busy}
                    onClick={() => send("I'm traveling tomorrow")}>
              ⚡ Demo: journey dialogue
            </button>
            <button type="button" className="demo-btn" disabled={busy}
                    onClick={runReassess} title="§1.10 continual reassessment">
              ↻ Reassess now
            </button>
            <button type="button" className="crisis-btn"
                    onClick={() => setCrisisOpen(true)}>
              🚨 Declare incident
            </button>
          </div>

          {/* v3.4 red-team #3 — the cortex detected crisis language; surface
              the REAL pathway (declare = checklist + honest on-call notify),
              never a cosmetic badge. */}
          {crisisSignal && !incident && (
            <div className="crisis-signal" role="alert">
              <span>
                Crisis language detected (<em>“{crisisSignal.phrase}”</em>).
                If this is a live incident, declare it:
              </span>
              <button type="button" className="crisis-btn"
                      onClick={() => { setCrisisOpen(true); }}>
                Declare now
              </button>
              <button type="button" className="btn ghost"
                      aria-label="Dismiss crisis suggestion"
                      onClick={() => setCrisisSignal(null)}>
                Dismiss
              </button>
            </div>
          )}
        </div>

        {/* ------------------- right pane: tabs ------------------- */}
        <div className="ops-side">
          {/* v3.2 checklist D — Plan Review gate (choice & autonomy) */}
          {plan && (
            <div className="card plan-review" role="dialog"
                 aria-label="Plan review — approve before execution">
              <h3 style={{ marginTop: 0 }}>
                📋 Review &amp; Approve Plan
                <span className="badge moderate" style={{ marginLeft: 8 }}>
                  {plan.task_count} tasks · nothing has run yet
                </span>
              </h3>
              <p style={{ fontWeight: 600 }}>{plan.goal}</p>
              {plan.investigation_id && (
                <p className="muted" style={{ fontSize: 12 }}>
                  🗂 Bound to investigation case{" "}
                  <code>{plan.investigation_id}</code> — its §63 authorization
                  (scope, sources, expiry) governs this run.
                </p>
              )}
              {plan.ethics_flag && (
                <p className="review-route" role="alert">
                  ⛔ Ethics flag: {plan.ethics_flag.message}
                </p>
              )}
              {plan.cost_warning && (
                <p className="review-route" role="alert">
                  ⚠ {plan.cost_warning}
                </p>
              )}
              <ol className="strategy-tree">
                {plan.plan.map((t, i) => (
                  <li key={i} className="task-item"
                      style={{ marginLeft: t.parent ? 22 : 0 }}>
                    <span className="task-agent">{t.agent}</span>
                    <span className="task-title">{t.title}</span>
                  </li>
                ))}
              </ol>
              <p className="ai-disclaimer" role="note">
                ⚠ {plan.disclaimer}
              </p>
              <div className="btn-row">
                <button className="btn" type="button" disabled={busy}
                        onClick={approvePlan}>
                  Approve &amp; Execute
                </button>
                <button className="demo-btn" type="button" onClick={rejectPlan}>
                  Cancel plan
                </button>
              </div>
            </div>
          )}
          <nav className="pane-tabs" aria-label="Ops panes">
            {/* v3.5 risk #10 — during an ACTIVE incident the pane set is
                reduced to essentials (stream + alerts); the rest reappear
                on resolve. No content is deleted, just decluttered. */}
            {((incident ? crisisPanes
                        : ["strategy", "cases", "locker", "governance",
                           "timeline", "alerts", "feed", "kpis", "stream"]) as Pane[]).map((p: Pane) => (
              <button key={p} type="button"
                      className={pane === p ? "active" : ""}
                      onClick={() => setPane(p)}>
                {{ strategy: "Strategy Map",
                   cases: `Cases${cases.length ? ` (${cases.length})` : ""}`,
                   locker: "Evidence Locker", governance: "Governance",
                   timeline: "Timeline",
                   alerts: `Alerts${alerts.length ? ` (${alerts.length})` : ""}`,
                   feed: "Intel Feed", kpis: "KPIs",
                   stream: "Data Stream" }[p]}
              </button>
            ))}
          </nav>

          {error && <ErrorPanel error={error} />}

          {pane === "strategy" && (
            <div className="card" aria-label="Strategy Map">
              {tree ? (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <h3 style={{ marginTop: 0 }}>🗺 Strategy Map</h3>
                    {tree.tasks.some((t) =>
                      t.status === "PENDING" || t.status === "RUNNING") && (
                      <button type="button" className="halt-btn"
                              onClick={haltCurrentTree}>
                        ■ Halt Execution
                      </button>
                    )}
                  </div>
                  <p className="muted" style={{ marginTop: 0 }}>
                    <span className="mono">{tree.tree_id}</span> · peer{" "}
                    <span className="mono">{tree.peer_id}</span> · status{" "}
                    <strong>{tree.status}</strong>
                  </p>
                  <p style={{ fontWeight: 600 }}>{tree.goal}</p>
                  <ol className="strategy-tree">
                    {tree.tasks.map((t) => {
                      const meta = STATUS_META[t.status] ?? STATUS_META.PENDING;
                      const agentDesc = agents.find(
                        (a) => a.agent_id === t.agent)?.description
                        ?? `${t.agent} agent`;
                      const hasResult = t.result &&
                        Object.keys(t.result).length > 0;
                      return (
                        <li key={t.task_id}
                            className={`task-item st-${t.status.toLowerCase()}`}
                            style={{
                              marginLeft: t.parent_id ? 22 : 0,
                            }}>
                          <span className="task-icon" aria-hidden="true">
                            {meta.icon}
                          </span>
                          {/* risk #8 black-box fix: role tooltip on agents */}
                          <span className="task-agent" title={agentDesc}>
                            {t.agent}
                          </span>
                          <span className="task-title">{t.title}</span>
                          <span className="task-status">{meta.label}
                            {t.classified_error
                              ? ` · ${t.classified_error}` : ""}
                          </span>
                          {/* interactive (flow #5): raw task I/O on demand */}
                          {hasResult && (
                            <details className="task-io">
                              <summary>raw result</summary>
                              <pre className="mono">
                                {JSON.stringify(t.result, null, 2)}
                              </pre>
                            </details>
                          )}
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

          {pane === "cases" && (
            <div className="card" aria-label="Investigation cases">
              <h3 style={{ marginTop: 0 }}>🗂 Investigation Cases</h3>
              <p className="muted" style={{ fontSize: 13 }}>
                v4.0 §2/§63 — every case carries an <b>authorization
                object</b> (purpose, authority, scope, allowed sources,
                expiry). Goals fired while a case is active are gated by its
                scope (§35: the model proposes, policy disposes; §76: no
                action without living authorization).
              </p>

              {/* ---------- create case ---------- */}
              <details>
                <summary style={{ cursor: "pointer", marginBottom: 8 }}>
                  + New investigation case
                </summary>
                <div className="field">
                  <label htmlFor="case-obj">Objective</label>
                  <input id="case-obj" value={caseForm.objective}
                         placeholder="Assess exposure of example.ng"
                         onChange={(e) => setCaseForm({
                           ...caseForm, objective: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="case-subject">Subject (type + value)</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    <select id="case-subject" value={caseForm.subject_type}
                            onChange={(e) => setCaseForm({
                              ...caseForm, subject_type: e.target.value })}>
                      {SUBJECT_TYPES.map((t) => (
                        <option key={t} value={t}>{t}</option>))}
                    </select>
                    <input value={caseForm.subject}
                           placeholder="example.ng"
                           aria-label="subject value"
                           onChange={(e) => setCaseForm({
                             ...caseForm, subject: e.target.value })} />
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="case-purpose">Purpose (§63)</label>
                  <input id="case-purpose" value={caseForm.purpose}
                         placeholder="Why this investigation exists"
                         onChange={(e) => setCaseForm({
                           ...caseForm, purpose: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="case-authority">Authority (§63)</label>
                  <select id="case-authority" value={caseForm.authority}
                          onChange={(e) => setCaseForm({
                            ...caseForm, authority: e.target.value })}>
                    <option value="organization_owned">organization_owned — our own assets</option>
                    <option value="client_authorized">client_authorized — written client mandate</option>
                    <option value="public_research">public_research — open public sources</option>
                    <option value="unchecked">unchecked — demo/no-auth path</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="case-scope">Scope statement</label>
                  <input id="case-scope" value={caseForm.scope}
                         placeholder="passive OSINT only; no active probing"
                         onChange={(e) => setCaseForm({
                           ...caseForm, scope: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="case-sources">Allowed source families
                    (comma-separated; empty = open public tier)</label>
                  <input id="case-sources" value={caseForm.allowed_sources}
                         placeholder="osint_databases, rdap, news_feed"
                         onChange={(e) => setCaseForm({
                           ...caseForm, allowed_sources: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="case-days">Authorization expires in (days,
                    1–90)</label>
                  <input id="case-days" type="number" min={1} max={90}
                         value={caseForm.expires_days}
                         onChange={(e) => setCaseForm({
                           ...caseForm,
                           expires_days: Number(e.target.value) || 30 })} />
                </div>
                <button type="button" className="btn"
                        disabled={busy || !caseForm.objective.trim()
                                  || !caseForm.subject.trim()
                                  || !caseForm.purpose.trim()}
                        onClick={createCase}>
                  Open case
                </button>
              </details>

              <hr style={{ borderColor: "var(--line)", opacity: .4,
                           margin: "14px 0" }} />

              {/* ---------- case list ---------- */}
              {cases.length === 0 && (
                <p className="muted">No investigation cases yet. Create one
                above — runs without a case use the no-auth demo path.</p>
              )}
              {cases.map((inv) => (
                <div key={inv.id} className="card"
                     style={{ marginBottom: 10,
                              borderColor: inv.id === activeCase
                                ? "var(--accent)" : undefined }}>
                  <div style={{ display: "flex", alignItems: "center",
                                gap: 10, flexWrap: "wrap" }}>
                    <strong>{inv.objective.slice(0, 60)}</strong>
                    <span className="verdict-chip"
                          data-verdict={inv.status === "OPEN"
                            ? "VERIFIED" : "MISLEADING"}>
                      {inv.status}
                    </span>
                    <button type="button" className="btn ghost"
                            disabled={inv.status !== "OPEN"}
                            onClick={() => setActiveCase(
                              inv.id === activeCase ? null : inv.id)}>
                      {inv.id === activeCase ? "◇ Active" : "◈ Make active"}
                    </button>
                    {tree && inv.status === "OPEN" && (
                      <button type="button" className="btn ghost"
                              onClick={() => linkCurrentTree(inv.id)}>
                        Link current tree
                      </button>
                    )}
                    <button type="button" className="btn ghost"
                            onClick={() => void toggleCaseGraph(inv.id)}>
                      {caseGraphs[inv.id] ? "Hide graph" : "⛓ Graph"}
                    </button>
                    <button type="button" className="btn ghost"
                            title="§67 immutable case chronology, digest-committed"
                            onClick={() => void toggleChronology(inv.id)}>
                      {caseChrono[inv.id] ? "Hide chronology" : "🕰 Chronology"}
                    </button>
                    {inv.status === "OPEN" && (
                      <button type="button" className="btn ghost"
                              onClick={() => void buildCaseDorks(inv)}>
                        {caseDorks[inv.id] ? "Hide dorks" : "🔎 Build dorks"}
                      </button>
                    )}
                    {/* v4.5/4.7 — PASSIVE live reads via the §80 registry,
                        domain cases only (scope is the case subject's cone) */}
                    {inv.status === "OPEN" && inv.subject_type === "domain" && (
                      <>
                        <button type="button" className="btn ghost"
                                title="PASSIVE Certificate Transparency read through the connector registry"
                                onClick={() => void observeCase(inv, "crtsh")}>
                          📡 Observe CT
                        </button>
                        <button type="button" className="btn ghost"
                                title="PASSIVE registry-of-record (RDAP) read through the connector registry"
                                onClick={() => void observeCase(inv, "rdap")}>
                          🛰 Observe RDAP
                        </button>
                      </>
                    )}
                    {inv.status === "OPEN" && (
                      <button type="button" className="btn ghost"
                              onClick={() => closeCase(inv.id)}>
                        Close case
                      </button>
                    )}
                  </div>
                  <p className="muted" style={{ fontSize: 12, margin: "6px 0" }}>
                    {inv.subject_type}: <code>{inv.subject}</code> · authority{" "}
                    <code>{inv.authority}</code> · expires{" "}
                    {new Date(inv.expires_at).toLocaleDateString()} · sources:{" "}
                    {inv.allowed_sources.length
                      ? inv.allowed_sources.join(", ")
                      : "open public tier"}
                  </p>
                  {inv.scope && (
                    <p className="muted" style={{ fontSize: 12 }}>
                      scope: {inv.scope}
                    </p>
                  )}
                  {(inv.links ?? []).length > 0 && (
                    <p className="muted" style={{ fontSize: 12 }}>
                      links: {(inv.links ?? [])
                        .map((l) => `${l.kind}:${l.ref_id.slice(0, 8)}`)
                        .join(" · ")}
                    </p>
                  )}

                  {/* v4.1 — evidence-chain graph expansion */}
                  {caseGraphs[inv.id] && (
                    <div style={{ marginTop: 8 }}>
                      <EvidenceGraph data={caseGraphs[inv.id]!} />
                      <p className="muted" style={{ fontSize: 11 }}>
                        {(caseGraphs[inv.id] as GraphData & { note?: string })
                          .note}
                      </p>
                    </div>
                  )}

                  {/* v4.1 — dork builder expansion (generation only) */}
                  {caseDorks[inv.id] && (
                    <div style={{ marginTop: 8 }}>
                      <p className="muted" style={{ fontSize: 11 }}>
                        {caseDorks[inv.id]!.execution_note}{" "}
                        {caseDorks[inv.id]!.passive_first}
                      </p>
                      <table className="task-matrix">
                        <thead>
                          <tr><th>Dork</th><th>Engine</th><th>Why / boundaries</th></tr>
                        </thead>
                        <tbody>
                          {caseDorks[inv.id]!.dorks.map((d) => (
                            <tr key={d.name}>
                              <td><code style={{ fontSize: 11 }}>{d.syntax}</code>
                                <div className="muted" style={{ fontSize: 10 }}>
                                  {d.risk_level} · verified {d.last_verified.slice(0, 10)}
                                </div>
                              </td>
                              <td>{d.search_engine}</td>
                              <td style={{ fontSize: 11 }}>
                                {d.why}<br />
                                <span className="muted">{d.boundaries}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* v4.8 — §67 chronology expansion */}
                  {caseChrono[inv.id] && (() => {
                    const c = caseChrono[inv.id]!;
                    return (
                      <div className="live-obs" style={{ marginTop: 8 }}>
                        <p className="muted" style={{ fontSize: 11 }}>
                          🕰 <b>{c.event_count}</b> events · digest{" "}
                          <code className="mono">{c.digest.slice(0, 20)}…</code>
                          {" "}· recomputed on read — an edited trail yields a
                          different digest (§67)
                        </p>
                        <ul style={{ fontSize: 11, margin: "4px 0 0",
                                     paddingLeft: 0, listStyle: "none" }}>
                          {c.events.map((e, i) => (
                            <li key={i} className="chrono-row">
                              <code className="mono chrono-kind"
                                    data-kind={e.kind}>{e.kind}</code>{" "}
                              <span className="muted">
                                {e.at.slice(0, 19).replace("T", " ")}
                              </span>{" "}
                              <b>{e.action}</b>{" "}
                              <span className="muted">{e.decision}</span>{" "}
                              <span style={{ display: "block",
                                             paddingLeft: "5.2rem" }}>
                                {e.detail.slice(0, 140)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })()}

                  {/* v4.5/4.7 — governed live-observation result */}
                  {caseObs[inv.id] && (() => {
                    const o = caseObs[inv.id]!;
                    return (
                      <div className="live-obs" style={{ marginTop: 8 }}>
                        <p className="muted" style={{ fontSize: 11 }}>
                          🛰 <strong>{o.provenance.source}</strong> ·{" "}
                          {o.osint_class}
                          {o.changed_from && (
                            <span className="verdict-chip"
                                  data-verdict="MIXED"> CHANGED</span>
                          )}
                          {o.new_evidence
                            ? " · new evidence stored"
                            : " · identical to stored observation"}
                          {"outcome" in o && (
                            <span className="verdict-chip"
                                  data-verdict={o.outcome === "CHANGED"
                                    ? "MIXED" : "VERIFIED"}>
                              {" "}replay: {o.outcome}
                            </span>
                          )}
                        </p>
                        {o.observed_total !== undefined && (
                          <p style={{ fontSize: 12, margin: "4px 0" }}>
                            CT names observed: <b>{o.observed_total}</b>
                            {o.truncated ? " (truncated at 100)" : ""}
                            {(o.names ?? []).length > 0 && (
                              <span className="muted"> —{" "}
                                {(o.names ?? []).slice(0, 5).join(", ")}
                                {(o.names ?? []).length > 5 ? "…" : ""}
                              </span>
                            )}
                          </p>
                        )}
                        {o.registered !== undefined && (
                          <p style={{ fontSize: 12, margin: "4px 0" }}>
                            {o.registered ? (
                              <>Registered — registrar{" "}
                                <b>{o.registrar ?? "unparsed"}</b>
                                {(o.nameservers ?? []).length > 0 && (
                                  <span className="muted"> · ns:{" "}
                                    {(o.nameservers ?? []).slice(0, 3)
                                      .join(", ")}</span>
                                )}
                              </>
                            ) : (
                              <b>NOT registered in the registry of record</b>
                            )}
                          </p>
                        )}
                        <p className="muted mono" style={{ fontSize: 10 }}>
                          hash {o.result_hash.slice(0, 16)}… · evidence{" "}
                          {o.evidence_id?.slice(0, 8)}… ·{" "}
                          {o.provenance.query_url}
                        </p>
                        {/* v4.8 §68 — replay from stored provenance */}
                        {o.evidence_id && (
                          <button type="button" className="btn ghost"
                                  style={{ fontSize: 11 }}
                                  title="§68 Re-run: replay from stored provenance and compare hashes"
                                  onClick={() =>
                                    void rerunObs(inv, o.evidence_id!)}>
                            ↻ Re-run observation
                          </button>
                        )}
                      </div>
                    );
                  })()}
                </div>
              ))}
            </div>
          )}

          {pane === "locker" && (
            <div className="card" aria-label="Evidence Locker">
              <h3 style={{ marginTop: 0 }}>🗄 Evidence Locker</h3>
              <p className="muted" style={{ fontSize: 13 }}>
                §73 V1 — provenance-first store browser. Absence = nothing
                stored, never a verdict (§1.9).
              </p>
              <form className="field" style={{ display: "flex", gap: 8 }}
                    onSubmit={(e) => { e.preventDefault();
                                       void loadLocker(lockerQ || undefined); }}>
                <input id="locker-q" value={lockerQ}
                       placeholder="search title / excerpt / url…"
                       onChange={(e) => setLockerQ(e.target.value)}
                       style={{ flex: 1 }} />
                <button type="submit" className="btn">Search</button>
                {lockerQ && (
                  <button type="button" className="btn ghost"
                          onClick={() => { setLockerQ("");
                                           void loadLocker(); }}>
                    Clear
                  </button>
                )}
              </form>
              {locker ? (
                <>
                  <p className="muted" style={{ fontSize: 12 }}>
                    {locker.count} shown · {locker.total_stored} stored ·{" "}
                    {locker.note}
                  </p>
                  <table className="task-matrix">
                    <thead>
                      <tr><th>Evidence</th><th>Source</th><th>Authority</th>
                          <th>Fetched</th></tr>
                    </thead>
                    <tbody>
                      {locker.items.map((it) => (
                        <tr key={it.id}>
                          <td>
                            <span style={{ fontSize: 12 }}>
                              {it.title ?? "(untitled)"}
                            </span>
                            <div className="muted" style={{ fontSize: 10 }}>
                              {it.excerpt.slice(0, 120)}
                              {it.excerpt.length > 120 ? "…" : ""}
                            </div>
                            {it.url && (
                              <div className="muted" style={{ fontSize: 10 }}>
                                <code>{it.url.slice(0, 80)}</code>
                              </div>
                            )}
                          </td>
                          <td style={{ fontSize: 11 }}>{it.source_id}
                            <div className="muted" style={{ fontSize: 10 }}>
                              hash {it.content_hash} · grp {it.independence_group?.slice(0, 14)}
                            </div>
                          </td>
                          <td>
                            <span className="verdict-chip"
                                  data-verdict={it.authority === "PRIMARY"
                                    ? "VERIFIED" : "MOSTLY_TRUE"}>
                              {it.authority ?? "UNKNOWN"}
                            </span>
                            <div className="muted" style={{ fontSize: 10 }}>
                              {it.reliability ?? ""}
                            </div>
                          </td>
                          <td style={{ fontSize: 11, whiteSpace: "nowrap" }}>
                            {it.fetched_at ? it.fetched_at.slice(0, 10) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : (
                <p className="muted">Loading locker…</p>
              )}
            </div>
          )}

          {pane === "governance" && (
            <div className="card" aria-label="Governance planes">
              <h3 style={{ marginTop: 0 }}>⚖ Governance (V2)</h3>
              <p className="muted" style={{ fontSize: 13 }}>
                §73 V2 — the approval engine is the durable surface for
                REQUIRE_HUMAN decisions (§27/R-05); the agent inventory
                answers, per node, "what could this agent reach if
                compromised".
              </p>

              {/* ---------- v4.3 continuous assurance ---------- */}
              <h4 style={{ margin: "10px 0 6px" }}>🛡 Continuous assurance</h4>
              <div style={{ display: "flex", alignItems: "center", gap: 10,
                            flexWrap: "wrap" }}>
                <button type="button" className="btn" disabled={sweepBusy}
                        onClick={() => void runSweep()}>
                  {sweepBusy ? "Sweeping…" : "▶ Run assurance sweep"}
                </button>
                {assurance?.latest ? (
                  <span className="verdict-chip"
                        data-verdict={assurance.latest.posture === "OK"
                          ? "VERIFIED" : assurance.latest.posture === "ATTENTION"
                          ? "MOSTLY_TRUE" : "FALSE"}>
                    posture: {assurance.latest.posture}
                  </span>
                ) : (
                  <span className="muted" style={{ fontSize: 12 }}>
                    No sweeps yet — posture unknown until the first run.
                  </span>
                )}
              </div>
              {assurance?.latest && (
                <div style={{ fontSize: 12, margin: "6px 0 4px" }}>
                  {(assurance.latest.summary.posture_reasons ?? []).map((r) => (
                    <p key={r} className="muted" style={{ margin: "2px 0" }}>
                      · {r}
                    </p>
                  ))}
                  <p className="muted" style={{ margin: "4px 0" }}>
                    §26 events this sweep: RiskRecalculated ×
                    {assurance.latest.summary.events_emitted?.RiskRecalculated ?? 0}
                    {" · "}JourneyConditionChanged ×
                    {assurance.latest.summary.events_emitted?.JourneyConditionChanged ?? 0}
                    {" · "}AlertTriggered ×
                    {assurance.latest.summary.events_emitted?.AlertTriggered ?? 0}
                    {" · "}consent chain:{" "}
                    {assurance.latest.summary.consent_chain_valid ? "intact"
                      : "BROKEN"}
                    {assurance.latest.summary.degraded_or_worse?.length
                      ? ` · degraded sources: ${assurance.latest.summary.degraded_or_worse.join(", ")}`
                      : ""}
                  </p>
                  {(assurance.series ?? []).length > 1 && (
                    <p className="muted" style={{ fontSize: 11 }}>
                      series: {assurance.series.map((s) =>
                        `${s.posture} ${s.started_at.slice(5, 16)}`).join(" → ")}
                    </p>
                  )}
                </div>
              )}

              {/* ---------- approvals queue ---------- */}
              <h4 style={{ margin: "10px 0 6px" }}>📋 Approvals</h4>
              {!approvalsList && <p className="muted">Loading…</p>}
              {approvalsList && approvalsList.length === 0 && (
                <p className="muted">No approval records yet — promotions and
                other external-effect actions mint them here.</p>
              )}
              {(approvalsList ?? []).map((a) => (
                <div key={a.id} className="card" style={{ marginBottom: 8 }}>
                  <div style={{ display: "flex", alignItems: "center",
                                gap: 10, flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 13 }}>{a.summary}</strong>
                    <span className="verdict-chip"
                          data-verdict={a.status === "APPROVED" ? "VERIFIED"
                            : a.status === "REJECTED" ? "MISLEADING"
                            : "UNVERIFIED"}>
                      {a.status}
                    </span>
                    {a.status === "PENDING" && (
                      <>
                        <button type="button" className="btn ghost"
                                onClick={() => void decide(a.id, true)}>
                          Approve
                        </button>
                        <button type="button" className="btn ghost"
                                onClick={() => void decide(a.id, false)}>
                          Reject
                        </button>
                      </>
                    )}
                  </div>
                  <p className="muted" style={{ fontSize: 11, margin: "4px 0" }}>
                    {a.kind} · {a.subject_ref} · requested by {a.requester} at{" "}
                    {a.created_at.slice(0, 19)}
                    {a.decided_by
                      ? ` · decided by ${a.decided_by} at ${a.decided_at?.slice(0, 19)}`
                      : " · awaiting human decision"}
                  </p>
                </div>
              ))}

              {/* ---------- v4.6 review decisions (§27 write-path) -------- */}
              <h4 style={{ margin: "14px 0 6px" }}>🧾 Review decisions (§27)</h4>
              <p className="muted" style={{ fontSize: 11, margin: "0 0 6px" }}>
                Every decision records the system's prior verdict and — for
                CORRECTED — the analyst's correction in writing. These diffs
                are what the §71 analyst/fact-checker correction KPIs measure.
              </p>
              {reviews === null ? null : reviews.length === 0 ? (
                <p className="muted" style={{ fontSize: 12 }}>
                  Queue empty — nothing awaiting human judgment.
                </p>
              ) : (
                <>
                  <input
                    className="correction-input"
                    placeholder="Correction note (required for CORRECTED)"
                    value={correctionText}
                    onChange={(e) => setCorrectionText(e.target.value)}
                  />
                  {reviews.slice(0, 8).map((rv) => (
                    <div key={rv.id} className="evidence-item">
                      <div className="head">
                        <span className={`badge ${
                          rv.status === "OPEN" ? "moderate" : "low"}`}>
                          {rv.module} · {rv.tier ?? "—"}
                        </span>
                        <strong>{rv.reason}</strong>
                        {rv.status === "OPEN" ? (
                          <>
                            <button type="button" className="btn ghost"
                                    onClick={() =>
                                      void decideReview(rv.id, "CONFIRMED")}>
                              ✓ Confirm
                            </button>
                            <button type="button" className="btn ghost"
                                    onClick={() =>
                                      void decideReview(rv.id, "CORRECTED")}>
                              ✎ Correct
                            </button>
                          </>
                        ) : (
                          <span className={`verdict-chip`} data-verdict={
                            rv.decision === "CORRECTED"
                              ? "FALSE" : "VERIFIED"}>
                            {rv.decision}
                          </span>
                        )}
                      </div>
                      <p className="muted" style={{ fontSize: 11,
                                                    margin: "4px 0" }}>
                        risk {rv.risk} · queued {rv.created_at.slice(0, 19)}
                        {rv.status === "DECIDED" &&
                          ` · by ${rv.decided_by}${rv.prior_outcome
                            ? ` · system said ${rv.prior_outcome}` : ""}${rv.corrected_outcome
                            ? ` → analyst: ${rv.corrected_outcome}` : ""}`}
                      </p>
                    </div>
                  ))}
                </>
              )}

              {/* ---------- v4.6 journey oversight — reroutes ---------- */}
              <h4 style={{ margin: "14px 0 6px" }}>🧭 Journey oversight —
                reroutes</h4>
              <p className="muted" style={{ fontSize: 11, margin: "0 0 6px" }}>
                Machine reroute recommendations awaiting a human answer — the
                accept/decline ratio is the §71 reroute-acceptance KPI.
              </p>
              {reroutes === null ? null : reroutes.length === 0 ? (
                <p className="muted" style={{ fontSize: 12 }}>
                  No pending or decided reroute recommendations.
                </p>
              ) : reroutes.slice(0, 8).map((w) => (
                <div key={w.watch_id} className="evidence-item">
                  <div className="head">
                    <span className={`badge ${
                      w.reroute_pending ? "high" : "low"}`}>
                      {w.reroute_pending ? "PENDING" : w.reroute_outcome}
                    </span>
                    <strong>{w.origin} → {w.destination}</strong>
                    {w.reroute_pending === 1 && (
                      <>
                        <button type="button" className="btn ghost"
                                onClick={() =>
                                  void decideReroute(w.watch_id, "ACCEPT")}>
                          Accept reroute
                        </button>
                        <button type="button" className="btn ghost"
                                onClick={() =>
                                  void decideReroute(w.watch_id, "DECLINE")}>
                          Decline
                        </button>
                      </>
                    )}
                  </div>
                  <p className="muted" style={{ fontSize: 11,
                                                margin: "4px 0" }}>
                    risk {w.current_risk ?? "—"} · watch {w.status.toLowerCase()}
                    {w.reroute_decided_at
                      ? ` · answered ${w.reroute_decided_at.slice(0, 19)}`
                      : ""}
                    {w.reroute_outcome === "AUTO_RESOLVED"
                      ? " · engine retired its own recommendation when risk eased"
                      : ""}
                  </p>
                </div>
              ))}

              {/* ---------- agent inventory / supply chain ---------- */}
              <h4 style={{ margin: "14px 0 6px" }}>🧭 Agent inventory &amp;
                supply chain</h4>
              {inventory && (
                <p className="muted" style={{ fontSize: 11 }}>
                  NIST RMF — govern: {inventory.readiness.govern} · map:{" "}
                  {inventory.readiness.map} · measure:{" "}
                  {inventory.readiness.measure}
                  <br />{inventory.honest_limits}
                </p>
              )}
              {(inventory?.agents ?? []).map((n) => (
                <details key={n.agent_id} style={{ marginBottom: 6 }}>
                  <summary style={{ cursor: "pointer" }}>
                    <strong>{n.agent_id}</strong>{" "}
                    <span className="verdict-chip"
                          data-verdict={n.trust_status === "TRUSTED"
                            ? "VERIFIED" : n.trust_status === "OBSERVED"
                            ? "MOSTLY_TRUE" : "FALSE"}>
                      {n.trust_status}
                    </span>{" "}
                    <span className="muted" style={{ fontSize: 11 }}>
                      {n.status} · {n.permissions.api_functions.length} fn ·{" "}
                      {n.owner}
                    </span>
                  </summary>
                  <div style={{ fontSize: 11, margin: "6px 0 10px 6px" }}>
                    <p style={{ margin: "3px 0" }}>
                      <b>Source:</b> <code>{n.source}</code> · <b>publisher:</b>{" "}
                      {n.publisher} · <b>version:</b> {n.version}
                    </p>
                    <p style={{ margin: "3px 0" }}>
                      <b>Data classification:</b> {n.data_classification}
                    </p>
                    <p style={{ margin: "3px 0" }}>
                      <b>Credentials:</b> {n.credentials}
                    </p>
                    <p style={{ margin: "3px 0" }}>
                      <b>Runtime exposure:</b> {n.runtime_exposure}
                    </p>
                    <p style={{ margin: "3px 0" }}>
                      <b>Last reviewed:</b> {n.last_reviewed}
                    </p>
                    <p style={{ margin: "3px 0" }}>
                      <b>Known issue:</b> {n.known_issue}
                    </p>
                    <p style={{ margin: "3px 0" }} className="review-route">
                      ☢ {n.blast_radius_note}
                    </p>
                  </div>
                </details>
              ))}
              {inventory && inventory.dependency_graph.edges.length > 0 && (
                <p className="muted" style={{ fontSize: 11 }}>
                  Dependency edges: {inventory.dependency_graph.edges
                    .map((e) => `${e.from}→${e.to}`).join(" · ")}
                </p>
              )}

              {/* ---------- v4.4 enterprise plane ---------- */}
              <h4 style={{ margin: "16px 0 6px" }}>🏢 Enterprise plane</h4>
              {whoami && (
                <p className="muted" style={{ fontSize: 11 }}>
                  Identity: <code>{whoami.id}</code> · role{" "}
                  <b>{whoami.role}</b> ({whoami.auth_class})
                  {whoami.org_scope ? ` · org ${whoami.org_scope}` : ""} ·{" "}
                  {whoami.permissions_granted.length} permissions granted
                </p>
              )}

              {/* retention sweeper */}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                            alignItems: "center", margin: "6px 0" }}>
                <button type="button" className="btn ghost"
                        onClick={() => void runRetention(true)}>
                  🧹 Retention dry-run
                </button>
                <button type="button" className="btn ghost"
                        onClick={() => void runRetention(false)}>
                  Apply retention (deletes)
                </button>
                <a className="btn ghost" rel="noreferrer"
                   href={api.siemExportUrl(24)} target="_blank">
                  ⬇ SIEM export (NDJSON, 24h)
                </a>
              </div>
              {retentionRep && (
                <p className="muted" style={{ fontSize: 11 }}>
                  {retentionRep.dry_run ? "DRY RUN — nothing deleted: "
                    : "APPLIED — deleted: "}
                  {Object.entries(retentionRep.classes).map(([k, v]) =>
                    `${v.count} ${k.split("_older_than")[0]}`).join(" · ")}
                  <br />Permanent invariants:{" "}
                  {retentionRep.permanent_classes.join(", ")}
                </p>
              )}

              {/* custom connectors */}
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: "pointer" }}>
                  Register connector (admin; activation needs approval)
                </summary>
                <div className="field">
                  <label htmlFor="conn-name">Name</label>
                  <input id="conn-name" value={connForm.name}
                         placeholder="Acme TI Feed"
                         onChange={(e) => setConnForm({
                           ...connForm, name: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="conn-kind">Kind (§80 types A–D)</label>
                  <select id="conn-kind" value={connForm.kind}
                          onChange={(e) => setConnForm({
                            ...connForm, kind: e.target.value })}>
                    <option value="A_methodology">A — methodology</option>
                    <option value="B_discovery">B — discovery connector</option>
                    <option value="C_data_api">C — data API</option>
                    <option value="D_research_distribution">
                      D — research distribution</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="conn-url">Base URL</label>
                  <input id="conn-url" value={connForm.base_url}
                         placeholder="https://ti.acme.example/api"
                         onChange={(e) => setConnForm({
                           ...connForm, base_url: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="conn-env">auth_env — env var NAME only,
                    never the secret (§25)</label>
                  <input id="conn-env" value={connForm.auth_env}
                         placeholder="ACME_TI_API_KEY"
                         onChange={(e) => setConnForm({
                           ...connForm, auth_env: e.target.value })} />
                </div>
                <button type="button" className="btn" onClick={() => void registerConn()}>
                  Register (mint approval)
                </button>
              </details>
              {(connectorsList ?? []).length > 0 && (
                <table className="task-matrix" style={{ marginTop: 8 }}>
                  <thead>
                    <tr><th>Connector</th><th>Kind</th><th>Status</th>
                        <th></th></tr>
                  </thead>
                  <tbody>
                    {(connectorsList ?? []).map((c) => (
                      <tr key={c.id}>
                        <td style={{ fontSize: 11 }}>
                          {c.name}
                          <div className="muted" style={{ fontSize: 10 }}>
                            <code>{c.base_url.slice(0, 40)}</code>
                            {c.auth_env ? ` · $${c.auth_env}` : ""}
                          </div>
                        </td>
                        <td style={{ fontSize: 11 }}>{c.kind}</td>
                        <td>
                          <span className="verdict-chip"
                                data-verdict={c.status === "ACTIVE"
                                  ? "VERIFIED" : c.status === "RETIRED"
                                  ? "MISLEADING" : "UNVERIFIED"}>
                            {c.status}
                          </span>
                        </td>
                        <td>
                          {c.status !== "RETIRED" && (
                            <button type="button" className="btn ghost"
                                    onClick={() => void retireConn(c.id)}>
                              Retire
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
                    {/* risk #9 — reports are deletable (Data sovereignty) */}
                    <button type="button" className="tree-delete"
                            aria-label={`Delete report ${t.tree_id.slice(0, 8)}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              if (window.confirm(
                                "Delete this report and all its task records "
                                + "permanently?")) {
                                api.deleteTree(t.tree_id).then(refreshPanels);
                              }
                            }}>
                      🗑
                    </button>
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
                    {/* v4.6 — one verdict per alert; feeds false-alarm KPI */}
                    {n.adjudication ? (
                      <span className="verdict-chip" data-verdict={
                        n.adjudication === "FALSE_POSITIVE"
                          ? "FALSE" : "VERIFIED"}>
                        {n.adjudication === "FALSE_POSITIVE"
                          ? "false alarm" : "true positive"}
                      </span>
                    ) : (
                      <>
                        <button type="button" className="btn ghost"
                                title="Adjudicate: the alert was real"
                                onClick={() =>
                                  void adjudicate(n.id, "TRUE_POSITIVE")}>
                          ✓ real
                        </button>
                        <button type="button" className="btn ghost"
                                title="Adjudicate: the alert was a false alarm"
                                onClick={() =>
                                  void adjudicate(n.id, "FALSE_POSITIVE")}>
                          ✕ false alarm
                        </button>
                      </>
                    )}
                  </div>
                  <p className="excerpt">{n.body}</p>
                  <div className="meta">{new Date(n.created_at)
                    .toLocaleString()}
                    {n.adjudicated_at
                      ? ` · adjudicated by ${n.adjudicated_by}` : ""}
                  </div>
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

          {/* v3.3 — blueprint v5.2 §3.B: Sovereign Data Stream. Low-level
              view of agent API calls (persisted audit rows) and live system
              heartbeats — each row honestly labelled by persistence. */}
          {pane === "stream" && (
            <div className="card" aria-label="Sovereign Data Stream">
              <h3 style={{ marginTop: 0 }}>🛰 Sovereign Data Stream</h3>
              <p className="dim" style={{ marginTop: -4, fontSize: "0.8rem" }}>
                {stream?.note ??
                  "Persisted audit events plus live volatile pulses."}
              </p>
              <div className="stream-list" role="log" aria-live="off">
                {(stream?.events ?? []).map((e, i) => (
                  <div key={`${e.ts}-${i}`}
                       className={`stream-row kind-${e.kind}`}>
                    <span className="stream-ts">
                      {e.ts.slice(11, 19)}
                    </span>
                    <span className="stream-actor">{e.actor}</span>
                    <span className="stream-text">
                      {e.text}
                      <span className={`stream-badge ${e.persistence}`}>
                        {e.persistence.toUpperCase()}
                      </span>
                    </span>
                  </div>
                ))}
                {(!stream || stream.events.length === 0) && (
                  <p className="dim">No stream events yet — submit a goal or
                    run an L1 audit to light up the trail.</p>
                )}
              </div>
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
              {/* v3.2 checklist J — the safety learning loop, visible */}
              <h4>Safety events (learning loop)</h4>
              {kpis.safety_events &&
              Object.keys(kpis.safety_events).length > 0 ? (
                <ul className="muted" style={{ fontSize: ".82rem" }}>
                  {Object.entries(kpis.safety_events).map(([k, v]) => (
                    <li key={k}>
                      {k.replace(/_/g, " ")}: <strong>{v}×</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted" style={{ fontSize: ".82rem" }}>
                  No safety events yet — halts, plan rejections, incidents and
                  masking hits are counted here so we learn where users push
                  back on the AI.
                </p>
              )}
              {/* v4.5 — §71/§72 pilot read-out (honest-degrading metrics) */}
              <h4 style={{ marginBottom: ".3rem" }}>
                Platform KPIs (§71) — pilot readiness
              </h4>
              {kpis.v71 ? (
                <V71Panel v71={kpis.v71} />
              ) : (
                <p className="muted" style={{ fontSize: ".82rem" }}>
                  v71 KPI engine unavailable on this backend — the plane
                  reports absence, never fabricated numbers (§20).
                </p>
              )}
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
          {/* v3.2 flow #4 — explicit AI-output disclaimer on every report */}
          <p className="ai-disclaimer" role="note">
            ⚠ {report.disclaimer ?? "AI-generated output — verify all "
              + "findings and recommendations with your team's protocols "
              + "before taking action."}
          </p>
          {report.refusal && (
            <p className="review-route" role="alert">
              ⛔ {report.refusal.message}
            </p>
          )}
          {report.halted && (
            <p className="review-route" role="status">
              ■ This execution was halted by the user — results are partial
              and marked as such.
            </p>
          )}
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
      {/* v3.2 blocker G — functional Incident Declaration modal (flow #3) */}
      {crisisOpen && (
        <div className="crisis-modal-overlay" role="presentation"
             onClick={(e) => {
               if (e.target === e.currentTarget) setCrisisOpen(false);
             }}>
          <div className="card crisis-modal" role="dialog"
               aria-modal="true" aria-labelledby="crisis-title">
            <h3 id="crisis-title" style={{ marginTop: 0 }}>
              🚨 Incident Declaration
            </h3>
            <p className="muted" style={{ fontSize: ".85rem" }}>
              This records the incident, notifies the operations channel
              (webhook when configured), and opens the response checklist —
              it does <em>not</em> just change colors.
            </p>
            <div className="field">
              <label htmlFor="sev">Severity</label>
              <select id="sev" value={sev}
                      onChange={(e) => setSev(e.target.value)}>
                <option value="SEV1">SEV-1 — critical, active breach/outage</option>
                <option value="SEV2">SEV2 — major, contained but serious</option>
                <option value="SEV3">SEV3 — minor, watch closely</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="sev-summary">Incident summary</label>
              <textarea id="sev-summary" rows={4} value={sevSummary}
                        placeholder="What happened, what systems, what do you know so far?"
                        onChange={(e) => setSevSummary(e.target.value)} />
            </div>
            <div className="btn-row">
              <button className="btn" type="button"
                      disabled={busy || sevSummary.trim().length < 5}
                      onClick={declareCrisis}>
                Declare &amp; notify on-call
              </button>
              <button className="demo-btn" type="button"
                      onClick={() => setCrisisOpen(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
