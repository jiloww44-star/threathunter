"""Journey Advisor tests — spec Parts 5·6·7·9, demo scenario 3 (Part 10.6)."""
import asyncio
import random
from datetime import datetime, timezone

from app.core.journey import (JourneyRequest, assess_journey, build_risk_timeline,
                              compare_routes, predictive_risk)
from app.models.schemas import RiskLevel


def req(dep):
    return JourneyRequest(origin="Lagos", destination="Ibadan", departure_time=dep)


def run(coro):
    return asyncio.run(coro)


def night_req():
    return req(datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc))


def day_req():
    return req(datetime(2026, 8, 24, 7, 0, tzinfo=timezone.utc))


def _seg(timeline, name):
    return next(t for t in timeline if "km 42" in t.segment)


def test_night_route_elevated_at_km42():
    t = build_risk_timeline(night_req())
    assert _seg(t, "km 42").risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_day_route_lower_at_km42():
    day = _seg(build_risk_timeline(day_req()), "km 42").risk
    night = _seg(build_risk_timeline(night_req()), "km 42").risk
    order = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]
    assert order.index(day) < order.index(night)


def test_every_segment_explains_why():
    """§7 — every risk level change is explained."""
    t = build_risk_timeline(day_req())
    assert len(t) >= 4
    for seg in t:
        assert seg.why and "security:" in seg.why and "eather" in seg.why


def test_route_comparison_tradeoffs_explicit():
    """§8 — never silently recommend shortest: trade-offs surfaced."""
    opts = compare_routes(req(datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)))
    assert len(opts) == 2
    assert all(o.trade_off for o in opts)
    fastest = min(opts, key=lambda o: o.travel_time_min)
    assert any(f"{o.travel_time_min}" != f"{fastest.travel_time_min}" for o in opts)


def test_safest_priority_respects_safety():
    opts = compare_routes(JourneyRequest(
        origin="Lagos", destination="Ibadan",
        departure_time=datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc),
        priority="safest"))
    assert opts[0].safety_score <= opts[-1].safety_score


def test_predictions_use_hedged_language():
    """§9 / Part 8.3 — predictions never assert certainty."""
    hedges = ("appears", "potential", "emerging", "insufficient", "no current")
    preds = predictive_risk(day_req())
    assert preds
    for p in preds:
        assert any(h in p.language.lower() for h in hedges)
        assert p.predicted_risk in list(RiskLevel)
        assert p.basis.endswith("over trailing 90 days")


def test_clarification_asks_only_missing_fields():
    """§14-15 — flow asks only materially-missing fields, keeps context."""
    r = run(assess_journey(JourneyRequest(origin="Lagos", destination="Ibadan")))
    assert r.status == "CLARIFICATION_NEEDED"
    assert r.missing_fields == ["departure_time"]
    assert r.context_retained["origin"] == "Lagos"
    assert "time" in (r.question or "").lower()


def test_complete_assessment_shape():
    r = run(assess_journey(night_req()))
    assert r.status == "COMPLETE"
    assert r.risk_timeline and r.route_options and r.prediction
    assert r.interpretation.startswith("INFERENCE:")
