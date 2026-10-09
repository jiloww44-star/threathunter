"""v4.6 — MEASUREMENT CLOSURE tests (§71 write-paths).

v4.5 reported five spec KPIs UNAVAILABLE because the write-paths did not
exist — honestly, with the gap named. v4.6 builds those write-paths:
review decisions (corrections), fact-check latency, reroute adjudication,
alert adjudication. These tests cover: the three decision routes (guards,
atomicity, RBAC, audit events, prior-verdict capture), latency persistence,
voyager's reroute-recommendation minting + auto-resolve, and the KPI flips
from UNAVAILABLE to measured — including window semantics.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import adjudication, kpis                       # noqa: E402
from app.core.adjudication import (adjudicate_alert,          # noqa: E402
                                   decide_reroute, decide_review)
from app.core.errors import PipelineError                     # noqa: E402
from app.store.db import get_store, reset_store              # noqa: E402

NOW = datetime.now(timezone.utc)


def _client(tmp_path, name="v46.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    reset_store(str(tmp_path / name))
    return TestClient(app)


def _store():
    return get_store()


def _seed_factcheck_review(store, outcome="VERIFIED"):
    """A factcheck run escalated to the human queue (§27)."""
    cid = store.record_check("factcheck", "claim under review", outcome,
                             "MEDIUM", {"verdict": outcome})
    rid = store.enqueue_review("factcheck", cid,
                               "confidence below publish threshold",
                               "MEDIUM", 5, "D1")
    return cid, rid


def _seed_watch(store, elevated=True):
    store.add_watch("watch-1", "Lagos", "Abuja",
                    (NOW + timedelta(hours=6)).isoformat(),
                    baseline_risk="LOW", priority="fastest",
                    tolerance="MODERATE")
    store.update_watch("watch-1", current_risk="HIGH")
    if elevated:
        store.update_watch("watch-1", status="ELEVATED", reroute_pending=1)
    return "watch-1"


def _seed_alert(store):
    return store.notify(kind="RISK_ELEVATION", title="Corridor risk rose",
                        body="evidence-driven", ref="watch-1")


# ------------------------------------------------------------ review decides
class TestReviewDecisions:
    def test_confirm_records_prior_verdict(self, tmp_path):
        _client(tmp_path)
        store = _store()
        cid, rid = _seed_factcheck_review(store)
        row = decide_review(store, rid, decision="CONFIRMED",
                            decided_by="analyst-1")
        assert row["status"] == "DECIDED" and row["decision"] == "CONFIRMED"
        assert row["prior_outcome"] == "VERIFIED"      # diff basis persisted
        assert row["decided_by"] == "analyst-1"

    def test_corrected_requires_written_outcome(self, tmp_path):
        _client(tmp_path)
        _, rid = _seed_factcheck_review(_store())
        with pytest.raises(PipelineError) as e:
            decide_review(_store(), rid, decision="CORRECTED",
                          decided_by="a")
        assert e.value.status == 422
        assert "writing" in e.value.detail

    def test_corrected_captures_both_sides(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _, rid = _seed_factcheck_review(store, outcome="VERIFIED")
        row = decide_review(store, rid, decision="CORRECTED",
                            decided_by="a", corrected_outcome="FALSE")
        assert row["prior_outcome"] == "VERIFIED"
        assert row["corrected_outcome"] == "FALSE"

    def test_double_decide_409_and_audited(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _, rid = _seed_factcheck_review(store)
        decide_review(store, rid, decision="CONFIRMED", decided_by="a")
        with pytest.raises(PipelineError) as e:
            decide_review(store, rid, decision="CORRECTED", decided_by="b",
                          corrected_outcome="FALSE")
        assert e.value.status == 409
        assert e.value.code == "REVIEW_ALREADY_DECIDED"

    def test_missing_404(self, tmp_path):
        _client(tmp_path)
        with pytest.raises(PipelineError) as e:
            decide_review(_store(), "nope", decision="CONFIRMED",
                          decided_by="a")
        assert e.value.status == 404

    def test_route_rbac_and_event(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        _, rid = _seed_factcheck_review(store)
        assert client.post(f"/api/v1/ops/review/{rid}/decide",
                           json={"decision": "CONFIRMED"},
                           headers={"X-TH360-Role": "viewer"}
                           ).status_code == 403
        r = client.post(f"/api/v1/ops/review/{rid}/decide",
                        json={"decision": "CORRECTED",
                              "corrected_outcome": "PARTIALLY TRUE"},
                        headers={"X-TH360-Role": "analyst"})
        assert r.status_code == 200
        events = [a["action"] for a in store.audit_trail(limit=20)]
        assert "event:ReviewDecided" in events


# ------------------------------------------------------------- latency (§71)
class TestFactcheckLatency:
    def test_full_pipeline_persists_measured_latency(self, tmp_path):
        client = _client(tmp_path)
        # engine only persists checks backed by evidence (no-evidence
        # UNVERIFIEDs return early by design) — seed the demo pack first
        import asyncio
        from app.scraper.orchestrator import load_sources, run_pipeline
        asyncio.run(run_pipeline(_store(), load_sources()))
        r = client.post("/api/v1/factcheck",
                        json={"claim": "Company X was sanctioned in "
                                       "August 2026"})
        assert r.status_code == 200
        rows = _store().kpi_sql(
            "SELECT latency_ms FROM checks WHERE module='factcheck' "
            "ORDER BY created_at DESC LIMIT 1")
        assert rows, "evidence-backed run must persist a check row"
        assert rows[0]["latency_ms"] is not None
        assert rows[0]["latency_ms"] >= 0.0
        fam = kpis.compute_kpis(_store())["families"]["fact_checker"]
        assert fam["latency"]["status"] == "OK"
        assert fam["latency"]["sample"] >= 1 and fam["latency"]["unit"] == "ms"


# --------------------------------------------------------------- reroutes
class TestReroutes:
    def test_accept_resolves_and_audits(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _seed_watch(store)
        row = decide_reroute(store, "watch-1", accept=True, decided_by="op")
        assert row["reroute_pending"] == 0
        assert row["reroute_outcome"] == "ACCEPTED"
        assert row["reroute_decided_at"]

    def test_not_pending_409(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _seed_watch(store, elevated=False)
        with pytest.raises(PipelineError) as e:
            decide_reroute(store, "watch-1", accept=False, decided_by="op")
        assert e.value.status == 409 and e.value.code == "REROUTE_NOT_PENDING"

    def test_route_and_pending_listing(self, tmp_path):
        client = _client(tmp_path)
        _seed_watch(_store())
        listing = client.get("/api/v1/ops/watches/reroutes").json()
        assert listing["pending"] == 1
        r = client.post("/api/v1/ops/watches/watch-1/reroute",
                        json={"decision": "DECLINE"})
        assert r.status_code == 200
        assert client.get("/api/v1/ops/watches/reroutes"
                          ).json()["pending"] == 0
        again = client.post("/api/v1/ops/watches/watch-1/reroute",
                            json={"decision": "ACCEPT"})
        assert again.status_code == 409

    def test_voyager_elevation_mints_pending_recommendation(self, tmp_path):
        """The machine side: elevation past tolerance IS the recommendation;
        easing risk AUTO_RESOLVEs it (neither accepted nor declined)."""
        _client(tmp_path)
        store = _store()
        _seed_watch(store, elevated=True)
        from app.core.adjudication import auto_resolve_reroute
        assert auto_resolve_reroute(store, "watch-1") is True
        row = store.get_watch("watch-1")
        assert row["reroute_outcome"] == "AUTO_RESOLVED"
        # auto-resolved is NOT a human decision — no double count, no re-fire
        assert auto_resolve_reroute(store, "watch-1") is False


# ----------------------------------------------------------------- alerts
class TestAlertAdjudication:
    def test_single_verdict_atomic(self, tmp_path):
        _client(tmp_path)
        store = _store()
        nid = _seed_alert(store)
        row = adjudicate_alert(store, nid, verdict="FALSE_POSITIVE",
                               decided_by="analyst")
        assert row["adjudication"] == "FALSE_POSITIVE"
        with pytest.raises(PipelineError) as e:
            adjudicate_alert(store, nid, verdict="TRUE_POSITIVE",
                             decided_by="analyst-2")
        assert e.value.status == 409 and e.value.code == (
            "ALERT_ALREADY_ADJUDICATED")

    def test_route_rbac_and_validation(self, tmp_path):
        client = _client(tmp_path)
        nid = _seed_alert(_store())
        assert client.post(f"/api/v1/ops/notifications/{nid}/adjudicate",
                           json={"verdict": "TRUE_POSITIVE"},
                           headers={"X-TH360-Role": "viewer"}
                           ).status_code == 403
        assert client.post(f"/api/v1/ops/notifications/{nid}/adjudicate",
                           json={"verdict": "MAYBE"}
                           ).status_code == 422
        r = client.post(f"/api/v1/ops/notifications/{nid}/adjudicate",
                        json={"verdict": "TRUE_POSITIVE"})
        assert r.status_code == 200
        events = [a["action"] for a in _store().audit_trail(limit=20)]
        assert "event:AlertAdjudicated" in events


# ------------------------------------------------------------------- KPIs
class TestKpiFlips:
    def test_correction_rates_measured_after_decisions(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _, r1 = _seed_factcheck_review(store, outcome="VERIFIED")
        _, r2 = _seed_factcheck_review(store, outcome="MIXED")
        decide_review(store, r1, decision="CONFIRMED", decided_by="a")
        decide_review(store, r2, decision="CORRECTED", decided_by="a",
                      corrected_outcome="FALSE")
        fams = kpis.compute_kpis(store)["families"]
        iq = fams["intelligence_quality"]
        assert iq["analyst_correction_rate"]["status"] == "OK"
        assert iq["analyst_correction_rate"]["value"] == 0.5
        assert iq["analyst_correction_rate"]["sample"] == 2
        fc = fams["fact_checker"]
        assert fc["correction_rate"]["value"] == 0.5
        assert fc["correction_rate"]["sample"] == 2  # module-scoped

    def test_reroute_acceptance_and_auto_resolve_denominator(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _seed_watch(store)
        decide_reroute(store, "watch-1", accept=True, decided_by="op")
        store.add_watch("watch-2", "Lagos", "Kano",
                        (NOW + timedelta(hours=9)).isoformat(),
                        baseline_risk="LOW", priority="safest")
        store.update_watch("watch-2", current_risk="MODERATE")
        store.update_watch("watch-2", status="ELEVATED", reroute_pending=1)
        from app.core.adjudication import auto_resolve_reroute
        auto_resolve_reroute(store, "watch-2")
        j = kpis.compute_kpis(store)["families"]["journey"]
        # 1 human accept out of 1 human decision; AUTO_RESOLVED excluded
        assert j["reroute_acceptance_rate"]["status"] == "OK"
        assert j["reroute_acceptance_rate"]["value"] == 1.0
        assert j["reroute_acceptance_rate"]["sample"] == 1

    def test_false_alarm_rate_measured(self, tmp_path):
        _client(tmp_path)
        store = _store()
        n1 = _seed_alert(store)
        n2 = _seed_alert(store)
        adjudicate_alert(store, n1, verdict="TRUE_POSITIVE", decided_by="a")
        adjudicate_alert(store, n2, verdict="FALSE_POSITIVE", decided_by="a")
        j = kpis.compute_kpis(store)["families"]["journey"]
        assert j["false_alarm_rate"]["status"] == "OK"
        assert j["false_alarm_rate"]["value"] == 0.5
        assert j["alerts_adjudicated"]["value"] == 2

    def test_window_semantics_on_decisions(self, tmp_path):
        _client(tmp_path)
        store = _store()
        _, rid = _seed_factcheck_review(store)
        decide_review(store, rid, decision="CORRECTED", decided_by="a",
                      corrected_outcome="FALSE")
        old = (NOW - timedelta(hours=500)).isoformat()
        with store._lock:
            store._conn.execute(
                "UPDATE review_queue SET decided_at=?", (old,))
            store._conn.commit()
        rate = kpis.compute_kpis(store, window_hours=24)[
            "families"]["intelligence_quality"]["analyst_correction_rate"]
        assert rate["status"] == "UNAVAILABLE"      # decided, but not in window
        rate_all = kpis.compute_kpis(store, window_hours=1000)[
            "families"]["intelligence_quality"]["analyst_correction_rate"]
        assert rate_all["value"] == 1.0

    def test_empty_store_still_honest(self, tmp_path):
        _client(tmp_path)
        fams = kpis.compute_kpis(_store())["families"]
        for fam, metric in (("intelligence_quality",
                             "analyst_correction_rate"),
                            ("journey", "reroute_acceptance_rate"),
                            ("journey", "false_alarm_rate"),
                            ("fact_checker", "correction_rate"),
                            ("fact_checker", "latency")):
            kv = fams[fam][metric]
            assert kv["status"] == "UNAVAILABLE" and kv["value"] is None
            assert "write-path" in kv["basis"] or "latency" in kv["basis"]
