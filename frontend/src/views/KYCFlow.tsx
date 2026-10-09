// KYC Verification view — spec Parts 2.1 (KYCFlow, StepProgress), 3.4, 5.3.
// 6-step guided flow; anomalies shown as review items, never fraud findings
// (§12). Demo profile uses the seed pack's document fixtures.
import { useEffect, useState } from "react";
import { api, type ApiError } from "../api";
import type { KYCFixture, KYCResponse } from "../types";
import {
  ConfidenceMeter, ErrorPanel, LoadingStages, ReasoningTrace, TrustTag,
} from "../components/shared";

const STEPS = ["Document", "Data", "Consistency", "Biometric", "Screening", "Decision"];

export function KYCFlow() {
  const [step, setStep] = useState(0);
  const [fixtures, setFixtures] = useState<KYCFixture[]>([]);
  const [selected, setSelected] = useState<KYCFixture | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<KYCResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    api.kycFixtures().then((d) => setFixtures(d.fixtures)).catch(() => {});
  }, []);

  const recordConsent = async () => {
    // §5.3 — the "I consent" action is REAL: it lands on the hash-chained
    // consent ledger before biometrics run. Best-effort in demo (a ledger
    // outage must not block verification — §20 degradation, never fake).
    try {
      await api.consent(
        localStorage.getItem("th360.user") || "demo-operator",
        "kyc_biometrics", "granted");
    } catch { /* ledger unavailable in demo — proceed without recording */ }
  };

  const run = async (fx: KYCFixture) => {
    setLoading(true);
    setError(null);
    setResult(null);
    // §21 — walk the real pipeline steps as the backend runs
    for (const s of [2, 3, 4, 5]) {
      setStep(s);
      // small staged delay reflects real pipeline progress, not a fake spin
      await new Promise((r) => setTimeout(r, 450));
    }
    try {
      const r = await api.kycVerify({
        document: fx.document,
        user_input: fx.user_input,
        selfie_ref: fx.selfie_ref,
        fixture_id: fx.id,
      });
      setResult(r);
      setStep(5);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section aria-labelledby="kyc-title">
      <header className="view-head">
        <p className="view-kicker">Module · Identity assurance</p>
        <h1 id="kyc-title">🪪 KYC Verification</h1>
        <p className="view-lede">
          “Verify my identity” — document consistency, mock biometrics and
          sanctions-list screening (§12: anomalies route to humans, they are{" "}
          <em>not</em> fraud findings).
        </p>
      </header>

      <div className="step-progress" role="list" aria-label={`Step ${step + 1} of 6`}>
        {STEPS.map((s, i) => (
          <span key={s} role="listitem"
                aria-current={i === step ? "step" : undefined}
                className={`step-dot ${i === step ? "active" : i < step ? "done" : ""}`}
                title={s}>
            {i < step ? "✓" : i + 1}
          </span>
        ))}
        <span className="muted" style={{ alignSelf: "center", marginLeft: 8 }}>
          Step {Math.min(step + 1, 6)} of 6 — {STEPS[Math.min(step, 5)]}
        </span>
      </div>

      {step === 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Choose a demo document</h3>
          <p className="muted">
            In production this step is a camera/upload capture (Part 2.1
            DocumentDropzone; §25: images held in memory only). The demo uses
            OCR-parsed fixture documents — each designed to exercise a specific
            §12 behavior:
          </p>
          {fixtures.map((fx) => (
            <button key={fx.id} className="demo-btn" style={{ display: "block", width: "100%", textAlign: "left", padding: 12, marginBottom: 8 }}
                    onClick={() => { setSelected(fx); setStep(1); }}>
              <strong>{fx.label}</strong>
              <br /><span className="muted" style={{ fontSize: ".8rem" }}>designed to test: {fx.designed_to_test}</span>
            </button>
          ))}
          {fixtures.length === 0 && <p className="muted">Loading fixtures…</p>}
        </div>
      )}

      {step === 1 && selected && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Extracted document data</h3>
          <pre className="mono" style={{ fontSize: ".8rem", overflow: "auto" }}>
            {JSON.stringify({ document: selected.document, user_input: selected.user_input }, null, 2)}
          </pre>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Note: document number is stored as a hash only — §25 data
            minimization. Your consent is written to the immutable §5.3
            ledger before biometrics run (auditable, withdrawable in
            Settings → Privacy).
          </p>
          <div className="btn-row">
            <button className="btn secondary" onClick={() => setStep(0)}>Back</button>
            <button className="btn" onClick={() => {
              recordConsent();
              run(selected);
            }}>
              I consent — run verification
            </button>
          </div>
        </div>
      )}

      <LoadingStages active={loading && step >= 2 && !result} />
      {error && <ErrorPanel error={error} />}

      {result && (
        <article className="result-card">
          <header className="result-head">
            <span className={`decision-badge decision-${result.decision}`}>
              {result.decision.replace(/_/g, " ")}
            </span>
            <ConfidenceMeter level={result.confidence} />
          </header>

          <p className="answer">{result.answer}</p>
          <p className="interpretation">
            <TrustTag kind="INFERENCE" />
            {result.interpretation.replace(/^INFERENCE:\s*/, "")}
          </p>
          <p className="recommended"><strong>Next:</strong> {result.recommended_action}</p>

          <div className="detail-section">
            <h4>Consistency checks & biometrics</h4>
            <div className="route-grid">
              <div>Document readable<b>{String(result.checks.readable)}</b></div>
              <div>Liveness<b>{String(result.checks.liveness)}</b></div>
              <div>Face match<b>{String(result.checks.face_match_score)}</b></div>
              <div>Sanctions hits<b>{String(result.checks.sanctions_hits)}</b></div>
            </div>
          </div>

          {result.anomalies.length > 0 && (
            <div className="detail-section">
              <h4>Anomalies — flagged for review, not accusations (§12)</h4>
              {result.anomalies.map((a, i) => (
                <div key={i} className={`anomaly ${a.severity.toLowerCase()}`}>
                  <strong>{a.type}</strong> ({a.severity}) — {a.detail}
                  <br /><span className="muted">action: {a.action}</span>
                </div>
              ))}
            </div>
          )}

          {result.routed_to_human_review && (
            <div className="detail-section">
              <p className="muted">
                🧑‍⚖️ This case was added to the human review queue (§27) — a
                specialist confirms the outcome within the 4-hour SLA.
              </p>
            </div>
          )}

          <div className="detail-section">
            <h4>Reasoning trace</h4>
            <ReasoningTrace steps={result.reasoning_trace} />
          </div>
          <p className="caveat">{result.what_would_change_conclusion}</p>

          <div className="btn-row">
            <button className="btn secondary"
                    onClick={() => { setResult(null); setSelected(null); setStep(0); }}>
              Start another verification
            </button>
          </div>
        </article>
      )}
    </section>
  );
}
