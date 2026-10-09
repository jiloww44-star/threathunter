import { useEffect, useState } from "react";
import { Home } from "./views/Home";
import { FactChecker } from "./views/FactChecker";
import { JourneyAdvisor } from "./views/JourneyAdvisor";
import { KYCFlow } from "./views/KYCFlow";
import { Analytics } from "./views/Analytics";
import { OpsNode } from "./views/OpsNode";
import { Settings } from "./views/Settings";
import { applyBandwidthAttr } from "./hooks/useBandwidth";

type Route = "home" | "ops" | "fact-check" | "journey" | "kyc" | "analytics" | "settings";

function routeFromHash(): Route {
  const h = window.location.hash.replace("#/", "");
  const alias = h === "govern" ? "settings" : h;  // v5.2 §6.C — "Govern" tab
  return (["ops", "fact-check", "journey", "kyc", "analytics", "settings"] as Route[]).includes(alias as Route)
    ? (alias as Route)
    : "home";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash());

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // §5.4 — bandwidth attribute drives text-first degradation app-wide
  useEffect(() => {
    applyBandwidthAttr();
    const onChange = () => applyBandwidthAttr();
    window.addEventListener("th360-bandwidth", onChange);
    return () => window.removeEventListener("th360-bandwidth", onChange);
  }, []);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="logo">
          <span className="mark" aria-hidden="true">◈</span>
          <span>
            ThreatHunter<span style={{ color: "var(--color-evidence)" }}>360</span>
          </span>
        </div>
        <nav className="nav" aria-label="Main modules">
          <a href="#/ops" className={route === "ops" ? "active" : ""}>
            ◈ Ops Node
          </a>
          <a href="#/" className={route === "home" ? "active" : ""}>Home</a>
          <a href="#/fact-check" className={route === "fact-check" ? "active" : ""}>
            Fact Checker
          </a>
          <a href="#/journey" className={route === "journey" ? "active" : ""}>
            Journey Advisor
          </a>
          <a href="#/kyc" className={route === "kyc" ? "active" : ""}>KYC Verify</a>
          <a href="#/analytics" className={route === "analytics" ? "active" : ""}>
            Analytics
          </a>
          <a href="#/govern" className={route === "settings" ? "active" : ""}
             aria-label="Govern — consent ledger, compliance index, data sovereignty">
            ⚖ Govern
          </a>
        </nav>
      </header>

      {/* blueprint v5.2 §3.B — mobile-first fixed bottom-nav */}
      <nav className="bottomnav" aria-label="Mobile module navigation">
        <a href="#/ops" className={route === "ops" ? "active" : ""}>◈<span>Ops</span></a>
        <a href="#/" className={route === "home" ? "active" : ""}>⌂<span>Home</span></a>
        <a href="#/fact-check" className={route === "fact-check" ? "active" : ""}>✓<span>Facts</span></a>
        <a href="#/journey" className={route === "journey" ? "active" : ""}>➤<span>Journey</span></a>
        <a href="#/kyc" className={route === "kyc" ? "active" : ""}>🛡<span>KYC</span></a>
        <a href="#/govern" className={route === "settings" ? "active" : ""}>⚖<span>Govern</span></a>
      </nav>

      <main id="main">
        {route === "home" && <Home />}
        {route === "ops" && <OpsNode />}
        {route === "fact-check" && <FactChecker />}
        {route === "journey" && <JourneyAdvisor />}
        {route === "kyc" && <KYCFlow />}
        {route === "analytics" && <Analytics />}
        {route === "settings" && <Settings />}
      </main>

      <footer className="footer-note">
        ThreatHunter360 v3.0 SOVEREIGN FUSION demo profile — evidence-based
        conclusions, honest uncertainty, provenance everywhere, humans in
        command. Trust labels:
        <span className="trust-tag tag-fact" style={{ marginLeft: 8 }}>FACT</span>
        <span className="trust-tag tag-inference">INFERENCE</span>
      </footer>
    </div>
  );
}
