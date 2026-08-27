"""Journey Advisor — spec Parts 1.6, 5 (module table), 6 (predictive model).

Consumers (per spec §5): weather feed, traffic feed, incident feeds, crime
patterns → risk timeline per route segment. Predictions stay hedged (§9) and
confidence scales with sample size, honestly (Part 6.3).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from ..config import SEED_ROOT
from ..models.schemas import (
    Confidence, JourneyPrediction, JourneyRequest, JourneyResponse,
    JourneySegmentRisk, RiskLevel, RouteOption,
)
from ..store.db import get_store
from . import nlp_lite
from ..services.geo import _haversine_km, get_geo
from ..services.routing import get_routing

_RISK_ORDER = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]


def _fuse(env: float, sec: float, mob: float) -> RiskLevel:
    """spec Part 5: level = fuse(env_risk, sec_risk, mob_risk) — LOW→HIGH."""
    score = max(env, sec) * 0.55 + mob * 0.25 + min(env, sec) * 0.20
    if score >= 0.75:
        return RiskLevel.CRITICAL
    if score >= 0.5:
        return RiskLevel.HIGH
    if score >= 0.25:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def _bucket_of_time(hour: int) -> str:
    """Aligned with incident-feed time_of_day semantics (night ≈ 20:00–05:00)."""
    if 0 <= hour < 5:
        return "night"
    if 5 <= hour < 7:
        return "early_morning"
    if 7 <= hour < 10:
        return "morning_peak"
    if 10 <= hour < 16:
        return "day"
    if 16 <= hour < 19:
        return "evening_peak"
    if 19 <= hour < 20:
        return "evening"
    return "night"  # 20:00–24:00


def _load_fixture(name: str, default):
    path = SEED_ROOT / "fixtures" / name
    if path.exists():
        return json.loads(path.read_text())
    return default


def _routes_for(origin: str, destination: str) -> list[dict]:
    routes = _load_fixture("routes.json", {"routes": []})["routes"]
    o, d = origin.lower(), destination.lower()
    for r in routes:
        ro, rd = r["origin"].lower(), r["destination"].lower()
        if (ro in o or o in ro) and (rd in d or d in rd):
            return r["options"]
    return routes[0]["options"] if routes else []


def _incident_records() -> list[dict]:
    """Incident feed with coordinates preserved (spatial join, spec §1.4)."""
    feats = _load_fixture("incidents.geojson", {"features": []})["features"]
    out = []
    for f in feats:
        lon, lat = f.get("geometry", {}).get("coordinates", [0, 0])
        out.append({**f.get("properties", {}), "lon": lon, "lat": lat})
    return out


def _incidents_near(coord: dict, radius_km: float = 5.0,
                    time_of_day: str | None = None) -> list[dict]:
    """Spatial query: incidents within radius of a segment midpoint, filtered
    to the relevant time-of-day bucket (day-vs-night semantics preserved)."""
    hits = []
    for inc in _incident_records():
        if _haversine_km(coord, inc) > radius_km:
            continue
        tod = inc.get("time_of_day", "any")
        if time_of_day and tod not in ("any", "", None) and tod != time_of_day:
            continue
        hits.append(inc)
    return hits


def _hedged_note(n_incidents: int, weather_flag: float, tod: str,
                 max_sev: str) -> str:
    """§9 — hedged language, never deterministic claims."""
    if n_incidents == 0 and weather_flag < 0.2:
        return "No current evidence of elevated risk beyond baseline."
    if max_sev in ("HIGH", "CRITICAL") or n_incidents >= 3:
        return "Risk appears elevated based on recent patterns in this corridor."
    if n_incidents >= 1 or weather_flag >= 0.35:
        return "A potential concern is emerging along this segment."
    return "Insufficient information for a confident assessment."


def _sev_to_num(sev: str) -> float:
    return {"LOW": 0.2, "MODERATE": 0.45, "HIGH": 0.7, "CRITICAL": 0.95,
            "NONE": 0.0}.get(sev, 0.0)


async def build_risk_timeline_live(req: JourneyRequest) -> tuple[
        list[JourneySegmentRisk], dict | None, dict | None]:
    """spec §1.4 — Nominatim geocode → OSRM route geometry → per-segment
    incident/weather fusion. Returns (timeline, geometry, route_summary).
    Falls back to fixture segments when services are unavailable (§20)."""
    geo, routing = get_geo(), get_routing()
    dep = req.departure_time or datetime.now(timezone.utc)
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)

    o = await geo.geocode(req.origin)
    d = await geo.geocode(req.destination)
    if not o or not d:
        return [], None, None
    route = await routing.route(o, d)
    if not route or not route["segments"]:
        return [], None, None

    weather = _load_fixture("weather_forecast.json", {"hourly": []})["hourly"]
    timeline: list[JourneySegmentRisk] = []
    for seg in route["segments"]:
        eta = dep + timedelta(minutes=seg["start_offset_min"])
        bucket = _bucket_of_time(eta.hour)
        hits = _incidents_near(seg["coord"], radius_km=5.0, time_of_day=bucket)
        wx = min(
            (w for w in weather if nlp_lite.parse_iso(w["time"]) is not None),
            key=lambda w: abs((nlp_lite.parse_iso(w["time"]) - eta).total_seconds()),
            default=None)
        env_risk = (wx or {}).get("risk_factor", 0.0)
        sev_order = ["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL"]
        max_sev = max((h.get("severity", "LOW") for h in hits),
                      key=sev_order.index, default="NONE")
        sec_risk = min(0.95, sum(_sev_to_num(h.get("severity", "LOW"))
                                 for h in hits) * 0.5)
        mob_risk = _load_fixture("traffic_profile.json",
                                 {"profiles": {}})["profiles"].get(
                                     "standard", {}).get(bucket, 0.1)
        level = _fuse(env_risk, sec_risk, mob_risk)
        why = (f"Security: {len(hits)} incident record(s) within 5 km "
               f"matching {bucket.replace('_', ' ')} window (max {max_sev}); "
               f"weather: {(wx or {}).get('condition', 'no adverse forecast')}; "
               f"{_hedged_note(len(hits), env_risk, bucket, max_sev)}")
        timeline.append(JourneySegmentRisk(
            time=eta.strftime("%H:%M"), segment=seg["segment"], risk=level,
            why=why, lat=seg["coord"]["lat"], lon=seg["coord"]["lon"],
            incident_count=len(hits), max_severity=max_sev))
    return timeline, route["geometry"], {
        "total_km": route["total_km"], "total_min": route["total_min"],
        "origin": o["display_name"], "destination": d["display_name"]}


def _incident_matches(incident: dict, segment: dict, eta: datetime) -> bool:
    """A historical incident applies to a segment if geography matches AND the
    time-of-day profile matches the ETA (day vs night — demo scenario 3)."""
    seg_name = segment["name"].lower()
    inc_seg = (incident.get("segment") or "").lower()
    geo_hit = (inc_seg in seg_name or seg_name in inc_seg
               or any(w in seg_name for w in inc_seg.split() if len(w) > 3))
    if not geo_hit:
        return False
    tod = incident.get("time_of_day", "any")
    if tod in ("any", None, ""):
        return True
    return tod == _bucket_of_time(eta.hour)


def build_risk_timeline(req: JourneyRequest) -> list[JourneySegmentRisk]:
    """spec Part 5 — env/security/mobility fusion with per-change 'why'."""
    incidents = _load_fixture("incidents.geojson", {"features": []})["features"]
    weather = _load_fixture("weather_forecast.json", {"hourly": []})["hourly"]
    traffic = _load_fixture("traffic_profile.json", {"profiles": {}})["profiles"]

    dep = req.departure_time or datetime.now(timezone.utc)
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)

    options = _routes_for(req.origin, req.destination)
    segments = options[0]["segments"] if options else []

    timeline: list[JourneySegmentRisk] = []
    elapsed = 0
    for seg in segments:
        eta = dep + timedelta(minutes=elapsed)
        elapsed += seg.get("avg_minutes", 45)

        # --- environment: weather at (segment, eta)
        wx = min(
            (w for w in weather if abs(
                (nlp_lite.parse_iso(w["time"]) - eta).total_seconds()) <= 5400),
            key=lambda w: abs((nlp_lite.parse_iso(w["time"]) - eta).total_seconds()),
            default=None,
        )
        env_risk = (wx or {}).get("risk_factor", 0.0)
        wx_desc = (wx or {}).get("condition", "no adverse forecast")

        # --- security: incidents near segment in trailing window, time-aware
        hits = [f["properties"] for f in incidents
                if _incident_matches(f.get("properties", {}), seg, eta)]
        sev_map = {"LOW": 0.2, "MODERATE": 0.45, "HIGH": 0.7, "CRITICAL": 0.95}
        sec_risk = min(0.95, sum(sev_map.get(h.get("severity", "LOW"), 0.2)
                                 for h in hits) * 0.5)

        # --- mobility: traffic bucket at eta
        bucket = _bucket_of_time(eta.hour)
        mob_risk = traffic.get(seg.get("traffic_profile", "standard"),
                               {}).get(bucket, 0.1)

        level = _fuse(env_risk, sec_risk, mob_risk)
        why = (
            f"Weather: {wx_desc}; security: "
            f"{len(hits)} relevant incident record(s) matching "
            f"{bucket.replace('_', ' ')} travel window; congestion profile "
            f"{mob_risk:.2f}."
        )
        sev_order = ["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL"]
        max_sev = max((h.get("severity", "LOW") for h in hits),
                      key=sev_order.index, default="NONE")
        coords = seg.get("coords") or [None, None]
        timeline.append(JourneySegmentRisk(
            time=eta.strftime("%H:%M"), segment=seg["name"], risk=level, why=why,
            lon=coords[0] if coords[0] else None,
            lat=coords[1] if coords[1] else None,
            incident_count=len(hits), max_severity=max_sev,
        ))
    return timeline


def compare_routes(req: JourneyRequest) -> list[RouteOption]:
    """spec Part 6.4/§8 — explicit trade-offs, sorted by priority."""
    options = _routes_for(req.origin, req.destination)
    incidents = _load_fixture("incidents.geojson", {"features": []})["features"]
    dep = req.departure_time or datetime.now(timezone.utc)
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)

    scored: list[RouteOption] = []
    for opt in options:
        elapsed = 0
        risk_sum, n_seg, high_km = 0.0, 0, 0.0
        for seg in opt["segments"]:
            eta = dep + timedelta(minutes=elapsed)
            elapsed += seg.get("avg_minutes", 45)
            hits = [f["properties"] for f in incidents
                    if _incident_matches(f.get("properties", {}), seg, eta)]
            sev_map = {"LOW": 0.2, "MODERATE": 0.45, "HIGH": 0.7, "CRITICAL": 0.95}
            seg_risk = min(0.95, sum(sev_map.get(h.get("severity", "LOW"), 0.2)
                                     for h in hits) * 0.5)
            risk_sum += seg_risk
            n_seg += 1
            if seg_risk >= 0.5:
                high_km += seg.get("km", 10)
        scored.append(RouteOption(
            route=opt["name"],
            safety_score=round(risk_sum / max(n_seg, 1), 3),
            travel_time_min=sum(s.get("avg_minutes", 45) for s in opt["segments"]),
            exposure_km_high_risk=round(high_km, 1),
            trade_off=opt.get("trade_off", "No specific trade-off recorded."),
        ))

    keys = {
        "safest": lambda x: x.safety_score,
        "fastest": lambda x: x.travel_time_min,
        "balanced": lambda x: x.travel_time_min * 0.5 + x.safety_score * 50,
        "lowest_exposure": lambda x: x.exposure_km_high_risk,
    }
    return sorted(scored, key=keys.get(req.priority, keys["balanced"]))


def _confidence_from_sample(n: int) -> Confidence:
    """spec Part 6.3 — confidence scales honestly with sample size (§1.9)."""
    if n >= 100:
        return Confidence.HIGH
    if n >= 30:
        return Confidence.MODERATE
    if n >= 10:
        return Confidence.LOW
    return Confidence.UNDETERMINED


def predictive_risk(req: JourneyRequest) -> list[JourneyPrediction]:
    """spec Part 6 — hedged predictions with factor breakdown + basis."""
    options = _routes_for(req.origin, req.destination)
    incidents = _load_fixture("incidents.geojson", {"features": []})["features"]
    weather = _load_fixture("weather_forecast.json", {"hourly": []})["hourly"]
    traffic = _load_fixture("traffic_profile.json", {"profiles": {}})["profiles"]
    dep = req.departure_time or datetime.now(timezone.utc)
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)

    segments = options[0]["segments"] if options else []
    all_incidents = [f["properties"] for f in incidents]

    preds: list[JourneyPrediction] = []
    elapsed = 0
    for seg in segments:
        eta = dep + timedelta(minutes=elapsed)
        elapsed += seg.get("avg_minutes", 45)

        seg_incidents = [p for p in all_incidents
                         if _incident_matches(p, seg, eta) or
                         (p.get("segment") or "").lower() in seg["name"].lower()]
        n_sample = len(seg_incidents)
        base_rate = n_sample / 90.0 if n_sample else 0.02  # incidents/day /90d

        dow_factor = 1.2 if eta.weekday() in (4, 5) else 1.0
        bucket = _bucket_of_time(eta.hour)
        hod_factor = {"night": 1.5, "evening": 1.25, "morning_peak": 1.15,
                      "evening_peak": 1.15}.get(bucket, 1.0)
        trend = 1.15 if n_sample and any(
            (nlp_lite.parse_iso(p.get("timestamp")) or eta)
            > eta - timedelta(days=7) for p in seg_incidents) else 1.0
        wx = min(
            (w for w in weather if abs(
                (nlp_lite.parse_iso(w["time"]) - eta).total_seconds()) <= 5400),
            key=lambda w: abs((nlp_lite.parse_iso(w["time"]) - eta).total_seconds()),
            default=None,
        )
        wx_factor = 1.0 + (wx or {}).get("risk_factor", 0.0) * 0.8

        predicted = base_rate * dow_factor * hod_factor * trend * wx_factor
        ratio = predicted / max(base_rate, 1e-6)

        # §9 — hedged language only, no false precision
        if ratio >= 2.0:
            level, language = (RiskLevel.HIGH,
                               "Risk appears elevated based on recent patterns.")
        elif ratio >= 1.3:
            level, language = (RiskLevel.MODERATE,
                               "A potential concern is emerging along this segment.")
        elif ratio <= 0.7 and n_sample:
            level, language = (RiskLevel.LOW,
                               "No current evidence of elevated risk beyond baseline.")
        else:
            level, language = (RiskLevel.MODERATE,
                               "Insufficient information for a confident assessment.")

        preds.append(JourneyPrediction(
            segment=seg["name"], predicted_risk=level, language=language,
            confidence=_confidence_from_sample(n_sample),
            basis=f"{n_sample} recorded event(s) over trailing 90 days",
            factors={"day_of_week": dow_factor, "time_of_day": hod_factor,
                     "recent_trend": trend, "weather": round(wx_factor, 2)},
        ))
    return preds


async def ai_narrative(req: JourneyRequest,
                       timeline: list[JourneySegmentRisk]) -> dict | None:
    """spec §3 (OpenRouter actions) — optional live narrative. Absent key →
    deterministic templates stand in (demo profile, §20)."""
    from ..llm.circuit_breaker import ai_action
    from ..core.errors import PipelineError
    digest = "; ".join(f"{t.time} {t.segment}={t.risk.value}" for t in timeline)
    prompt = (
        "Write exactly two short, hedged sentences summarizing this journey "
        "risk timeline. Never assert certainty; use words like 'appears', "
        "'patterns suggest'. Do not exceed 40 words.")
    try:
        out = await ai_action("journey", [
            {"role": "user",
             "content": f"Route: {req.origin} to {req.destination}. "
                        f"Timeline: {digest}\n\n{prompt}"}], max_tokens=120)
        return {"text": out["text"], "model_used": out["model_used"],
                "mode": out["mode"]}
    except PipelineError:
        return None


def derive_confidence(timeline: list[JourneySegmentRisk]) -> Confidence:
    high = sum(1 for t in timeline if t.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL))
    if len(timeline) >= 4:
        return Confidence.HIGH if high else Confidence.MODERATE
    if len(timeline) >= 2:
        return Confidence.MODERATE
    return Confidence.LOW


async def assess_journey(req: JourneyRequest) -> JourneyResponse:
    """spec Part 1.6 — conversational clarification, then fused assessment."""
    trace: list[str] = []
    if not req.origin or not req.destination:
        return JourneyResponse(
            status="CLARIFICATION_NEEDED", answer="",
            confidence=Confidence.UNDETERMINED,
            question="Where are you departing from, and where are you going?",
            missing_fields=[f for f, v in (("origin", req.origin),
                                           ("destination", req.destination))
                            if not v],
            context_retained={"origin": req.origin, "destination": req.destination},
        )
    if req.departure_time is None:
        # §14-15 — ask ONLY for materially important info; keep context
        return JourneyResponse(
            status="CLARIFICATION_NEEDED",
            answer=f"Route registered: {req.origin} → {req.destination}.",
            confidence=Confidence.UNDETERMINED,
            question="What time do you expect to leave?",
            missing_fields=["departure_time"],
            context_retained={"origin": req.origin,
                              "destination": req.destination},
        )

    trace.append(f"Route resolved: {req.origin} → {req.destination}, "
                 f"departure {req.departure_time.isoformat()}, "
                 f"priority={req.priority}")
    # spec §1.4 — live OSM stack preferred; honest fixture fallback (§20)
    timeline, geometry, route_summary = await build_risk_timeline_live(req)
    data_mode = "live" if timeline else "offline-fixture"
    if not timeline:
        timeline = build_risk_timeline(req)
        trace.append("OSM stack unavailable — degraded to fixture corridor "
                     "(SOURCE_UNAVAILABLE surfaced in data_mode marker)")
    else:
        trace.append(f"Live route: {route_summary['total_km']} km / "
                     f"{route_summary['total_min']} min via OSRM road geometry, "
                     f"geocoded via Nominatim")
    trace.append(f"Risk timeline: {len(timeline)} segments fused from weather, "
                 f"incident history and traffic profiles")
    routes = compare_routes(req)
    trace.append(f"Route options compared: {len(routes)} alternative(s) ranked "
                 f"by '{req.priority}' with explicit trade-offs")
    preds = predictive_risk(req)
    trace.append(f"Predictive model (hedged §9): {len(preds)} segment forecast(s)")
    narrative = await ai_narrative(req, timeline)
    if narrative:
        trace.append(f"AI narrative via OpenRouter {narrative['model_used']} "
                     f"(mode {narrative['mode']})")
    confidence = derive_confidence(timeline)
    trace.append(f"Overall journey confidence: {confidence.value}")

    max_risk = max((t.risk for t in timeline),
                   key=lambda r: _RISK_ORDER.index(r), default=RiskLevel.LOW)
    answer = {
        RiskLevel.LOW: "Your journey looks routinely safe across all segments.",
        RiskLevel.MODERATE: "Your journey is mostly routine — one or more "
                            "segments need ordinary caution.",
        RiskLevel.HIGH: "Elevated risk detected on part of your journey — "
                        "see the timeline and consider the safer alternative.",
        RiskLevel.CRITICAL: "Severe risk on this journey — strongly consider "
                            "postponing or taking the alternative route below.",
    }[max_risk]

    resp = JourneyResponse(
        status="COMPLETE", answer=answer, confidence=confidence,
        risk_timeline=timeline, route_options=routes, prediction=preds,
        data_mode=data_mode, route_geometry=geometry,
        route_summary=route_summary, ai_narrative=narrative,
        interpretation=("INFERENCE: Segment risks are fused estimates from "
                        "incident history, weather and congestion patterns — "
                        "they describe tendencies, not certainties."),
        recommended_action=(
            "Review the highlighted segments; consider departing at the "
            "recommended window or taking the safer route option."
            if max_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            else "Standard precautions apply. Download the offline brief "
                 "before departure."),
        what_would_change_conclusion=(
            "A change in departure time (day vs night travel materially "
            "changes the security profile), new incidents on route, or a "
            "forecast update."),
        reasoning_trace=trace,
        sources_independent=3, sources_total=3,  # weather + incidents + traffic
    )
    check_id = get_store().record_check(
        module="journey",
        subject=f"{req.origin} → {req.destination} @ "
                f"{req.departure_time.strftime('%H:%M')}",
        outcome=max_risk.value, confidence=confidence.value,
        response=resp.model_dump(mode="json"),
    )
    # Part 18 D1 — journey advisories are a HIGH-blast-radius surface
    # (physical safety): high-confidence verdicts stay human-gated;
    # low-confidence ones hit the uncertainty firewall. Routing disclosed.
    from .review_routing import route_review, stakes_for_module
    route = route_review(
        confidence=confidence, contradictions=[],
        sources_independent=3, sources_total=3,
        stakes=stakes_for_module("journey"), module="journey")
    trace.append(f"Review routing (Part 18 D1): {route.tier} — {route.reason}")
    resp.review_route = route.tier
    if route.enqueued:
        get_store().enqueue_review(
            module="journey", case_ref=check_id, reason=route.reason,
            risk=route.risk, priority=route.priority, tier=route.tier)
    return resp
