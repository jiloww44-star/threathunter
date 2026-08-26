import { useEffect, useState } from "react";
import { Home } from "./views/Home";
import { FactChecker } from "./views/FactChecker";
import { JourneyAdvisor } from "./views/JourneyAdvisor";
import { KYCFlow } from "./views/KYCFlow";
import { Analytics } from "./views/Analytics";
import { OpsNode } from "./views/OpsNode";

type Route = "home" | "ops" | "fact-check" | "journey" | "kyc" | "analytics";

function routeFromHash(): Route {
  const h = window.location.hash.replace("#/", "");
  return (["ops", "fact-check", "journey", "kyc", "analytics"] as Route[]).includes(h as Route)
    ? (h as Route)
    : "home";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash());

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
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
        </nav>
      </header>

      <main id="main">
        {route === "home" && <Home />}
        {route === "ops" && <OpsNode />}
        {route === "fact-check" && <FactChecker />}
        {route === "journey" && <JourneyAdvisor />}
        {route === "kyc" && <KYCFlow />}
        {route === "analytics" && <Analytics />}
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
