"""v4.0 — INTELLIGENCE CORE tests.

Covers the Investigation primary object (§2), the §63 authorization gate
(§35: LLM proposes, policy disposes; §76: no consequential action without
authorization), §26 events on the single audit store, the §70 epistemic
separation in UnifiedReports, the §49-51 Coverage axis beside Confidence,
and the §6/§32 Source Health Monitor states.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import investigation                                   # noqa: E402
from app.core.errors import PipelineError                            # noqa: E402
from app.core.reasoning_engine import _coverage_assessment           # noqa: E402
from app.api.routes.feed import _health_state, SOURCE_HEALTH_STATES  # noqa: E402
from app.swarm import pathfinder                                     # noqa: E402
from app.store.db import reset_store                                 # noqa: E402


def make_inv(store, **kw):
    kw.setdefault("objective", "Assess domain exposure")
    kw.setdefault("subject_type", "domain")
    kw.setdefault("subject", "example.ng")
    kw.setdefault("purpose", "organization-owned monitoring")
    kw.setdefault("authority", "organization_owned")
    kw.setdefault("scope", "passive OSINT only")
    kw.setdefault("allowed_sources", None)
    kw.setdefault("expires_days", 30)
    kw.setdefault("user_id", "demo")
    return investigation.create(store, **kw)


# ------------------------------------------------------------ §2 object ----
class TestInvestigationObject:
    def test_create_open_with_authorization_fields(self, store):
        inv = make_inv(store)
        assert inv["status"] == "OPEN"
        assert inv["authority"] == "organization_owned"
        assert inv["expires_at"]  # §63 expiry is always set
        assert inv["allowed_sources"] == []
        exp = datetime.fromisoformat(inv["expires_at"])
        assert exp > datetime.now(timezone.utc)

    def test_invalid_authority_rejected(self, store):
        with pytest.raises(PipelineError) as e:
            make_inv(store, authority="warrantless")
        assert e.value.status == 400

    def test_invalid_subject_type_rejected(self, store):
        with pytest.raises(PipelineError) as e:
            make_inv(store, subject_type="galaxy")
        assert e.value.status == 400

    def test_expiry_clamped_to_90_days(self, store):
        inv = make_inv(store, expires_days=365)
        exp = datetime.fromisoformat(inv["expires_at"])
        assert exp <= (datetime.now(timezone.utc)
                       + timedelta(days=91))

    def test_events_on_single_audit_store(self, store):
        inv = make_inv(store)
        investigation.close(store, inv["id"], actor="analyst")
        actions = [a["action"] for a in store.audit_trail(limit=50)]
        assert "event:InvestigationCreated" in actions
        assert "event:InvestigationClosed" in actions
        row = next(a for a in store.audit_trail(limit=50)
                   if a["action"] == "event:InvestigationCreated")
        assert row["policy_version"] == "intel-core/4.0.0"

    def test_list_scoped_per_user(self, store):
        make_inv(store, user_id="alice")
        make_inv(store, user_id="bob")
        assert len(store.inv_list(user_id="alice")) == 1
        assert len(store.inv_list()) == 2


# ---------------------------------------------------- §35/§76 gate ---------
class TestAuthorizationGate:
    def test_expired_refused_and_evented(self, store):
        inv = make_inv(store, expires_days=1)
        # age the row past expiry (deterministic, no clock mocking)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with store._lock:
            store._conn.execute(
                "UPDATE investigations SET expires_at=? WHERE id=?",
                (past, inv["id"]))
            store._conn.commit()
        with pytest.raises(PipelineError) as e:
            investigation.authorize_run(store, inv["id"],
                                        branches=["journey"],
                                        user_id="u")
        assert e.value.code == "ACTION_DENIED"
        assert e.value.status == 403
        assert "§76" in e.value.detail
        assert any("AuthorizationExpired" in a["action"]
                   for a in store.audit_trail(limit=50))

    def test_closed_refused(self, store):
        inv = make_inv(store)
        investigation.close(store, inv["id"], actor="analyst")
        with pytest.raises(PipelineError) as e:
            investigation.authorize_run(store, inv["id"],
                                        branches=["intel"], user_id="u")
        assert e.value.status == 403
        assert "§76" in e.value.detail

    def test_unknown_investigation_404(self, store):
        with pytest.raises(PipelineError) as e:
            investigation.authorize_run(store, "nope-404",
                                        branches=["intel"], user_id="u")
        assert e.value.code == "TREE_NOT_FOUND"
        assert e.value.status == 404

    def test_allowlist_denies_out_of_scope_branch(self, store):
        inv = make_inv(store, allowed_sources=["osint_databases", "rdap"])
        with pytest.raises(PipelineError) as e:
            investigation.authorize_run(store, inv["id"],
                                        branches=["journey"], user_id="u")
        assert e.value.code == "ACTION_DENIED"
        assert "§35" in e.value.detail      # LLM proposes, policy disposes
        assert "routes" in e.value.detail    # the denied family is named
        assert any("AuthorizationDenied" in a["action"]
                   for a in store.audit_trail(limit=50))

    def test_allowlist_admits_in_scope_branch(self, store):
        inv = make_inv(store, allowed_sources=["routes", "weather", "traffic",
                                               "incidents", "osm"])
        row = investigation.authorize_run(store, inv["id"],
                                          branches=["journey"], user_id="u")
        assert row["id"] == inv["id"]

    def test_open_tier_admits_any_branch(self, store):
        inv = make_inv(store)  # allowed_sources = [] → open public tier
        investigation.authorize_run(store, inv["id"],
                                    branches=["journey", "claim"],
                                    user_id="u")


# --------------------------------------------- pathfinder binding (§2) -----
class TestPathfinderBinding:
    def test_plan_denied_before_tree_exists(self, store):
        inv = make_inv(store, allowed_sources=["osint_databases", "rdap"])
        with pytest.raises(PipelineError):
            pathfinder.propose_plan(
                "plan travel from Lagos to Abuja", store,
                investigation_id=inv["id"])
        # §76: NO tree may exist for the refused plan
        assert store.list_trees() == []

    def test_plan_links_tree_to_investigation(self, store):
        inv = make_inv(store, allowed_sources=["routes", "weather", "traffic",
                                               "incidents", "osm"])
        plan = pathfinder.propose_plan(
            "plan travel from Lagos to Abuja", store,
            investigation_id=inv["id"])
        assert plan["investigation_id"] == inv["id"]
        links = store.inv_get(inv["id"])["links"]
        assert links == [links[0]]  # exactly one
        assert links[0]["kind"] == "ops_tree"
        assert links[0]["ref_id"] == plan["tree_id"]


# ------------------------------------------------------ §70 epistemic ------
class TestEpistemicSeparation:
    def test_unified_report_separates_layers(self, store):
        tasks = pathfinder.decompose("plan travel from Lagos to Abuja")
        results = {}  # no branch ran — honest empty layers
        report = pathfinder.synthesize("plan travel from Lagos to Abuja",
                                       tasks, results)
        epi = report["epistemic"]
        assert set(epi) == {"observed", "interpreted", "assessed",
                            "recommended"}
        assert isinstance(epi["observed"], list)
        assert isinstance(epi["interpreted"], list)
        assert isinstance(epi["recommended"], list)
        assert epi["assessed"]["confidence"] == report["confidence"]
        assert "never a single" in epi["assessed"]["confidence_axis"]

    def test_executed_tree_report_carries_epistemic(self, store):
        """Line-level smoke: a full tree run emits the §70 block with the
        observed layer derived from EVIDENCE-labelled key evidence."""
        import asyncio
        goal = "assess journey Lagos to Abuja"
        report = asyncio.run(pathfinder.run_goal(goal, store))
        assert "epistemic" in report
        observed = report["epistemic"]["observed"]
        evidenced = [e for e in report["key_evidence"]
                     if e.get("trust_label") == "EVIDENCE"]
        if evidenced:  # offline env → branch may degrade (§20)
            assert observed, "EVIDENCE entries must surface in observed"


# -------------------------------------------------- §49-51 Coverage axis ---
class TestCoverageAxis:
    def test_high_needs_three_groups_and_primary(self):
        cov, basis = _coverage_assessment(3, True)
        assert cov == "HIGH" and "PRIMARY" in basis

    def test_three_groups_no_primary_is_medium(self):
        cov, _ = _coverage_assessment(3, False)
        assert cov == "MEDIUM"

    def test_two_groups_medium(self):
        cov, _ = _coverage_assessment(2, False)
        assert cov == "MEDIUM"

    def test_single_group_low(self):
        cov, basis = _coverage_assessment(1, False)
        assert cov == "LOW" and "provisional" in basis

    def test_unverified_response_has_low_coverage(self, store):
        """§1.9 + §49-51: absence of evidence = LOW coverage, never FALSE."""
        from app.core.reasoning_engine import ReasoningEngine
        engine = ReasoningEngine(store)
        resp = engine._unverified("nothing anywhere confirms this claim xyz",
                                  trace=[], reason="no signals",
                                  action="Try again later")
        assert resp.coverage == "LOW"
        assert "not be read as 'claim is false'" in resp.coverage_basis


# -------------------------------------------- §6/§32 Source Health ----------
class TestSourceHealthStates:
    def test_vocabulary_matches_spec(self):
        assert set(SOURCE_HEALTH_STATES) == {
            "ACTIVE", "DEGRADED", "AUTH_REQUIRED", "SCHEMA_CHANGED",
            "DEPRECATED", "UNAVAILABLE"}

    @pytest.mark.parametrize("meta,state", [
        ({"health_note": "401 unauthorized since patch", "health_score": 0.9},
         "AUTH_REQUIRED"),
        ({"health_note": "SCHEMA drift: 'items' moved", "health_score": 0.9},
         "SCHEMA_CHANGED"),
        ({"health_note": "DEPRECATED feed, use v2", "health_score": 0.9},
         "DEPRECATED"),
        ({"health_note": "", "health_score": 0.1}, "UNAVAILABLE"),
        ({"health_note": "", "health_score": 0.5}, "DEGRADED"),
        ({"health_note": "", "health_score": 0.95}, "ACTIVE"),
        ({"health_note": "", "health_score": None,
          "last_success_at": "2026-09-17"}, "ACTIVE"),
        ({"health_note": "", "health_score": None, "last_success_at": None},
         "DEGRADED"),
    ])
    def test_deterministic_mapping(self, meta, state):
        assert _health_state(meta) == state

    def test_endpoint_shape(self, store, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "sh.db"))
        client = TestClient(app)
        client.get("/api/v1/admin/sources")  # idempotent admin surface
        r = client.get("/api/v1/feed/source-health")
        assert r.status_code == 200
        body = r.json()
        assert body["states_vocabulary"] == list(SOURCE_HEALTH_STATES)
        for s in body["sources"]:
            assert s["state"] in SOURCE_HEALTH_STATES
            assert "source_id" in s and "note" in s
