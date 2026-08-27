"""v3.3 — SOVEREIGN OPS NODE (blueprint v5.2) tests.

Covers: id_audit_l1 (§5), identity-intel RGD fan-out (§7), Compliance Index
(§6.C), Sovereign Data Stream (§3.B), and that the v3.2 ethics gate still
intercepts sensitive identity goals BEFORE any fan-out.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.swarm import pathfinder, registry                     # noqa: E402
from app.swarm.agents import voyager                           # noqa: E402
from app.core import compliance, privacy                       # noqa: E402
from app.store.db import reset_store                           # noqa: E402


# ---------------------------------------------------------------- §5 L1 ----
class TestIdAuditL1:
    def test_risky_domain_reviews(self):
        r = voyager.id_audit_l1("acme-parcels.xyz")
        assert r["verdict"] in ("REVIEW", "FAIL")
        assert r["risk_points"] > 0
        assert any("TLD" in s for s in r["checks"][0]["signals"])

    def test_structure_and_honesty(self):
        r = voyager.id_audit_l1("support@gtbank.com")
        for key in ("identity", "identifier_type", "level", "verdict",
                    "checks", "provenance", "hedge", "disclaimer"):
            assert key in r, key
        assert r["level"] == "L1"
        assert r["identifier_type"] == "email"
        assert "AI-generated" in r["disclaimer"]
        assert r["verdict"] in ("PASS", "REVIEW", "FAIL")

    def test_phone_path(self, monkeypatch):
        monkeypatch.setattr(voyager, "check_sim_swap",
                            lambda p: {"status": "SWAP_SUSPECTED",
                                       "notes": "recent port event"})
        r = voyager.id_audit_l1("+2348012345678")
        assert r["identifier_type"] == "phone"
        assert r["verdict"] in ("REVIEW", "FAIL")
        kinds = {c["check"] for c in r["checks"]}
        assert "carrier_integrity" in kinds

    def test_no_silent_success(self):
        """Unknown carrier status must never masquerade as PASS (§20)."""
        r = voyager.id_audit_l1("+2348099999999")
        carrier = [c for c in r["checks"] if c["check"] == "carrier_integrity"]
        if carrier and carrier[0]["detail"]["status"] != "OK":
            assert carrier[0]["verdict"] == "REVIEW"


# ------------------------------------------------- A-14 governance ---------
class TestGovernance:
    def test_voyager_allowlist_includes_l1(self):
        assert registry.NATIVE_AGENTS["VOYAGER"].allows("id_audit_l1")

    def test_hunter_cannot_dispatch_l1(self, store):
        with pytest.raises(registry.GovernanceError):
            registry.check_dispatch(store, "HUNTER", "id_audit_l1")


# ----------------------------------------------------------------- §7 RGD --
class TestIdentityIntelDecomposition:
    GOAL = "Verify identity of acme-vendor.ng and check for data leaks"

    def test_fan_out_shape(self):
        tasks = pathfinder.decompose(self.GOAL)
        pairs = {(t["agent"], t["function"]) for t in tasks}
        assert ("HUNTER", "footprint_scan") in pairs
        assert ("VOYAGER", "id_audit_l1") in pairs
        assert ("AUDITOR", "mask_pii") in pairs
        assert ("AUDITOR", "compliance_overlay") in pairs

    def test_nested_under_hunter(self):
        tasks = pathfinder.decompose(self.GOAL)
        by_fn = {t["function"]: t for t in tasks}
        l1 = by_fn["id_audit_l1"]
        assert l1["parent_id"] == by_fn["footprint_scan"]["task_id"]
        under_l1 = [t for t in tasks if t["function"] == "mask_pii"
                    and t["parent_id"] == l1["task_id"]]
        assert under_l1, "mask step must nest under the L1 audit"

    def test_ethics_gate_still_first(self):
        """v3.2 invariant: a doxxing-flavoured goal must refuse before any
        identity-intel fan-out happens."""
        tasks = pathfinder.decompose(
            "Find home address of Ada Obi who lives in Surulere and check "
            "for data leaks")
        assert len(tasks) == 1
        assert tasks[0]["agent"] == "AUDITOR"
        assert tasks[0]["params"].get("ethics_flag") is not None

    def test_journey_goal_not_hijacked(self):
        tasks = pathfinder.decompose(
            "Check the route from Ikeja to Lekki for exposed flood sections")
        fns = {t["function"] for t in tasks}
        assert "id_audit_l1" not in fns


# ------------------------------------------------------- §6.C Compliance ---
class TestComplianceIndex:
    def test_empty_store_bounds(self, store):
        idx = compliance.compute_index(store)
        assert 0 <= idx["index"] <= 100
        assert idx["grade"] in ("A", "B", "C", "REVIEW")
        assert len(idx["components"]) == 4
        assert idx["index"] == sum(c["score"] for c in idx["components"])
        assert "not an audit certification" in idx["indicator_notice"]

    def test_consent_component_reacts(self, store):
        before = compliance.compute_index(store)
        privacy.record(store, user_id="op-1", purpose="personalization",
                       state="granted")
        after = compliance.compute_index(store)
        b = next(c for c in before["components"]
                 if c["key"] == "consent_integrity")
        a = next(c for c in after["components"]
                 if c["key"] == "consent_integrity")
        assert a["score"] >= b["score"]

    def test_masking_component_reflects_intel_trees(self, store):
        base = compliance.compute_index(store)
        pii = next(c for c in base["components"] if c["key"] == "pii_defense")
        assert pii["score"] == 20 and "untested" in pii["note"]


# ------------------------------------------------------- §3.B Data Stream --
class TestSovereignStream:
    def _client(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "stream.db"))
        return TestClient(app)

    def test_stream_blends_persisted_and_live(self, tmp_path):
        client = self._client(tmp_path)
        r = client.get("/api/v1/ops/stream")
        assert r.status_code == 200
        body = r.json()
        kinds = {e["kind"] for e in body["events"]}
        assert "heartbeat" in kinds
        hb = next(e for e in body["events"] if e["kind"] == "heartbeat")
        assert hb["persistence"] == "live"
        assert "volatile" in hb["detail"]
        assert "audit trail" in body["note"]

    def test_audit_rows_appear_after_activity(self, tmp_path):
        client = self._client(tmp_path)
        client.post("/api/v1/privacy/id-audit",
                    json={"identity": "acme-parcels.xyz"})
        body = client.get("/api/v1/ops/stream").json()
        audits = [e for e in body["events"] if e["kind"] == "audit"]
        assert any("id_audit_l1" in e["text"] for e in audits)
        assert all(e["persistence"] == "persisted" for e in audits)


# ------------------------------------------------------------- API routes --
class TestRoutes:
    def test_id_audit_route(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "r1.db"))
        client = TestClient(app)
        r = client.post("/api/v1/privacy/id-audit",
                        json={"identity": "acme-parcels.xyz"})
        assert r.status_code == 200
        assert r.json()["verdict"] in ("REVIEW", "FAIL")

    def test_compliance_index_route(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "r2.db"))
        client = TestClient(app)
        r = client.get("/api/v1/privacy/compliance-index")
        assert r.status_code == 200
        assert "index" in r.json() and "components" in r.json()
