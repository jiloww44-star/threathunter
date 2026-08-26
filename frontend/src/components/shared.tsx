import { useEffect, useState } from "react";
import type {
  Confidence, Contradiction, EvidenceItem, Verdict,
} from "../types";
import type { ApiError } from "../api";

/* ---------------- Meaningful loading stages (§21) ---------------- */
const STAGES = [
  "Analyzing claim...",
  "Comparing sources...",
  "Checking contradictions...",
  "Assessing confidence...",
];

export function LoadingStages({ active }: { active: boolean }) {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    if (!active) { setStage(0); return; }
    const t = setInterval(
      () => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 900);
    return () => clearInterval(t);
  }, [active]);

  if (!active) return null;
  return (
    <div role="status" aria-live="polite" className="stages card">
      {STAGES.map((s, i) => (
        <div key={s}
             className={`stage ${i === stage ? "active" : i < stage ? "done" : ""}`}>
          {i < stage ? "✓" : i === stage ? "◐" : "·"} {s}
        </div>
      ))}
    </div>
  );
}

/* ---------------- Verdict badge (icon+text, not color alone) ---------------- */
const VERDICT_STYLE: Record<Verdict, { icon: string; label: string }> = {
  VERIFIED: { icon: "✔", label: "VERIFIED" },
  MOSTLY_TRUE: { icon: "✔≈", label: "MOSTLY TRUE" },
  PARTIALLY_TRUE: { icon: "◑", label: "PARTIALLY TRUE" },
  MISLEADING: { icon: "⚠", label: "MISLEADING" },
  FALSE: { icon: "✘", label: "FALSE" },
  UNVERIFIED: { icon: "?", label: "UNVERIFIED" },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const s = VERDICT_STYLE[verdict];
  return (
    <span className={`verdict-badge verdict-${verdict}`} aria-label={`Verdict: ${s.label}`}>
      <span aria-hidden="true">{s.icon}</span> {s.label}
    </span>
  );
}

/* ---------------- Confidence meter ---------------- */
const PCT: Record<Confidence, number> = {
  VERY_HIGH: 95, HIGH: 80, MODERATE: 60, LOW: 40, VERY_LOW: 20, UNDETERMINED: 10,
};

export function ConfidenceMeter({ level }: { level: Confidence }) {
  const pct = PCT[level];
  return (
    <div className="confidence-meter" role="meter" aria-valuenow={pct}
         aria-valuemin={0} aria-valuemax={100}
         aria-label={`Confidence ${level.replace(/_/g, " ")}`}>
      <div className="track">
        <div className="confidence-fill conf-Very" style={{ width: `${pct}%` }} />
      </div>
      <div className="conf-label">CONFIDENCE · {level.replace(/_/g, " ")}</div>
    </div>
  );
}

/* ---------------- Trust labels (§26) ---------------- */
export function TrustTag({ kind }: { kind: "FACT" | "INFERENCE" }) {
  return (
    <span className={`trust-tag tag-${kind.toLowerCase()}`}>{kind}</span>
  );
}

/* ---------------- Error panel (§20): what happened / meaning / next step --- */
export function ErrorPanel({ error }: { error: ApiError }) {
  return (
    <div className="error-panel" role="alert">
      <h4>{error.title}</h4>
      <p className="muted" style={{ margin: "4px 0" }}>{error.meaning}</p>
      <p style={{ margin: 0 }}><strong>Next:</strong> {error.next_step}</p>
      <p className="mono muted" style={{ margin: "6px 0 0", fontSize: ".75rem" }}>
        code: {error.code}
      </p>
    </div>
  );
}

/* ---------------- Evidence list with provenance (§16-17) ---------------- */
export function EvidenceList({ items }: { items: EvidenceItem[] }) {
  if (!items.length) return <p className="muted">No evidence items available.</p>;
  return (
    <div data-testid="evidence-list">
      {items.map((e, i) => (
        <div className="evidence-item" key={i}>
          <div className="head">
            <span className="src">{e.source_id}</span>
            <span className={`pill pill-${e.authority}`}>{e.authority}</span>
            <span className={`pill ${e.supports_claim === true ? "pill-support"
              : e.supports_claim === false ? "pill-contradict" : "pill-neutral"}`}>
              {e.supports_claim === true ? "SUPPORTS"
                : e.supports_claim === false ? "CONTRADICTS" : "NEUTRAL"}
            </span>
            {e.is_duplicate_copy && (
              <span className="pill pill-copy" title="Near-identical text from the same independence group — counts as part of one source (copy chain)">
                COPY-CHAIN
              </span>
            )}
          </div>
          <p className="excerpt">{e.excerpt}</p>
          <div className="meta">
            reliability {e.reliability} · independence-group “{e.independence_group}”
            {e.published_at && <> · published {new Date(e.published_at).toLocaleDateString()}</>}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- Contradiction panel ---------------- */
export function ContradictionPanel({ items }: { items: Contradiction[] }) {
  if (!items.length)
    return <p className="muted">No contradictions detected between sources.</p>;
  return (
    <div>
      {items.map((c, i) => (
        <div key={i} className={`contra-item ${c.severity.toLowerCase()}`}>
          <strong>{c.severity}</strong> — {c.description}
        </div>
      ))}
    </div>
  );
}

/* ---------------- Reasoning trace (analysts) ---------------- */
export function ReasoningTrace({ steps }: { steps: string[] }) {
  return (
    <div>
      {steps.map((s, i) => (
        <div className="trace-step" key={i}>{s}</div>
      ))}
    </div>
  );
}

/* ---------------- Source provenance line ---------------- */
export function SourceProvenance({ independent, total }:
  { independent: number; total: number }) {
  return (
    <div className="sources-line">
      SOURCES: <strong>{independent}</strong> independent of{" "}
      <strong>{total}</strong> total — copy-chains are counted once (§1.6)
    </div>
  );
}
