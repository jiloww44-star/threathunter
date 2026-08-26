"""SENTINEL agent — spec A-03 (+ A-04 forensic sub-agent).

Closed-loop vulnerability operations in demo profile:
enumerate_assets → scan_cves → score_vpr → open_remediation_tickets.
Patching itself is never autonomous: `request_patch` routes through
AUDITOR.authorize_action which returns REQUIRE_HUMAN (§27, R-05).

Data comes from seed fixtures (spec Part 10: zero external dependencies);
live NVD/CISA feeds slot into the same fixture shapes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ...config import SEED_ROOT
from ...store.db import EvidenceStore
from . import auditor


def _load(name: str, default):
    p = SEED_ROOT / "fixtures" / name
    if p.exists():
        return json.loads(p.read_text())
    return default


def _parse_ver(v: str) -> tuple:
    out = []
    for part in v.replace("p", ".").split("."):
        try:
            out.append(int("".join(ch for ch in part if ch.isdigit()) or 0))
        except ValueError:
            out.append(0)
    return tuple(out)


def enumerate_assets() -> dict:
    inv = _load("asset_inventory.json", {"assets": []})
    if not inv["assets"]:
        # §20 — classified, honest degradation, never fabrication
        return {"classified_error": "SOURCE_UNAVAILABLE",
                "note": "asset inventory feed unavailable — no scan possible",
                "assets": []}
    return {"assets": inv["assets"], "count": len(inv["assets"]),
            "collected_at": inv.get("collected_at")}


def scan_cves(assets: list[dict] | None = None) -> dict:
    feed = _load("cve_feed.json", {"cves": []})
    if not feed["cves"]:
        return {"classified_error": "SOURCE_UNAVAILABLE",
                "note": "CVE feed unavailable — scan degraded", "findings": []}
    if assets is None:
        assets = enumerate_assets().get("assets", [])
    findings = []
    for a in assets:
        for sw in a.get("software", []):
            for cve in feed["cves"]:
                if cve["product"] != sw["product"]:
                    continue
                if _parse_ver(sw["version"]) >= _parse_ver(
                        cve["affected_below"]):
                    continue
                findings.append({
                    "asset_id": a["asset_id"], "host": a["host"],
                    "kind": a["kind"], "criticality": a["criticality"],
                    "exposure": a["exposure"], "owner": a["owner"],
                    "product": sw["product"], "installed": sw["version"],
                    "fixed_at_or_above": cve["affected_below"],
                    "cve_id": cve["cve_id"], "cvss": cve["cvss"],
                    "epss": cve["epss"], "poc_available": cve["poc_available"],
                    "exploited_in_wild": cve["exploited_in_wild"],
                    "kev": cve.get("kev", False), "summary": cve["summary"],
                })
    return {"findings": findings, "feed_fetched_at": feed.get("fetched_at"),
            "assets_scanned": len(assets), "cves_considered": len(feed["cves"])}


def score_vpr(findings: list[dict]) -> list[dict]:
    """VPR-style prioritization (A-03): threat-weighted, honest formula —
    weights are disclosed in every result row so analysts can audit them."""
    w = {"cvss": 0.35, "epss": 0.25, "poc": 0.15, "wild": 0.15,
         "exposure": 0.10}
    out = []
    for f in findings:
        exposure = 1.0 if f["exposure"] == "internet-facing" else 0.3
        score = (w["cvss"] * f["cvss"] / 10 + w["epss"] * f["epss"]
                 + w["poc"] * (1 if f["poc_available"] else 0)
                 + w["wild"] * (1 if f["exploited_in_wild"] else 0)
                 + w["exposure"] * exposure)
        crit = {"CRITICAL": 1.15, "HIGH": 1.0, "MODERATE": 0.85,
                "LOW": 0.7}.get(f["criticality"], 1.0)
        vpr = round(min(10.0, score * crit * 10), 2)
        priority = ("P1" if vpr >= 8.5 else "P2" if vpr >= 7.0
                    else "P3" if vpr >= 5.0 else "P4")
        out.append({**f, "vpr": vpr, "priority": priority,
                    "vpr_weights": w,
                    "trust_label": "INFERENCE"})  # score is INFERENCE (§26)
    return sorted(out, key=lambda r: r["vpr"], reverse=True)


def open_remediation_tickets(store: EvidenceStore,
                             scored: list[dict]) -> dict:
    """Auto-ticketing (A-03): P1/P2 findings enter the §27 human review queue
    (remediation has external effects; tier MANDATORY_REVIEW per TRUST.md
    blast-radius table). P3/P4 are reported back without queue noise."""
    tickets = []
    for f in scored:
        if f["priority"] not in ("P1", "P2"):
            continue
        rid = store.enqueue_review(
            module="sentinel",
            case_ref=f"{f['cve_id']}@{f['asset_id']}",
            reason=(f"SENTINEL {f['priority']} remediation: {f['cve_id']} "
                    f"({f['summary']}) on {f['host']} — VPR {f['vpr']}. "
                    f"Fix: upgrade {f['product']} ≥ {f['fixed_at_or_above']}."),
            risk="HIGH" if f["priority"] == "P1" else "MODERATE",
            priority=90 if f["priority"] == "P1" else 60,
            tier="MANDATORY_REVIEW")
        tickets.append({"queue_id": rid, "cve_id": f["cve_id"],
                        "asset_id": f["asset_id"], "priority": f["priority"],
                        "tier": "MANDATORY_REVIEW"})
    return {"tickets": tickets, "opened": len(tickets),
            "note": ("Remediation tickets open in the human review queue — "
                     "patches execute only after human approval (§27).")}


def request_patch(store: EvidenceStore, cve_id: str, asset_id: str) -> dict:
    """Patching is an external-effect action — ethically gated (A-06, R-05).
    Never executes autonomously in v3.0."""
    auth = auditor.authorize_action(
        store, actor="SENTINEL", action="apply_patch",
        detail=f"{cve_id} on {asset_id}")
    return {"cve_id": cve_id, "asset_id": asset_id,
            "patch_state": ("AWAITING_HUMAN_APPROVAL"
                            if auth["decision"] == "REQUIRE_HUMAN"
                            else auth["decision"]),
            "authorization": auth,
            "note": "Closed loop held open for a human (§27): no patch ran."}


# ----------------------------------------------------------------- A-04 ----
def analyze_media(ref: str | None) -> dict:
    """SENTINEL Forensic Sub-Agent (A-04). Demo provider is heuristic over
    mock refs; without a recognizable ref it degrades to UNVERIFIED honestly
    (§1.9: unverifiable ≠ fake)."""
    checks = {"presentation_attack": None, "synthetic_artifacts": None,
              "metadata_consistency": None}
    if ref == "mock:pass":
        verdict, conf = "LIKELY_AUTHENTIC", "MODERATE"
        checks = {k: "PASS" for k in checks}
        note = ("No strong manipulation indicators in heuristic checks. "
                "'Likely' — heuristic analysis cannot prove authenticity (§9).")
    elif ref == "mock:spoof":
        verdict, conf = "MANIPULATION_SUSPECTED", "MODERATE"
        checks["presentation_attack"] = "FAIL"
        note = ("Presentation-attack indicators detected. This is a signal "
                "for additional verification, not a verdict of fraud (§12).")
    elif ref == "mock:low_quality":
        verdict, conf = "UNVERIFIED", "LOW"
        checks["synthetic_artifacts"] = "INSUFFICIENT_SIGNAL"
        note = ("Capture quality too low for reliable analysis — recapture "
                "advised. Unverifiable is not 'fake' (§1.9).")
    else:
        verdict, conf = "UNVERIFIED", "UNDETERMINED"
        note = ("No forensic provider configured for this reference in the "
                "demo profile — degraded honestly (§20 SOURCE_UNAVAILABLE).")
    return {"media_ref": ref, "assessment": verdict, "confidence": conf,
            "checks": checks, "note": note, "trust_label": "EVIDENCE",
            "analyzed_at": datetime.now(timezone.utc).isoformat()}


def liveness_check(ref: str | None) -> dict:
    from ...core.kyc import MockBiometricProvider
    r = MockBiometricProvider().liveness(ref)
    return {"liveness_passed": r.passed, "score": r.score,
            "failure_reason": r.failure_reason,
            "trust_label": "EVIDENCE"}
