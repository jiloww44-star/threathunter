"""VOYAGER — Journey & Situational Advisor agent (spec §5.1).

Guardian-of-Passage: restores the v1 journey domains (§5–9) the v2 swarm
dropped, plus live journey monitoring (P3). Built on the deterministic
core/journey.py model; every prediction stays hedged (§9) and every level
change carries a 'why' (§7).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ...core import journey as jr
from ...models.schemas import JourneyRequest
from ...store.db import EvidenceStore

_RISK_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def parse_route_context(text: str) -> dict:
    """Extract origin/destination/departure hints from free text so the Cortex
    and RGD only ask for what is materially missing (§14–15)."""
    import re
    out: dict = {"origin": None, "destination": None, "departure_hint": None}
    m = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s+(?:at|by|around|tomorrow|"
                  r"today|tonight|this)\b|$)", text, re.I)
    if m:
        origin = re.sub(r"^(?:from|to)\s+", "", m.group(1).strip(" .,?"),
                        flags=re.I)
        dest = re.sub(r"^(?:from|to)\s+", "", m.group(2).strip(" .,?"),
                      flags=re.I)
        out["origin"] = origin or None
        out["destination"] = dest or None
    else:
        m2 = re.search(r"\bto\s+([A-Z][\w' -]{2,})", text)
        if m2:
            out["destination"] = m2.group(1).strip(" .,?")
    tl = text.lower()
    if "tomorrow" in tl:
        out["departure_hint"] = "tomorrow"
    elif "tonight" in tl:
        out["departure_hint"] = "tonight"
    elif "today" in tl or "now" in tl:
        out["departure_hint"] = "today"
    return out


def _req(origin: str, destination: str,
         departure_time: datetime | None = None,
         priority: str = "balanced") -> JourneyRequest:
    return JourneyRequest(origin=origin, destination=destination,
                          departure_time=departure_time, priority=priority)


async def assess_journey(req: JourneyRequest):
    """§5.1 row 1 — delegates to the v1 risk model (restored parity)."""
    return await jr.assess_journey(req)


def build_risk_timeline(req: JourneyRequest):
    """§5.1 row 2 (v1 §7) — chronological transitions with per-change 'why'."""
    return jr.build_risk_timeline(req)


def compare_routes(req: JourneyRequest):
    """§5.1 row 3 (v1 §8) — explicit trade-offs; never silent shortest path."""
    return jr.compare_routes(req)


def predict_route_risk(req: JourneyRequest):
    """§5.1 row 4 (v1 §9) — hedged language only."""
    return jr.predictive_risk(req)


def max_risk_of(timeline) -> str:
    level = "LOW"
    for t in timeline:
        r = t.risk.value if hasattr(t.risk, "value") else str(t.risk)
        if _RISK_ORDER.index(r) > _RISK_ORDER.index(level):
            level = r
    return level


def monitor_active_journey(store: EvidenceStore, *, origin: str,
                           destination: str,
                           departure_time: datetime | None,
                           priority: str = "balanced",
                           tolerance: str = "MODERATE",
                           user_id: str | None = None) -> dict:
    """§5.1 row 5 / §8 P3 — enrol a journey for live reassessment.

    Baseline risk is computed NOW; the Trust Layer's continual reassessment
    loop (§1.10) recomputes risk on new evidence and raises a RISK_ELEVATION
    or RISK_RESOLUTION notification when the level crosses the watcher's
    tolerance threshold. Tolerance shapes NOTIFICATIONS only — never the risk
    score itself (§3.4: personalization shapes presentation, not conclusions).
    """
    req = _req(origin, destination,
               departure_time or datetime.now(timezone.utc))
    timeline = build_risk_timeline(req)
    baseline = max_risk_of(timeline) if timeline else "LOW"
    import uuid
    watch_id = str(uuid.uuid4())
    store.add_watch(watch_id, origin, destination,
                    (departure_time or datetime.now(timezone.utc)).isoformat(),
                    baseline, priority=priority, tolerance=tolerance,
                    user_id=user_id)
    store.audit(actor="VOYAGER", action="enroll_journey_watch",
                decision="ALLOW",
                detail=f"{origin} → {destination} baseline={baseline}",
                policy_version="sovereign-policy/3.0.0")
    return {
        "watch_id": watch_id, "origin": origin, "destination": destination,
        "baseline_risk": baseline, "status": "MONITORING",
        "tolerance": tolerance,
        "note": ("Journey enrolled for live reassessment — you will be "
                 "alerted if risk crosses your notification threshold. "
                 "Thresholds shape alerts, never the risk score (§3.4)."),
    }


def reassess_watches(store: EvidenceStore) -> list[dict]:
    """§1.10 continual reassessment for every active watch.

    Returns a list of emitted notification summaries. Rule: compare recomputed
    risk to the stored CURRENT risk (drift of ≥1 level = notify); elevation
    past tolerance also flips watch status to ELEVATED so the Ops Node shows
    it immediately."""
    emitted: list[dict] = []
    for w in store.list_watches(active_only=True):
        try:
            dep = datetime.fromisoformat(w["departure_time"])
            if dep.tzinfo is None:
                dep = dep.replace(tzinfo=timezone.utc)
        except Exception:
            dep = datetime.now(timezone.utc)
        req = _req(w["origin"], w["destination"], dep,
                   priority=w.get("priority", "balanced"))
        timeline = build_risk_timeline(req)
        new = max_risk_of(timeline) if timeline else "LOW"
        old = w.get("current_risk") or w.get("baseline_risk") or "LOW"
        if new == old:
            continue
        store.update_watch(w["watch_id"], current_risk=new)
        delta = _RISK_ORDER.index(new) - _RISK_ORDER.index(old)
        tol = w.get("tolerance", "MODERATE")
        if delta > 0:
            kind, title = ("RISK_ELEVATION",
                           f"Risk elevated on {w['origin']} → {w['destination']}")
            if _RISK_ORDER.index(new) >= _RISK_ORDER.index(tol):
                store.update_watch(w["watch_id"], status="ELEVATED")
            body = (f"Monitored journey risk moved {old} → {new}. "
                    f"This appears driven by newly recorded evidence on the "
                    f"corridor — review the updated timeline before departure. "
                    f"(Hedged: patterns, not certainties — §9.)")
        else:
            kind, title = ("RISK_RESOLUTION",
                           f"Risk eased on {w['origin']} → {w['destination']}")
            store.update_watch(w["watch_id"], status="MONITORING")
            body = (f"Monitored journey risk moved {old} → {new} on the "
                    f"latest evidence refresh.")
        nid = store.notify(kind=kind, title=title, body=body,
                           ref=w["watch_id"])
        emitted.append({"notification_id": nid, "kind": kind,
                        "watch_id": w["watch_id"], "old": old, "new": new})
    return emitted
