"""v4.3 — CONTINUOUS ASSURANCE tests (§73 V2.5).

Covers: the assurance sweep (channels, posture rules, persistence, failure
guards), native §26 event naming (RiskRecalculated / JourneyConditionChanged
from reassess_all; AlertTriggered from store.notify), the shared health
mapping, and staleness SLA transitions.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import assurance, privacy                            # noqa: E402
from app.core.health import health_state                           # noqa: E402


def _client(tmp_path, name="v43.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.store.db import reset_store
    reset_store(str(tmp_path / name))
    return TestClient(app)


# -------------------------------------------------- notify → AlertTriggered -
class TestAlertTriggered:
    def test_notify_mints_alert_event(self, store):
        store.notify(kind="VERDICT_CHANGE", title="Verdict updated", body="x")
        rows = [a for a in store.audit_trail(limit=10)
                if a["action"] == "event:AlertTriggered"]
        assert len(rows) == 1
        assert rows[0]["policy_version"] == "platform-events/4.3.0"
        assert "VERDICT_CHANGE" in rows[0]["detail"]

    def test_notification_still_returned(self, store):
        nid = store.notify(kind="GOVERNANCE", title="t", body="b")
        notes = store.list_notifications(limit=5)
        assert any(n["id"] == nid and n["kind"] == "GOVERNANCE"
                   for n in notes)


# ------------------------------------------------- native §26 reassessment --
class TestReassessEventNames:
    def test_verdict_movement_names_risk_recalculated(self, store, seeded):
        """A verdict movement is named RiskRecalculated by reassess_all —
        the single emission site for every reassessment caller."""
        import asyncio
        import app.core.trust_layer as tl

        async def fake_checks(s):
            return [{"notification_id": "n1", "check_id": "case-0001",
                     "old": "UNVERIFIED", "new": "MOSTLY_TRUE"}]
        real = tl.reassess_open_checks
        tl.reassess_open_checks = fake_checks
        try:
            out = asyncio.run(tl.reassess_all(seeded))
        finally:
            tl.reassess_open_checks = real
        assert out["emitted"] >= 1
        rows = [a for a in seeded.audit_trail(limit=50)
                if a["action"] == "event:RiskRecalculated"]
        assert rows and rows[0]["policy_version"] == "trust-layer/1.10.0"
        assert "UNVERIFIED" in rows[0]["detail"]

    def test_watch_movement_names_journey_condition_changed(self, store):
        import asyncio
        from app.core import trust_layer as tl
        from app.swarm.agents import voyager
        real = voyager.reassess_watches
        voyager.reassess_watches = (
            lambda s: [{"watch_id": "w-1", "old": "LOW", "new": "HIGH",
                        "origin": "Lagos", "destination": "Abuja"}])
        try:
            asyncio.run(tl.reassess_all(store))
        finally:
            voyager.reassess_watches = real
        rows = [a for a in store.audit_trail(limit=50)
                if a["action"] == "event:JourneyConditionChanged"]
        assert rows and "w-1" in rows[0]["detail"]


# ------------------------------------------------------------ posture rules -
class TestPosture:
    def test_ok_on_green_seeded_store(self, seeded):
        posture, reasons = assurance._posture(
            seeded, {"degraded_or_worse": []})
        assert posture == "OK" and reasons == ["all posture checks green"]

    def test_critical_on_broken_consent_chain(self, seeded):
        # write real ledger entries, then tamper one — the verifier must
        # catch the break (§5.3) and posture must go CRITICAL.
        privacy.record(seeded, user_id="u1", purpose="personalization",
                       state="granted")
        privacy.record(seeded, user_id="u1", purpose="personalization",
                       state="withdrawn")
        assert privacy.verify_chain(seeded)["chain_intact"] is True
        with seeded._lock:
            seeded._conn.execute(
                "UPDATE consent_ledger SET entry_hash='tampered' "
                "WHERE rowid = (SELECT MIN(rowid) FROM consent_ledger)")
            seeded._conn.commit()
        assert privacy.verify_chain(seeded)["chain_intact"] is False
        posture, reasons = assurance._posture(
            seeded, {"degraded_or_worse": []})
        assert posture == "CRITICAL"
        assert any("consent ledger" in r for r in reasons)

    def test_attention_on_degraded_source(self, seeded):
        posture, reasons = assurance._posture(
            seeded, {"degraded_or_worse": ["demo_wire_a"]})
        assert posture == "ATTENTION"
        assert any("demo_wire_a" in r for r in reasons)

    def test_attention_on_pending_approval(self, seeded):
        from app.core import approvals
        approvals.request(seeded, kind="patch_apply", subject_ref="CVE-1",
                          summary="p", requester="t")
        posture, _ = assurance._posture(seeded, {"degraded_or_worse": []})
        assert posture == "ATTENTION"

    def test_critical_on_sev1(self, seeded):
        seeded.declare_incident("inc-1", "SEV1", "breach", "op",
                                delivery={"attempted": False})
        posture, _ = assurance._posture(seeded, {"degraded_or_worse": []})
        assert posture == "CRITICAL"
        seeded.resolve_incident("inc-1")

    def test_posture_heals_after_incident_resolves(self, seeded):
        seeded.declare_incident("inc-2", "SEV1", "breach", "op",
                                delivery={"attempted": False})
        assert assurance._posture(
            seeded, {"degraded_or_worse": []})[0] == "CRITICAL"
        seeded.resolve_incident("inc-2")
        posture, reasons = assurance._posture(
            seeded, {"degraded_or_worse": []})
        assert posture == "OK"
        assert reasons == ["all posture checks green"]


# ------------------------------------------------------------- the sweep ----
class TestSweep:
    def test_sweep_persists_and_reports(self, store):
        import asyncio
        summary = asyncio.run(assurance.run_assurance_sweep(store))
        assert summary["posture"] in ("OK", "ATTENTION", "CRITICAL")
        assert summary["engine_version"].startswith("assurance-engine/")
        latest = store.assurance_latest()
        assert latest and latest["summary"]["posture"] == summary["posture"]

    def test_stale_source_flips_to_degraded(self, store):
        store.upsert_source_meta({"id": "old_feed", "reliability": "HIGH",
                                  "authority": "SECONDARY"}, ok=True,
                                 at=(datetime.now(timezone.utc)
                                     - timedelta(days=3)).isoformat())
        sweep = assurance._source_sweep(store, actor="t")
        assert sweep["source_states"]["old_feed"] == "DEGRADED"
        assert any("old_feed" in s for s in sweep["stale_sources"])
        assert any(a["action"] == "event:SourceHealthChanged"
                   for a in store.audit_trail(limit=50))

    def test_second_sweep_detects_state_transition(self, store):
        import asyncio
        store.upsert_source_meta({"id": "live_feed", "reliability": "HIGH",
                                  "authority": "SECONDARY"}, ok=True)
        asyncio.run(assurance.run_assurance_sweep(store))
        # degrade the same source between sweeps → transition event
        store.upsert_source_meta({"id": "live_feed", "reliability": "HIGH",
                                  "authority": "SECONDARY"}, ok=False,
                                 error="HTTP 500s for a week")
        store.update_source_health("live_feed", 0.5, "repeated fetch "
                                   "failures over window")
        before = len(store.audit_trail(limit=200))
        summary = asyncio.run(assurance.run_assurance_sweep(store))
        assert summary["source_states"]["live_feed"] == "DEGRADED"
        rows = [a for a in store.audit_trail(limit=200)
                if a["action"] == "event:SourceHealthChanged"]
        assert len(store.audit_trail(limit=200)) >= before
        assert any("live_feed" in r["detail"] and "ACTIVE" in r["detail"]
                   for r in rows)
        assert any(t["source_id"] == "live_feed"
                   for t in summary["source_transitions"])

    def test_reassessment_failure_degrades_block_not_posture(self, store):
        """§20: a broken channel degrades its block; posture math intact."""
        import asyncio
        from app.core import trust_layer
        real = trust_layer.reassess_all

        async def boom(s):
            raise RuntimeError("engine down")
        trust_layer.reassess_all = boom
        try:
            summary = asyncio.run(assurance.run_assurance_sweep(store))
        finally:
            trust_layer.reassess_all = real
        assert summary["reassessment_degraded"].startswith(
            "reassessment loop failed")
        assert summary["posture"] in ("OK", "ATTENTION", "CRITICAL")


# --------------------------------------------------------------- routes -----
class TestAssuranceRoutes:
    def test_sweep_and_status_roundtrip(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/ops/assurance/sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["posture"] in ("OK", "ATTENTION", "CRITICAL")
        st = client.get("/api/v1/ops/assurance/status").json()
        assert st["latest"]["posture"] == body["posture"]
        assert len(st["series"]) == 1
        assert st["note"]

    def test_status_empty_store_honest(self, tmp_path):
        client = _client(tmp_path)
        st = client.get("/api/v1/ops/assurance/status").json()
        assert st["latest"] is None
        assert st["series"] == []


# ----------------------------------------------------- shared health map ----
class TestSharedHealthMap:
    def test_routes_and_core_agree(self):
        from app.api.routes.feed import _health_state as route_map
        meta = {"health_note": "", "health_score": 0.5}
        assert route_map(meta) == health_state(meta) == "DEGRADED"

    def test_boundary_scores(self):
        assert health_state({"health_score": 0.399, "health_note": ""}
                            ) == "UNAVAILABLE"
        assert health_state({"health_score": 0.4, "health_note": ""}
                            ) == "DEGRADED"
        assert health_state({"health_score": 0.7, "health_note": ""}
                            ) == "ACTIVE"
