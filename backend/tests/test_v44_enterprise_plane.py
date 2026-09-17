"""v4.4 — ENTERPRISE PLANE tests (§73 Enterprise).

Covers: RBAC role resolution + permission matrix + route enforcement,
whoami honesty, the retention sweeper (dry-run default, per-class counts,
permanent invariants), SIEM export (NDJSON + taxonomy + HMAC), and the
custom-connector lifecycle (admin register → approval → ACTIVE → source
health visible → retire).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import approvals, connectors, rbac, retention            # noqa: E402
from app.core.errors import PipelineError                              # noqa: E402
from app.store.db import reset_store                                   # noqa: E402


def _client(tmp_path, name="v44.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    reset_store(str(tmp_path / name))
    return TestClient(app)


# -------------------------------------------------------------------- RBAC --
class TestRbac:
    def test_role_vocabulary_and_rank(self):
        assert rbac.ROLES == ("viewer", "analyst", "governance", "admin")
        assert (rbac.role_rank("admin") > rbac.role_rank("governance")
                > rbac.role_rank("analyst") > rbac.role_rank("viewer"))

    def test_resolution_never_self_elevates_api_keys(self):
        role = rbac.resolve_role(is_demo_path=False, api_key_role="admin",
                                 header_role="admin")
        assert role == "admin"
        # key callers: unknown role degrades to viewer, header is ignored
        role = rbac.resolve_role(is_demo_path=False, api_key_role="root",
                                 header_role="admin")
        assert role == "viewer"

    def test_demo_path_override_documented(self):
        assert rbac.resolve_role(is_demo_path=True,
                                 header_role="viewer") == "viewer"
        assert rbac.resolve_role(is_demo_path=True) == "admin"

    def test_require_role_denies_below_floor(self):
        with pytest.raises(PipelineError) as e:
            rbac.require_role({"role": "analyst"}, "approvals.decide")
        assert e.value.status == 403
        assert "governance" in e.value.detail
        rbac.require_role({"role": "governance"}, "approvals.decide")

    def test_unmapped_permission_open(self):
        rbac.require_role({"role": "viewer"}, "unknown.perm")

    def test_whoami_route(self, tmp_path):
        client = _client(tmp_path)
        r = client.get("/api/v1/ops/whoami")
        body = r.json()
        assert body["role"] == "admin"          # demo human default
        assert "approvals.decide" in body["permissions_granted"]
        assert body["roles_vocabulary"] == list(rbac.ROLES)
        r2 = client.get("/api/v1/ops/whoami",
                        headers={"X-TH360-Role": "viewer"})
        assert r2.json()["permissions_granted"] == ["read"]

    def test_route_enforcement_403_for_viewer(self, tmp_path):
        client = _client(tmp_path)
        h = {"X-TH360-Role": "viewer"}
        assert client.post("/api/v1/ops/assurance/sweep",
                           headers=h).status_code == 403
        assert client.get("/api/v1/ops/agents/inventory",
                          headers=h).status_code == 403
        assert client.post("/api/v1/ops/retention/apply",
                           json={"dry_run": True},
                           headers=h).status_code == 403
        assert client.get("/api/v1/ops/siem/export",
                          headers=h).status_code == 403

    def test_enterprise_key_role_governance(self, tmp_path):
        client = _client(tmp_path)
        h = {"X-API-Key": "sk_demo_threathunter360"}
        body = client.get("/api/v1/ops/whoami", headers=h).json()
        assert body["role"] == "governance"
        assert body["auth_class"] == "api_key"
        # governance can sweep, cannot manage connectors
        assert client.post("/api/v1/ops/assurance/sweep",
                           headers=h).status_code == 200
        c = client.post("/api/v1/ops/connectors", json={
            "name": "Demo TI", "kind": "C_data_api",
            "base_url": "https://ti.example"}, headers=h)
        assert c.status_code == 403


# ---------------------------------------------------------------- retention -
class TestRetention:
    def _age(self, store, days, table, ts_col):
        past = (datetime.now(timezone.utc)
                - timedelta(days=days)).isoformat()
        with store._lock:
            store._conn.execute(
                f"UPDATE {table} SET {ts_col}=?", (past,))
            store._conn.commit()

    def test_dry_run_never_deletes(self, store):
        store.notify(kind="TEST", title="old", body="b")
        self._age(store, 200, "notifications", "created_at")
        rep = retention.apply_retention(store, dry_run=True)
        cls = rep["classes"]["notifications_older_than_cutoff"]
        assert cls["action"] == "would_delete" and cls["count"] == 1
        assert store.list_notifications(limit=10)  # still there

    def test_apply_deletes_old_only(self, store):
        store.notify(kind="TEST", title="old", body="b")
        self._age(store, 200, "notifications", "created_at")
        store.notify(kind="TEST", title="fresh", body="b")
        rep = retention.apply_retention(store, dry_run=False)
        assert rep["classes"]["notifications_older_than_cutoff"]["count"] == 1
        titles = [n["title"] for n in store.list_notifications(limit=10)]
        assert "fresh" in titles and "old" not in titles

    def test_trees_only_terminal_states(self, store):
        from app.swarm import pathfinder
        plan = pathfinder.propose_plan("plan travel from Lagos to Abuja",
                                       store)
        store.update_tree(plan["tree_id"], status="COMPLETE")
        self._age(store, 60, "ops_trees", "updated_at")
        old = store.old_trees(
            (datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
        assert old == [plan["tree_id"]]  # COMPLETE, aged
        rep = retention.apply_retention(store, dry_run=False)
        assert rep["classes"]["terminal_trees_older_than_cutoff"][
            "count"] == 1
        assert store.get_tree(plan["tree_id"]) is None

    def test_audit_and_consent_untouched(self, store):
        store.audit(actor="a", action="old_action", decision="ALLOW",
                    detail="x", policy_version="t")
        before = len(store.audit_trail(limit=100))
        retention.apply_retention(store, dry_run=False)
        # nothing deleted; growth is exactly the sweeper's own audit row —
        # retention runs are themselves auditable by design.
        rows = store.audit_trail(limit=100)
        assert len(rows) == before + 1
        assert rows[0]["action"] == "retention:applied"
        assert any(r["action"] == "old_action" for r in rows)
        assert "consent_ledger" in retention.apply_retention(
            store)["permanent_classes"]

    def test_route_rbac(self, tmp_path):
        client = _client(tmp_path)
        ok = client.post("/api/v1/ops/retention/apply",
                         json={"dry_run": True})
        assert ok.status_code == 200
        assert ok.json()["dry_run"] is True


# -------------------------------------------------------------------- SIEM --
class TestSiemExport:
    def test_ndjson_shape_and_taxonomy(self, tmp_path):
        client = _client(tmp_path)
        # produce real audit entries first (id-audit writes to the trail)
        client.post("/api/v1/privacy/id-audit",
                    json={"identity": "acme-parcels.xyz"})
        r = client.get("/api/v1/ops/siem/export?since_hours=24")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        assert "X-Th360-Record-Count" in r.headers
        lines = [l for l in r.text.strip().split("\n") if l]
        import json as _json
        for l in lines[:5]:
            rec = _json.loads(l)
            for k in ("ts", "actor", "action", "decision",
                      "taxonomy_class", "policy_version", "source"):
                assert k in rec
        assert any(_json.loads(l)["taxonomy_class"] == "identity_audit"
                   for l in lines)
        # classification is deterministic across the known prefixes
        from app.api.routes.enterprise import _classify
        assert _classify("event:X") == "platform_event"
        assert _classify("policy:probe") == "policy_decision"
        assert _classify("safety_event:ethics") == "safety"
        assert _classify("anything_else") == "governance"

    def test_hmac_signature_when_key_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TH360_SIEM_KEY", "unit-test-key")
        import hmac, hashlib
        client = _client(tmp_path)
        r = client.get("/api/v1/ops/siem/export")
        sig = r.headers.get("X-Th360-Signature", "")
        assert sig.startswith("sha256=")
        expected = hmac.new(b"unit-test-key", r.text.encode(),
                            hashlib.sha256).hexdigest()
        assert sig == f"sha256={expected}"

    def test_no_signature_without_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TH360_SIEM_KEY", raising=False)
        client = _client(tmp_path)
        r = client.get("/api/v1/ops/siem/export")
        assert "X-Th360-Signature" not in r.headers


# ---------------------------------------------------------------- connectors -
class TestConnectors:
    def test_register_pend_activate_retire(self, tmp_path):
        client = _client(tmp_path)
        reg = client.post("/api/v1/ops/connectors", json={
            "name": "Demo TI Feed", "kind": "C_data_api",
            "base_url": "https://ti.example/api",
            "auth_env": "DEMO_TI_API_KEY"})
        assert reg.status_code == 200
        body = reg.json()
        assert body["status"] == "PENDING_APPROVAL"
        approval_id = body["approval"]["id"]
        # connector must NOT be active before grant
        pre = client.get(f"/api/v1/ops/connectors").json()["connectors"][0]
        assert pre["status"] == "PENDING_APPROVAL"
        # grant through the approvals queue → durable effect fires
        dec = client.post(f"/api/v1/ops/approvals/{approval_id}/approve",
                          json={"decided_by": "gov"})
        assert dec.status_code == 200
        post = client.get("/api/v1/ops/connectors").json()["connectors"][0]
        assert post["status"] == "ACTIVE"
        # visible in the source health monitor from day one (§6/§32)
        health = client.get("/api/v1/feed/source-health").json()
        assert any(s["source_id"] == "connector:Demo TI Feed"
                   for s in health["sources"])
        # retire (admin path)
        ret = client.post(f"/api/v1/ops/connectors/{body['id']}/retire")
        assert ret.json()["status"] == "RETIRED"

    def test_reject_never_activates(self, tmp_path):
        client = _client(tmp_path)
        reg = client.post("/api/v1/ops/connectors", json={
            "name": "Bad Feed", "kind": "B_discovery",
            "base_url": "https://bad.example"}).json()
        client.post(
            f"/api/v1/ops/approvals/{reg['approval']['id']}/reject",
            json={"decided_by": "gov"})
        post = client.get("/api/v1/ops/connectors").json()["connectors"][0]
        assert post["status"] == "PENDING_APPROVAL"   # not activated
        health = client.get("/api/v1/feed/source-health").json()
        assert not any(s["source_id"] == "connector:Bad Feed"
                       for s in health["sources"])

    def test_secret_rejected_never_stored(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/ops/connectors", json={
            "name": "Leaky Feed", "kind": "C_data_api",
            "base_url": "https://leak.example",
            "auth_env": "sk-abcdef1234567890"})
        assert r.status_code == 422

    def test_kind_closed_set(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/ops/connectors", json={
            "name": "X Feed", "kind": "Z_magic",
            "base_url": "https://x.example"})
        assert r.status_code == 422

    def test_register_requires_admin(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/ops/connectors", json={
            "name": "Y Feed", "kind": "C_data_api",
            "base_url": "https://y.example"},
            headers={"X-TH360-Role": "governance"})
        assert r.status_code == 403
