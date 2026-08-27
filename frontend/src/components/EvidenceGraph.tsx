// Evidence graph visualization — spec Part 12 (Neo4j model, SVG layout).
// Nodes colored by type; COPIED_FROM edges render thick red — making the
// echo-chain instantly visible. Click a node → provenance panel (§17).
import { useMemo, useState } from "react";
import type { GraphData } from "../types";

const COLORS: Record<string, string> = {
  Claim: "#22c55e",
  Hypothesis: "#ef4444",
  Evidence: "#0891b2",
  Source: "#8b5cf6",
  Entity: "#2563eb",
  Event: "#f59e0b",
};

export function EvidenceGraph({ data }: { data: GraphData }) {
  const [selected, setSelected] = useState<GraphData["nodes"][number] | null>(null);

  const layout = useMemo(() => {
    // Deterministic radial layout: Claim at center, hypotheses ring-1,
    // evidence ring-2, sources ring-3.
    const cx = 480, cy = 200;
    const ranks: Record<string, { r: number }> = {
      Claim: { r: 0 },
      Hypothesis: { r: 95 },
      Evidence: { r: 165 },
      Source: { r: 185 },
    };
    const buckets: Record<string, GraphData["nodes"][number][]> = {};
    for (const n of data.nodes) (buckets[n.type] ||= []).push(n);

    const pos = new Map<string, { x: number; y: number }>();
    for (const [type, nodes] of Object.entries(buckets)) {
      const r = ranks[type]?.r ?? 150;
      if (r === 0) {
        pos.set(nodes[0].id, { x: cx, y: cy });
        continue;
      }
      nodes.forEach((n, i) => {
        const angle = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
        const jitter = type === "Source" ? 25 : 0;
        pos.set(n.id, {
          x: cx + Math.cos(angle) * (r + jitter * Math.sin(i * 3)),
          y: cy + Math.sin(angle) * (r + jitter) ,
        });
      });
    }
    return pos;
  }, [data]);

  const nodeById = useMemo(
    () => new Map(data.nodes.map((n) => [n.id, n])), [data]);

  return (
    <div className="graph-wrap">
      <svg className="graph-svg" viewBox="0 0 960 420" role="img"
           aria-label="Evidence relationship graph">
        {data.edges.map((e) => {
          const a = layout.get(e.source), b = layout.get(e.target);
          if (!a || !b) return null;
          const copied = e.type === "COPIED_FROM";
          return (
            <g key={e.id}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    stroke={copied ? "#ef4444" : "#334155"}
                    strokeWidth={copied ? 3 : 1.2}
                    strokeDasharray={e.type === "TESTED_BY" ? "4 3" : undefined} />
            </g>
          );
        })}
        {data.nodes.map((n) => {
          const p = layout.get(n.id);
          if (!p) return null;
          const r = n.type === "Claim" ? 14 : n.type === "Source" ? 9 : 11;
          return (
            <g key={n.id} onClick={() => setSelected(n)}
               style={{ cursor: "pointer" }} role="button" tabIndex={0}
               aria-label={`${n.type}: ${n.label}`}>
              <circle cx={p.x} cy={p.y} r={r}
                      fill={COLORS[n.type] || "#64748b"}
                      stroke={selected?.id === n.id ? "#fff" : "none"}
                      strokeWidth={2} />
              <text x={p.x} y={p.y + r + 12} textAnchor="middle" fontSize="9"
                    fill="currentColor" opacity={0.85}>
                {n.label.length > 26 ? n.label.slice(0, 24) + "…" : n.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="graph-legend">
        {Object.entries(COLORS).map(([k, c]) => (
          <span key={k}><i style={{ background: c }} />{k}</span>
        ))}
        <span><i style={{ background: "#ef4444", borderRadius: 2, width: 14, height: 3 }} /> COPIED_FROM (copy chain)</span>
      </div>

      {selected && (
        <aside className="provenance-panel" role="complementary"
               aria-label="Node provenance">
          <h4>{selected.type}: {selected.label}</h4>
          <dl>
            {typeof selected.reliability === "string" && (
              <><dt>Reliability</dt><dd>{String(selected.reliability)}</dd></>)}
            {typeof selected.authority === "string" && (
              <><dt>Authority</dt><dd>{String(selected.authority)}</dd></>)}
            {typeof selected.independence_group === "string" && (
              <><dt>Independence</dt><dd>{String(selected.independence_group)}</dd></>)}
            {typeof selected.status === "string" && (
              <><dt>Status</dt><dd>{String(selected.status)}</dd></>)}
            {typeof selected.score === "number" && (
              <><dt>Score</dt><dd>{selected.score.toFixed(2)}</dd></>)}
            {typeof selected.supports_claim === "boolean" && (
              <><dt>Stance</dt><dd>{selected.supports_claim ? "SUPPORTS" : "CONTRADICTS"}</dd></>)}
            {typeof selected.url === "string" && (
              <><dt>Obtained</dt><dd className="mono">{String(selected.url).slice(0, 60)}</dd></>)}
          </dl>
          <button className="btn secondary" onClick={() => setSelected(null)}>
            Close
          </button>
        </aside>
      )}
    </div>
  );
}
