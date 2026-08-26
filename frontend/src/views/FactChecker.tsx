// Fact Checker view — spec Part 2 (components 2.2–2.4), §19 progressive
// disclosure: novice sees answer+confidence first; analysts expand for
// evidence, contradictions, provenance, reasoning trace and the evidence graph.
import { useState } from "react";
import { api, type ApiError } from "../api";
import type { FactCheckResponse } from "../types";
import {
  ConfidenceMeter, ContradictionPanel, ErrorPanel, EvidenceList,
  LoadingStages, ReasoningTrace, SourceProvenance, TrustTag, VerdictBadge,
} from "../components/shared";
import { EvidenceGraph } from "../components/EvidenceGraph";
import { useVoice, speakResult, stopSpeaking } from "../hooks/useVoice";

const DEMO_CLAIMS = [
  "Company X was sanctioned in August 2026",
  "A celebrity secretly married in Lagos last week",
  "Vendor Y lost its operating license in March 2026",
  "A flood warning was issued in Lagos on 18 August 2026",
];

export function FactChecker() {
  const [claim, setClaim] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<FactCheckResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const MAX = 280;
  const over = claim.length > MAX;

  const voice = useVoice((t) => setClaim(t.slice(0, MAX)));

  const submit = async (c?: string) => {
    const text = (c ?? claim).trim();
    if (!text || over) return;
    setLoading(true);
    setResult(null);
    setError(null);
    stopSpeaking();
    try {
      const r = await api.factCheck(text);
      setResult(r);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  };

  const reassess = async () => {
    if (!result?.check_id) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.reassess(result.check_id));
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section aria-labelledby="fc-title">
      <header className="view-head">
        <p className="view-kicker">Module · Evidence adjudication</p>
        <h1 id="fc-title">🔍 Fact Checker</h1>
        <p className="view-lede">
          “Is this claim true?” — claims are resolved against the evidence store:
          every source scored for reliability and editorial independence (§1.6).
        </p>
      </header>

      <form className="card" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="field">
          <label htmlFor="claim">Enter a claim to verify</label>
          <textarea id="claim" rows={3} value={claim}
                    onChange={(e) => setClaim(e.target.value)}
                    aria-describedby="char-count"
                    placeholder="e.g. Company X was sanctioned in August 2026" />
          <div id="char-count" aria-live="polite"
               className={`char-counter ${over ? "over" : ""}`}>
            Characters: {claim.length} / {MAX}
          </div>
        </div>
        <div className="btn-row">
          <button className="btn" type="submit"
                  disabled={over || !claim.trim() || loading}>
            Check Fact
          </button>
          {voice.supported && (
            <button type="button"
                    className={`mic-btn ${voice.listening ? "listening" : ""}`}
                    onClick={() => (voice.listening ? voice.stop() : voice.start())}
                    aria-pressed={voice.listening}
                    title="Speak the claim (voice input, §18)">
              {voice.listening ? "⏹ Listening…" : "🎤 Speak"}
            </button>
          )}
        </div>
        <div aria-label="Demo claims">
          {DEMO_CLAIMS.map((c) => (
            <button key={c} type="button" className="demo-btn"
                    onClick={() => { setClaim(c); submit(c); }}>
              {c.length > 40 ? c.slice(0, 38) + "…" : c}
            </button>
          ))}
        </div>
      </form>

      <LoadingStages active={loading} />
      {error && <ErrorPanel error={error} />}
      {result && <IntelligenceResult r={result} onReassess={reassess} onSpeak={() => speakResult(result as unknown as Record<string, unknown>)} />}
    </section>
  );
}

export function IntelligenceResult({ r, onReassess, onSpeak }: {
  r: FactCheckResponse;
  onReassess?: () => void;
  onSpeak?: () => void;
}) {
  const [showDetail, setShowDetail] = useState(false);

  return (
    <article className="result-card" aria-live="polite">
      {/* Novice view first — §19 */}
      <header className="result-head">
        <VerdictBadge verdict={r.verdict} />
        <ConfidenceMeter level={r.confidence} />
      </header>

      <p className="answer">{r.answer}</p>

      <p className="interpretation">
        <TrustTag kind="INFERENCE" />
        {r.interpretation.replace(/^INFERENCE:\s*/, "")}
      </p>

      <p className="recommended"><strong>Recommended action:</strong> {r.recommended_action}</p>
      <SourceProvenance independent={r.sources_independent} total={r.sources_total} />
      {r.review_route && (
        <p className="review-route" title="Part 18 D1 — where this verdict was routed after scoring (disclosed, never silently skipped)">
          🧭 Review lane: <strong>{r.review_route === "AUTO_PUBLISH"
            ? "auto-published (high confidence · low stakes)"
            : r.review_route === "AUDIT_SAMPLE"
            ? "published + random 5% QA audit"
            : "human review queue (mandatory rule fired)"}</strong>
        </p>
      )}
      {r.copy_chain_note && (
        <p className="copy-chain-note" title="Near-identical articles are grouped into text clusters; one effective voice is counted once (§1.6)">
          🔗 {r.copy_chain_clusters} copy-chain cluster{r.copy_chain_clusters === 1 ? "" : "s"}: {r.copy_chain_note}
        </p>
      )}

      <div className="btn-row">
        <button className="disclosure" onClick={() => setShowDetail((v) => !v)}
                aria-expanded={showDetail}>
          {showDetail ? "▴ Hide full analysis" : "▾ Show full analysis"}
        </button>
        {onSpeak && "speechSynthesis" in window && (
          <button className="btn secondary" onClick={onSpeak}>🔊 Listen</button>
        )}
        {onReassess && r.check_id && (
          <button className="btn secondary" onClick={onReassess}
                  title="Re-test this claim against newly ingested evidence (§1.10)">
            ⟳ Re-assess
          </button>
        )}
      </div>

      {/* Analyst view — progressively disclosed */}
      {showDetail && (
        <>
          <div className="detail-section">
            <h4>Key evidence</h4>
            <EvidenceList items={r.key_evidence} />
          </div>
          <div className="detail-section">
            <h4>Contradictions</h4>
            <ContradictionPanel items={r.contradictions} />
          </div>
          <div className="detail-section">
            <h4>Reasoning trace</h4>
            <ReasoningTrace steps={r.reasoning_trace} />
          </div>
          {r.check_id && <CaseGraph checkId={r.check_id} />}
          <p className="caveat">
            What would change this conclusion: {r.what_would_change_conclusion}
          </p>
        </>
      )}
    </article>
  );
}

function CaseGraph({ checkId }: { checkId: string }) {
  const [data, setData] = useState<import("../types").GraphData | null>(null);
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="detail-section">
      <h4>Evidence graph</h4>
      {!loaded ? (
        <button className="btn secondary" onClick={async () => {
          setData(await api.caseGraph(checkId));
          setLoaded(true);
        }}>
          Load relationship graph
        </button>
      ) : data && data.nodes.length ? (
        <EvidenceGraph data={data} />
      ) : (
        <p className="muted">No graph available for this case yet.</p>
      )}
    </div>
  );
}
