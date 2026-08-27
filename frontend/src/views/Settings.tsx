// Settings — v3.0 §5.3 consent ledger + §3.4 personalization (within
// evidence bounds) + §5.4 access modes. Privacy controls are real: consent
// entries are hash-chained server-side; preferences never touch scoring.
import { useCallback, useEffect, useState } from "react";
import { api, type ApiError } from "../api";
import type { ConsentLedgerView, Prefs } from "../types";
import { ErrorPanel } from "../components/shared";
import {
  applyBandwidthAttr, getBandwidthMode, isLowBandwidth, setBandwidthMode,
  type BandwidthMode,
} from "../hooks/useBandwidth";

const PURPOSE_LABEL: Record<string, string> = {
  kyc_biometrics: "KYC biometrics",
  personalization: "Personalization",
  journey_history: "Journey history",
  analytics: "Analytics",
};

const USER_KEY = "th360.user";

function demoUser(): string {
  return localStorage.getItem(USER_KEY) || "demo-operator";
}

export function Settings() {
  const [userId, setUserId] = useState(demoUser());
  const [consent, setConsent] = useState<Record<string, string>>({});
  const [ledgerOk, setLedgerOk] = useState<boolean | null>(null);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [watchInput, setWatchInput] = useState("");
  const [mode, setMode] = useState<BandwidthMode>(getBandwidthMode());
  const [error, setError] = useState<ApiError | null>(null);
  const [savedNote, setSavedNote] = useState("");

  const load = useCallback(async (uid: string) => {
    setError(null);
    try {
      const [c, l, p] = await Promise.all([
        api.consentState(uid), api.consentLedger(), api.getPrefs(uid),
      ]);
      setConsent(c.purposes);
      setLedgerOk(l.verification.chain_intact);
      setPrefs(p);
    } catch (e) {
      setError(e as ApiError);
    }
  }, []);

  useEffect(() => { load(userId); }, [userId, load]);

  const setConsentState = async (purpose: string, state: "granted" | "withdrawn") => {
    try {
      await api.consent(userId, purpose, state);
      await load(userId);
    } catch (e) {
      setError(e as ApiError);
    }
  };

  const savePrefs = async (patch: Partial<Prefs>) => {
    setSavedNote("");
    try {
      const next = await api.savePrefs(userId, patch);
      setPrefs(next);
      setSavedNote("Saved — applies to presentation & alerts only (§3.4).");
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "CONSENT_REQUIRED") {
        setError(err);
      } else {
        setError(err);
      }
    }
  };

  const pickUser = (uid: string) => {
    const clean = uid.trim() || "demo-operator";
    localStorage.setItem(USER_KEY, clean);
    setUserId(clean);
  };

  const lowNow = isLowBandwidth();

  return (
    <section aria-labelledby="set-title">
      <header className="view-head">
        <p className="view-kicker">v3.0 · Privacy & Personalization</p>
        <h1 id="set-title">⚙️ Settings</h1>
        <p className="view-lede">
          Consent is hash-chained and immutable (§5.3). Personalization shapes
          presentation, notifications and defaults — <em>never</em> confidence,
          verdicts or risk scores (§3.4). Access modes adapt the UI to your
          device and network (§5.4).
        </p>
      </header>

      <div className="card" style={{ maxWidth: 520 }}>
        <div className="field">
          <label htmlFor="demo-user">Demo user</label>
          <input id="demo-user" type="text" defaultValue={userId}
                 onBlur={(e) => pickUser(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" &&
                   pickUser((e.target as HTMLInputElement).value)} />
          <p className="muted" style={{ fontSize: ".78rem", margin: "6px 0 0" }}>
            Demo profile identity — consent and preferences attach to this id.
          </p>
        </div>
      </div>

      <div className="settings-grid">
        {/* ----------------------------- §5.3 privacy ------------------- */}
        <div className="card" aria-label="Privacy and consent">
          <h3 style={{ marginTop: 0 }}>🔏 Privacy & consent ledger</h3>
          <p className="muted" style={{ marginTop: 0, fontSize: ".82rem" }}>
            Ledger integrity:{" "}
            {ledgerOk === null ? "checking…" : ledgerOk
              ? <strong style={{ color: "var(--color-evidence)" }}>
                  ✓ hash-chain intact</strong>
              : <strong style={{ color: "#ef4444" }}>✕ TAMPER DETECTED</strong>}
          </p>
          {Object.entries(PURPOSE_LABEL).map(([purpose, label]) => {
            const state = consent[purpose] ?? "never_asked";
            return (
              <div key={purpose} className="consent-row">
                <div>
                  <strong>{label}</strong>
                  <p className="muted" style={{ margin: "2px 0 0", fontSize: ".78rem" }}>
                    {state === "never_asked" ? "never asked" : state}
                  </p>
                </div>
                {state === "granted" ? (
                  <button type="button" className="demo-btn"
                          onClick={() => setConsentState(purpose, "withdrawn")}>
                    Withdraw
                  </button>
                ) : (
                  <button type="button" className="demo-btn"
                          onClick={() => setConsentState(purpose, "granted")}>
                    Grant
                  </button>
                )}
              </div>
            );
          })}
          <p className="caveat" style={{ marginBottom: 0 }}>
            Withdrawal is recorded as a new entry — past grants stay provable,
            nothing is deleted. Auditors verify the chain via{" "}
            <span className="mono">/api/v1/privacy/ledger</span>.
          </p>
        </div>

        {/* -------------------- §3.4 personalization -------------------- */}
        <div className="card" aria-label="Personalization">
          <h3 style={{ marginTop: 0 }}>🎛 Personalization</h3>
          {consent.personalization !== "granted" && (
            <p className="muted" role="status" style={{ fontSize: ".82rem" }}>
              Saving preferences requires the <b>Personalization</b> consent
              above (§5.3) — nothing is stored silently.
            </p>
          )}
          {error && <ErrorPanel error={error} />}
          {savedNote && <p className="muted" role="status">{savedNote}</p>}
          {prefs && (
            <>
              <div className="field">
                <label htmlFor="pref-priority">Default route priority</label>
                <select id="pref-priority" value={prefs.journey_priority}
                        onChange={(e) =>
                          savePrefs({ journey_priority: e.target.value })}>
                  <option value="balanced">Balanced</option>
                  <option value="safest">Safest</option>
                  <option value="fastest">Fastest</option>
                  <option value="lowest_exposure">Lowest exposure</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="pref-tolerance">Default alert threshold</label>
                <select id="pref-tolerance" value={prefs.notify_tolerance}
                        onChange={(e) =>
                          savePrefs({ notify_tolerance: e.target.value })}>
                  <option value="LOW">LOW — alert on any drift</option>
                  <option value="MODERATE">MODERATE</option>
                  <option value="HIGH">HIGH — only serious elevation</option>
                  <option value="CRITICAL">CRITICAL — emergencies only</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="pref-format">Output format (§19)</label>
                <select id="pref-format" value={prefs.output_format}
                        onChange={(e) =>
                          savePrefs({ output_format: e.target.value })}>
                  <option value="novice">Novice — conclusion first</option>
                  <option value="analyst">Analyst — evidence expanded</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="watch-add">Entity watchlists (v1 §22)</label>
                <div className="chip-editor">
                  {prefs.watchlists.map((w) => (
                    <span key={w} className="chip">
                      {w}
                      <button type="button" aria-label={`Remove ${w}`}
                              onClick={() => savePrefs({
                                watchlists: prefs.watchlists
                                  .filter((x) => x !== w),
                              })}>×</button>
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <input id="watch-add" type="text" value={watchInput}
                         placeholder="e.g. Third Mainland Bridge"
                         onChange={(e) => setWatchInput(e.target.value)} />
                  <button type="button" className="demo-btn"
                          disabled={!watchInput.trim()}
                          onClick={() => {
                            savePrefs({
                              watchlists: [...prefs.watchlists,
                                           watchInput.trim()],
                            });
                            setWatchInput("");
                          }}>
                    Add
                  </button>
                </div>
                <p className="muted" style={{ fontSize: ".78rem", margin: "6px 0 0" }}>
                  Watched entities trigger <b>alerts</b> when new signals
                  arrive (§1.10 loop) — never verdict changes.
                </p>
              </div>
            </>
          )}
          <p className="caveat" style={{ marginBottom: 0 }}>
            “Personalization shapes presentation, not conclusions.” — §3.4,
            enforced by the test suite.
          </p>
        </div>

        {/* ------------------------- §5.4 access ------------------------ */}
        <div className="card" aria-label="Access modes">
          <h3 style={{ marginTop: 0 }}>📶 Access & bandwidth (§5.4)</h3>
          <div className="field">
            <label htmlFor="bw-mode">Bandwidth mode</label>
            <select id="bw-mode" value={mode}
                    onChange={(e) => {
                      const m = e.target.value as BandwidthMode;
                      setMode(m);
                      setBandwidthMode(m);
                    }}>
              <option value="auto">Auto — follow my device (Save-Data / 2G)</option>
              <option value="on">Always low — text-first everywhere</option>
              <option value="off">Full — maps & rich visuals</option>
            </select>
          </div>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            Current: <strong>{lowNow ? "LOW-bandwidth (text-first)" :
            "full"}</strong>. In low-bandwidth mode, map tiles are skipped and
            journeys render as text risk strips with identical information.
          </p>
          <p className="muted" style={{ fontSize: ".82rem", marginBottom: 0 }}>
            Motion communicates state throughout; your OS{" "}
            <span className="mono">prefers-reduced-motion</span> setting is
            honored automatically across every view.
          </p>
        </div>
      </div>
    </section>
  );
}
