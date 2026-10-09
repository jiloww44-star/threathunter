"""v4.2 — GOVERNANCE PLANES tests (§73 V2).

Covers: the policy engine as the single deterministic decision point
(PERMIT/DENY/REQUIRE_HUMAN + check ledger + audit), authorize_run parity
after delegation, the approval engine lifecycle (§26 ApprovalRequested/
ApprovalGranted/Rejected, double-decide 409, grant-only effects), and the
agent inventory / readiness / supply-chain cards.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import agent_inventory, approvals, investigation         # noqa: E402
from app.core import policy_engine                                      # noqa: E402
from app.core.errors import PipelineError                               # noqa: E402
from app.store.db import reset_store                                    # noqa: E402


def _client(tmp_path, name="v42.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    reset_store(str(tmp_path / name))
    return TestClient(app)


def _inv(store, **kw):
    kw.setdefault("objective", "gate test")
    kw.setdefault("subject_type", "domain")
    kw.setdefault("subject", "example.ng")
    kw.setdefault("purpose", "gate testing")
    kw.setdefault("authority", "organization_owned")
    kw.setdefault("scope", "passive")
    kw.setdefault("allowed_sources", None)
    kw.setdefault("expires_days", 10)
    kw.setdefault("user_id", "u")
    return investigation.create(store, **kw)


# -------------------------------------------------------- policy engine ----
class TestPolicyEngine:
    def test_permit_on_clean_run(self, store):
        inv = _inv(store)
        d = policy_engine.evaluate(
            store, action="investigation_run", subject=inv["id"],
            investigation_row=store.inv_get(inv["id"]))
        assert d.decision == "PERMIT"
        assert d.policy_version.startswith("policy-engine/")
        assert all(c["outcome"] == "PASS" for c in d.checks)

    def test_deny_closed_and_reasons(self, store):
        inv = _inv(store)
        investigation.close(store, inv["id"], actor="u")
        d = policy_engine.evaluate(
            store, action="investigation_run", subject=inv["id"],
            investigation_row=store.inv_get(inv["id"]))
        assert d.decision == "DENY"
        c = next(c for c in d.checks if c["check"] == "R-INV-LIFECYCLE")
        assert c["outcome"] == "FAIL"
        assert any("living authorization" in r for r in d.reasons)

    def test_deny_out_of_scope_sources(self, store):
        inv = _inv(store, allowed_sources=["osint_databases", "rdap"])
        d = policy_engine.evaluate(
            store, action="investigation_run", subject=inv["id"],
            investigation_row=store.inv_get(inv["id"]),
            requested_sources=["routes", "weather"])
        assert d.decision == "DENY"
        c = next(c for c in d.checks if c["check"] == "R-DENY-SOURCES")
        assert c["outcome"] == "FAIL" and "routes" in c["detail"]
        assert any("§35" in r for r in d.reasons)

    def test_require_human_external_effect(self, store):
        d = policy_engine.evaluate(store, action="apply_patch",
                                   subject="CVE-2026-0001",
                                   action_class="patch_apply")
        assert d.decision == "REQUIRE_HUMAN"
        assert any("§27" in r for r in d.reasons)

    def test_dispatch_allowlist_rule(self, store):
        d = policy_engine.evaluate(
            store, action="dispatch", agent_id="HUNTER",
            function="delete_production_db")
        assert d.decision == "DENY"
        assert any("A-14" in r for r in d.reasons)
        ok = policy_engine.evaluate(
            store, action="dispatch", agent_id="HUNTER",
            function="footprint_scan")
        assert ok.decision == "PERMIT"

    def test_record_writes_audit(self, store):
        d = policy_engine.evaluate(store, action="probe",
                                   action_class="patch_apply")
        policy_engine.record(store, d, actor="tester")
        rows = [a for a in store.audit_trail(limit=10)
                if a["action"] == "policy:probe"]
        assert rows and rows[0]["decision"] == "REQUIRE_HUMAN"
        assert rows[0]["policy_version"].startswith("policy-engine/")

    def test_authorize_run_parity_after_delegation(self, store):
        """v4.0 behavior must be identical through the engine (§76)."""
        inv = _inv(store, allowed_sources=["osint_databases", "rdap"])
        with pytest.raises(PipelineError) as e:
            investigation.authorize_run(store, inv["id"],
                                        branches=["journey"], user_id="u")
        assert e.value.code == "ACTION_DENIED"
        assert "§35" in e.value.detail
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with store._lock:
            store._conn.execute(
                "UPDATE investigations SET expires_at=? WHERE id=?",
                (past, inv["id"]))
            store._conn.commit()
        with pytest.raises(PipelineError) as e2:
            investigation.authorize_run(store, inv["id"],
                                        branches=["intel"], user_id="u")
        assert "expired" in e2.value.detail


# ------------------------------------------------------ approval engine ----
class TestApprovalEngine:
    def test_lifecycle_events_and_status(self, store):
        req = approvals.request(store, kind="patch_apply",
                                subject_ref="CVE-2026-0001",
                                summary="apply vendor patch",
                                requester="sentinel")
        assert req["status"] == "PENDING"
        out = approvals.decide(store, req["id"], approved=True,
                               decided_by="operator")
        assert out["status"] == "APPROVED"
        assert out["decided_by"] == "operator"
        actions = [a["action"] for a in store.audit_trail(limit=50)]
        assert "event:ApprovalRequested" in actions
        assert "event:ApprovalGranted" in actions

    def test_reject_never_runs_effect(self, store):
        ran = []
        req = approvals.request(store, kind="execute_dork_set",
                                subject_ref="dorks:example.ng",
                                summary="run 3 dorks", requester="osint")
        approvals.decide(store, req["id"], approved=False,
                         decided_by="operator",
                         on_approval=lambda row: ran.append(row["id"]))
        assert ran == []
        assert any("ApprovalRejected" in a["action"]
                   for a in store.audit_trail(limit=50))

    def test_approval_only_effect(self, store):
        ran = []
        req = approvals.request(store, kind="patch_apply",
                                subject_ref="CVE-1", summary="patch",
                                requester="sentinel")
        assert ran == []  # request alone executes nothing
        approvals.decide(store, req["id"], approved=True,
                         decided_by="op",
                         on_approval=lambda row: ran.append("ran"))
        assert ran == ["ran"]

    def test_double_decide_409(self, store):
        req = approvals.request(store, kind="patch_apply",
                                subject_ref="CVE-2", summary="patch",
                                requester="sentinel")
        approvals.decide(store, req["id"], approved=True, decided_by="a")
        with pytest.raises(PipelineError) as e:
            approvals.decide(store, req["id"], approved=False,
                             decided_by="b")
        assert e.value.code == "APPROVAL_NOT_PENDING"
        assert e.value.status == 409
        # and the recorded decision is untouched
        assert store.approval_get(req["id"])["decided_by"] == "a"

    def test_unknown_approval_404(self, store):
        with pytest.raises(PipelineError) as e:
            approvals.decide(store, "ghost", approved=True, decided_by="a")
        assert e.value.status == 404

    def test_promotion_flow_mints_approval_chain(self, tmp_path):
        client = _client(tmp_path)
        reg = client.post("/api/v1/ops/agents/custom",
                          json={"name": "ACME-Scout",
                                "functions": ["footprint_scan"]})
        assert reg.status_code == 200
        agent_id = reg.json()["agent_id"]
        r = client.post(f"/api/v1/ops/agents/custom/{agent_id}/promote")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ACTIVE"
        assert body["approval"]["status"] == "APPROVED"
        assert body["approval"]["kind"] == "promote_custom_agent"
        # on the trail: the spec's two §26 names, in order
        audit = client.get("/api/v1/ops/audit?limit=100").json()["audit_trail"]
        names = [a["action"] for a in audit]
        assert "event:ApprovalRequested" in names
        assert "event:ApprovalGranted" in names
        assert (names.index("event:ApprovalRequested")
                > names.index("event:ApprovalGranted"))  # trail is DESC

    def test_approvals_list_and_decide_routes(self, tmp_path):
        client = _client(tmp_path)
        client.post("/api/v1/osint/forensics/media",
                    json={"media_ref": "mock:pass"})  # some activity
        # seed a PENDING approval through the engine directly
        from app.store.db import get_store
        db = get_store()
        req = approvals.request(db, kind="patch_apply", subject_ref="CVE-x",
                                summary="route test", requester="tester")
        lst = client.get("/api/v1/ops/approvals?status=PENDING").json()
        assert any(a["id"] == req["id"] for a in lst["approvals"])
        r = client.post(f"/api/v1/ops/approvals/{req['id']}/reject",
                        json={"decided_by": "op"})
        assert r.status_code == 200
        assert r.json()["status"] == "REJECTED"
        r2 = client.post(f"/api/v1/ops/approvals/{req['id']}/approve",
                         json={"decided_by": "op"})
        assert r2.status_code == 409


# --------------------------------------------------- agent inventory (V2) --
class TestAgentInventory:
    def test_per_node_supply_chain_fields(self, store):
        inv = agent_inventory.inventory(store)
        assert inv["agents"]
        for n in inv["agents"]:
            # spec's verbatim per-node set
            for k in ("owner", "version", "source", "publisher",
                      "permissions", "credentials", "trust_status",
                      "last_reviewed", "known_issue", "runtime_exposure",
                      "data_classification"):
                assert k in n, (n["agent_id"], k)
            assert n["blast_radius_note"]  # the key question, answered

    def test_trust_status_mapping(self, store):
        store.register_custom_agent("CUSTOM-Demo", "Demo",
                                    ["footprint_scan"], status="SHADOW",
                                    drift_notes=None)
        inv = agent_inventory.inventory(store)
        by_id = {n["agent_id"]: n for n in inv["agents"]}
        assert by_id["AUDITOR"]["trust_status"] == "TRUSTED"
        assert by_id["CUSTOM-Demo"]["trust_status"] == "OBSERVED"
        assert by_id["CUSTOM-Demo"]["owner"] == "tenant (SDK admission)"

    def test_blast_radius_is_honest_about_auditor(self, store):
        inv = agent_inventory.inventory(store)
        auditor_card = next(n for n in inv["agents"]
                            if n["agent_id"] == "AUDITOR")
        assert "worst case" in auditor_card["blast_radius_note"]

    def test_nist_readiness_phases(self, store):
        inv = agent_inventory.inventory(store)
        assert set(inv["readiness"]) == {"govern", "map", "measure",
                                         "manage"}
        assert inv["readiness"]["map"].startswith(f"{len(inv['agents'])}")
        assert "Honestly" not in inv["readiness"]["govern"]
        assert inv["honest_limits"]  # no fake package-hash claims

    def test_inventory_route(self, tmp_path):
        client = _client(tmp_path)
        r = client.get("/api/v1/ops/agents/inventory")
        assert r.status_code == 200
        body = r.json()
        assert body["agents"] and body["dependency_graph"]["edges"]
        assert any(e["from"] == "PATHFINDER"
                   for e in body["dependency_graph"]["edges"])