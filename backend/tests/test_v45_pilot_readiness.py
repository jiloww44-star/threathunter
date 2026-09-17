"""v4.5 — PRODUCTION PILOT READINESS tests.

Covers: the §71/§72 KPI engine (shape, windowing, honesty — UNAVAILABLE with
named basis, never a fabricated zero), the override instrumentation behind
governance KPIs, the Prometheus export contract (UNAVAILABLE ⇒ no value
line), and the first REAL live source (crt.sh) entering exclusively through
the §80 connector registry — lifecycle gate (§76), scope binding (§63),
connector ACTIVE + allowlist, provenance-stamped evidence, idempotency,
classified fetch failures (§20).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import approvals, connectors, investigation, kpis  # noqa: E402
from app.core import live_sources                                # noqa: E402
from app.core.errors import PipelineError                        # noqa: E402
from app.store.db import get_store, reset_store                  # noqa: E402

NOW = datetime.now(timezone.utc)


def _client(tmp_path, name="v45.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    reset_store(str(tmp_path / name))
    return TestClient(app)


def _store():
    return get_store()


def _make_case(store, subject="example.com", sources=None, days=7):
    return investigation.create(
        store, objective="Map the public attack surface",
        subject_type="domain", subject=subject,
        purpose="pilot surface mapping", authority="organization_owned",
        scope="passive CT only", allowed_sources=sources, expires_days=days,
        user_id="pilot")


def _activate_crtsh(store) -> dict:
    row = connectors.register(store, name="crtsh", kind="C_data_api",
                              base_url="https://crt.sh", auth_env=None,
                              actor="admin")
    approvals.decide(store, row["approval"]["id"], approved=True,
                     decided_by="gov")
    return store.connector_get(row["id"])


def _fake_http(names):
    class _Resp:
        status_code = 200

        def json(self):
            return [{"name_value": n} for n in names]

    return lambda url: _Resp()


# ----------------------------------------------------------- KPI shape/honesty
class TestKpiShapeAndHonesty:
    def test_all_families_and_north_star_present(self, tmp_path):
        _client(tmp_path)
        report = kpis.compute_kpis(_store())
        assert set(report["families"]) == {
            "intelligence_quality", "journey", "fact_checker",
            "agent_security", "governance"}
        assert report["north_star"]["id"] == (
            "evidence_backed_decisions_completed")
        assert "§72" in report["north_star"]["spec"]

    def test_north_star_zero_is_measured_not_fabricated(self, tmp_path):
        _client(tmp_path)
        ns = kpis.compute_kpis(_store())["north_star"]
        assert ns["status"] == "OK" and ns["value"] == 0
        assert ns["sample"] == 0 and "CLOSED" in ns["basis"]

    def test_unavailable_carries_basis_never_zero(self, tmp_path):
        _client(tmp_path)
        fams = kpis.compute_kpis(_store())["families"]
        corr = fams["intelligence_quality"]["analyst_correction_rate"]
        assert corr["status"] == "UNAVAILABLE"
        assert corr["value"] is None and "P-3" in corr["basis"]
        # no investigations at all → completion is undefined, not 0.0
        comp = fams["journey"]["completion_rate"]
        assert comp["status"] == "UNAVAILABLE"
        # genuinely missing write-paths are named, not silently absent
        assert fams["fact_checker"]["latency"]["status"] == "UNAVAILABLE"
        assert "write-path" in fams["fact_checker"]["latency"]["basis"]

    def test_every_value_has_basis(self, tmp_path):
        _client(tmp_path)
        report = kpis.compute_kpis(_store())
        for fam in report["families"].values():
            for kv in fam.values():
                assert kv["status"] in ("OK", "UNAVAILABLE")
                assert kv["basis"] and len(kv["basis"]) > 10
        assert report["north_star"]["basis"]

    def test_policy_decision_counters_from_real_gate(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        # a real consequential attempt (dork generation) walks authorize_run
        r = client.post("/api/v1/osint/dorks", json={
            "objective": "find public exposure", "subject": "example.com",
            "investigation_id": inv["id"]})
        assert r.status_code == 200
        gov = kpis.compute_kpis(store)["families"]["governance"]
        decisions = gov["policy_decisions"]
        assert decisions["status"] == "OK"
        assert decisions["sample"] >= 1
        assert any(k in decisions["value"] for k in
                   ("PERMIT", "ALLOW", "REQUIRE_HUMAN"))


# --------------------------------------------------------------- KPI measured
class TestKpiMeasured:
    def _closed_case_with(self, store, with_evidence: bool):
        inv = _make_case(store)
        if with_evidence:
            store.inv_link(f"lnk-{inv['id']}", inv["id"], "evidence",
                           "ev-demo-1")
        investigation.close(store, inv["id"], actor="pilot")
        return inv

    def test_north_star_and_completion(self, tmp_path):
        _client(tmp_path)
        store = _store()
        self._closed_case_with(store, True)
        self._closed_case_with(store, False)
        report = kpis.compute_kpis(store)
        assert report["north_star"]["value"] == 1
        assert report["north_star"]["sample"] == 2
        journey = report["families"]["journey"]["completion_rate"]
        assert journey["status"] == "OK" and journey["value"] == 1.0
        concl = (report["families"]["intelligence_quality"]
                 ["evidence_backed_conclusion_rate"])
        assert concl["value"] == 0.5 and concl["sample"] == 2

    def test_decision_latency_and_override_exceptions(self, tmp_path):
        _client(tmp_path)
        store = _store()
        req = approvals.request(
            store, kind="patch_apply", subject_ref="CVE-2026-0001",
            summary="apply patch", requester="analyst",
            context={"decision_basis_overrides": [
                "severity re-classified LOW after manual review"]})
        approvals.decide(store, req["id"], approved=True, decided_by="gov")
        fams = kpis.compute_kpis(store)["families"]
        lat = fams["journey"]["decision_latency"]
        assert lat["status"] == "OK" and lat["sample"] == 1
        assert lat["value"] >= 0.0
        exc = fams["governance"]["override_exceptions"]
        assert exc["status"] == "OK" and exc["value"] == 1
        assert fams["governance"]["override_rate"]["value"] == 1.0
        assert fams["agent_security"]["remediated_findings"]["value"] == 1

    def test_evidence_completeness_and_reconstruction_measured(self, tmp_path):
        _client(tmp_path)
        gov = kpis.compute_kpis(_store())["families"]["governance"]
        chain = gov["evidence_completeness"]
        assert chain["status"] == "OK" and chain["value"] == 1.0
        recon = gov["reconstruction_time"]
        assert recon["status"] == "OK" and recon["value"] >= 0.0
        assert "500" in recon["basis"]

    def test_agent_security_from_live_inventory(self, tmp_path):
        _client(tmp_path)
        sec = kpis.compute_kpis(_store())["families"]["agent_security"]
        assert sec["inventory_total"]["status"] == "OK"
        assert sec["inventory_total"]["value"] >= 5  # native roster
        dist = sec["trust_distribution"]["value"]
        assert sum(dist.values()) == sec["inventory_total"]["value"]
        assert sec["review_coverage"]["value"] == 1.0

    def _record_factcheck(self, store, coverage, indep):
        store.record_check(
            "factcheck", "claim", "VERIFIED", "HIGH",
            {"verdict": "VERIFIED", "coverage": coverage,
             "sources_independent": indep})

    def test_fact_checker_family_mines_check_rows(self, tmp_path):
        _client(tmp_path)
        store = _store()
        self._record_factcheck(store, "HIGH", 3)
        self._record_factcheck(store, "LOW", 1)
        fam = kpis.compute_kpis(store)["families"]["fact_checker"]
        assert fam["runs"]["value"] == 2
        assert fam["evidence_coverage"]["value"] == 0.5
        assert fam["agreement"]["value"] == 2.0

    def test_window_excludes_old_runs(self, tmp_path):
        _client(tmp_path)
        store = _store()
        self._record_factcheck(store, "HIGH", 2)
        old = (NOW - timedelta(hours=999)).isoformat()
        with store._lock:
            store._conn.execute("UPDATE checks SET created_at=?", (old,))
            store._conn.commit()
        fam = kpis.compute_kpis(store, window_hours=24)["families"][
            "fact_checker"]
        assert fam["runs"]["value"] == 0
        assert fam["evidence_coverage"]["status"] == "UNAVAILABLE"
        fam_all = kpis.compute_kpis(store, window_hours=2000)["families"][
            "fact_checker"]
        assert fam_all["runs"]["value"] == 1


# --------------------------------------------------------------- Prometheus
class TestPrometheusExport:
    def test_unavailable_emits_no_value_line(self, tmp_path):
        client = _client(tmp_path)
        r = client.get("/api/v1/ops/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        text = r.text
        assert 'family="north_star",metric="evidence_backed_decisions' \
               '_completed"} 0' in text
        # UNAVAILABLE series: availability gauge 0, NO fabricated value
        assert ('th360_kpi_available{family="journey",'
                'metric="decision_latency"} 0') in text
        for line in text.splitlines():
            if line.startswith("th360_kpi_value"):
                fam_metric = line.split("{", 1)[1].split("}", 1)[0]
                assert "decision_latency" not in fam_metric

    def test_metrics_route_rbac_read_tier(self, tmp_path):
        client = _client(tmp_path)
        assert client.get("/api/v1/ops/metrics",
                          headers={"X-TH360-Role": "viewer"}
                          ).status_code == 200

    def test_ops_kpis_embeds_v71_and_standalone_route(self, tmp_path):
        client = _client(tmp_path)
        body = client.get("/api/v1/ops/kpis").json()
        assert body["v71"]["north_star"]["status"] == "OK"
        v71 = client.get("/api/v1/ops/kpis/v71").json()
        assert v71["kpi_version"] == kpis.KPI_ENGINE_VERSION
        assert v71["spec"].startswith("§71")


# -------------------------------------------------------------- live source
class TestCrtshLiveSource:
    def _post(self, client, inv_id, domain="example.com", headers=None):
        return client.post("/api/v1/osint/live/crtsh",
                           json={"investigation_id": inv_id,
                                 "domain": domain},
                           headers=headers or {})

    def test_missing_case_404(self, tmp_path):
        client = _client(tmp_path)
        assert self._post(client, "nope-nope").status_code == 404

    def test_connector_not_active_409_with_playbook(self, tmp_path):
        client = _client(tmp_path)
        inv = _make_case(_store())
        r = self._post(client, inv["id"])
        assert r.status_code == 409
        body = r.json()
        assert body["error_code"] == "CONNECTOR_NOT_ACTIVE"
        # §20 degraded shape reaches the caller: what happened / to do
        assert "what_to_do" in body["detail"] and "approve" in body["detail"]

    def test_pending_connector_is_not_active(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        connectors.register(store, name="crtsh", kind="C_data_api",
                            base_url="https://crt.sh", auth_env=None,
                            actor="admin")
        assert self._post(client, inv["id"]).status_code == 409

    def test_closed_case_gate_76(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate_crtsh(store)
        investigation.close(store, inv["id"], actor="pilot")
        r = self._post(client, inv["id"])
        assert r.status_code == 403
        assert r.json()["error_code"] == "ACTION_DENIED"
        assert "authorization" in r.json()["meaning"].lower()

    def test_scope_binding_63(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store, subject="example.com")
        _activate_crtsh(store)
        # out-of-cone domain → classified 422 before any network happens
        r = self._post(client, inv["id"], domain="totally-other.org")
        assert r.status_code == 422
        assert r.json()["error_code"] == "INVALID_CONSENT"
        assert "scope violation" in r.json()["detail"].lower()
        # subdomain cone of the case subject passes governance end-to-end
        monkeypatch.setattr(live_sources, "_http_get",
                            _fake_http(["a.www.example.com"]))
        ok = self._post(client, inv["id"], domain="WWW.Example.COM")
        assert ok.status_code == 200
        assert ok.json()["domain"] == "www.example.com"

    def test_allowlist_denies_unlisted_connector(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store, sources=["some-other-source"])
        _activate_crtsh(store)
        r = self._post(client, inv["id"])
        assert r.status_code == 403
        assert r.json()["error_code"] == "ACTION_DENIED"
        assert "allowed_sources" in r.json()["detail"]

    def test_rbac_viewer_cannot_observe(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate_crtsh(store)
        r = self._post(client, inv["id"], headers={"X-TH360-Role": "viewer"})
        assert r.status_code == 403

    def test_success_full_governed_chain(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        conn = _activate_crtsh(store)
        monkeypatch.setattr(live_sources, "_http_get",
                            _fake_http(["www.example.com",
                                        "mail.example.com\napi.example.com"]))
        r = self._post(client, inv["id"])
        assert r.status_code == 200
        body = r.json()
        assert body["observed_total"] == 3
        assert body["new_evidence"] is True and body["newly_linked"] is True
        assert body["connector"]["id"] == conn["id"]
        assert body["osint_class"].startswith("§64")
        assert body["provenance"]["result_hash" if False else "source"]
        # evidence row: provenance + reproducibility metadata
        ev = store.get_evidence(body["evidence_id"])
        assert ev["authority"] == "PRIMARY" and ev["reliability"] == "HIGH"
        meta = json.loads(ev["metadata_json"])
        assert meta["query_domain"] == "example.com"
        assert meta["result_hash"] == body["result_hash"]
        assert meta["collection"].startswith("PASSIVE")
        # case chain link (§5) + §26 events on the audit trail
        links = store.inv_links_for(inv["id"])
        assert ("evidence", body["evidence_id"]) in {
            (l["kind"], l["ref_id"]) for l in links}
        actions = [a["action"] for a in store.audit_trail(limit=50)]
        assert "event:SourceQueried" in actions
        assert "event:ObservationReceived" in actions
        # §6/32 source health now tracks the live connector as healthy
        health = client.get("/api/v1/feed/source-health").json()
        row = [s for s in health["sources"]
               if s["source_id"] == "connector:crtsh"]
        assert row and row[0]["state"] == "ACTIVE"
        # close the case → it feeds the §72 north-star (chain intact e2e)
        investigation.close(store, inv["id"], actor="pilot")
        assert kpis.compute_kpis(store)["north_star"]["value"] == 1

    def test_idempotent_reobservation_no_duplicates(self, tmp_path,
                                                    monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate_crtsh(store)
        monkeypatch.setattr(live_sources, "_http_get",
                            _fake_http(["www.example.com"]))
        first = self._post(client, inv["id"]).json()
        second = self._post(client, inv["id"]).json()
        assert first["new_evidence"] is True
        assert second["new_evidence"] is False
        assert second["evidence_id"] == first["evidence_id"]
        count = store.kpi_sql(
            "SELECT COUNT(*) c FROM evidence WHERE source_id=?",
            ("connector:crtsh",))[0]["c"]
        assert count == 1

    def test_classified_timeout_and_health_hit(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate_crtsh(store)

        def _timeout(url):
            raise httpx.TimeoutException("simulated pilot degradation")

        monkeypatch.setattr(live_sources, "_http_get", _timeout)
        r = self._post(client, inv["id"])
        assert r.status_code == 503
        assert r.json()["error_code"] == "SOURCE_TIMEOUT"
        detail = r.json()["detail"]
        assert "no observation was made" in detail  # §20: never fabricated
        # a failed observation is AUDITED as a denied SourceQueried and the
        # connector health register takes the hit (§6/32) — caught live:
        # pre-fix the monitor kept saying ACTIVE after failed fetches
        denials = [a for a in store.audit_trail(limit=50)
                   if a["action"] == "event:SourceQueried"
                   and a["decision"] == "DENY"]
        assert denials, "failed fetch must be on the trail"
        health = client.get("/api/v1/feed/source-health").json()
        row = [s for s in health["sources"]
               if s["source_id"] == "connector:crtsh"]
        assert row and row[0]["state"] == "DEGRADED"
        assert "SOURCE_TIMEOUT" in (row[0]["note"] or "")

    def test_domain_normalization_rejects_non_domains(self):
        assert live_sources.normalize_domain(
            "https://Example.COM/path") == "example.com"
        assert live_sources.normalize_domain("*.mail.example.org.") == (
            "mail.example.org")
        with pytest.raises(PipelineError) as e:
            live_sources.normalize_domain("not a domain")
        assert e.value.status == 422
        with pytest.raises(PipelineError):
            live_sources.normalize_domain("1.2.3.4")
