"""v4.7 — LIVE SOURCES II tests (§80 second source + §67 change detection).

Covers: RDAP fetch parsing (registered / unregistered-as-data / drift),
the identical governed gate order shared by both sources (the whole point
of the generalized runner), RDAP-specific response shape, §67 re-observation
change detection (new hash ⇒ supersede + event:ObservationChanged; same
hash ⇒ idempotent silence), the unregistered→registered transition, crtsh
regression parity through the new plumbing, and the live-source KPI
context metrics.
"""
import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import approvals, connectors, investigation, kpis   # noqa: E402
from app.core import live_sources                                 # noqa: E402
from app.core.errors import PipelineError                         # noqa: E402
from app.store.db import get_store, reset_store                  # noqa: E402


def _client(tmp_path, name="v47.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    reset_store(str(tmp_path / name))
    return TestClient(app)


def _store():
    return get_store()


def _make_case(store, subject="example.com", sources=None):
    return investigation.create(
        store, objective="Map the public attack surface",
        subject_type="domain", subject=subject,
        purpose="pilot surface mapping", authority="organization_owned",
        scope="passive CT+RDAP only", allowed_sources=sources,
        expires_days=7, user_id="pilot")


def _activate(store, name, base_url) -> dict:
    row = connectors.register(store, name=name, kind="C_data_api",
                              base_url=base_url, auth_env=None,
                              actor="admin")
    approvals.decide(store, row["approval"]["id"], approved=True,
                     decided_by="gov")
    return store.connector_get(row["id"])


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _rdap_payload(registrar="Example Registrar, Inc.", ns=None, status=None):
    return {
        "objectClassName": "domain",
        "rdapConformance": ["rdap_level_0"],
        "ldhName": "example.com",
        "status": status if status is not None
        else ["client transfer prohibited"],
        "entities": [{
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                       ["fn", {}, "text", registrar]]],
        }],
        "nameservers": [{"ldhName": n} for n in
                        (ns or ["a.iana-servers.net", "b.iana-servers.net"])],
        "events": [{"eventAction": "registration",
                    "eventDate": "1995-08-14T04:00:00Z"},
                   {"eventAction": "expiration",
                    "eventDate": "2027-08-13T04:00:00Z"}],
    }


def _post(client, inv_id, domain="example.com", path="/api/v1/osint/live/rdap",
          headers=None):
    return client.post(path, json={"investigation_id": inv_id,
                                   "domain": domain},
                       headers=headers or {})


# ----------------------------------------------------------------- fetcher --
class TestRdapFetch:
    def test_registered_parse(self):
        out = live_sources.fetch_rdap_domain(
            "example.com", http_get=lambda u: _Resp(_rdap_payload()))
        assert out["registered"] is True
        assert out["registrar"] == "Example Registrar, Inc."
        assert out["nameservers"] == ["a.iana-servers.net",
                                      "b.iana-servers.net"]
        assert any(e.startswith("registration:") for e in out["events"])
        assert out["canonical"]["registrar"] == "Example Registrar, Inc."
        assert out["source_version"] == "rdap_level_0"

    def test_404_is_data_not_error(self):
        out = live_sources.fetch_rdap_domain(
            "unregistered-xyz.example", http_get=lambda u: _Resp({}, 404))
        assert out["registered"] is False
        assert out["canonical"] == {"registered": False}

    def test_shape_drift_unverified_not_guessed(self):
        with pytest.raises(PipelineError) as e:
            live_sources.fetch_rdap_domain(
                "example.com", http_get=lambda u: _Resp(["not", "rdap"]))
        assert e.value.code == "SOURCE_BAD_RESPONSE" and e.value.status == 502
        with pytest.raises(PipelineError) as e2:
            live_sources.fetch_rdap_domain(
                "example.com",
                http_get=lambda u: _Resp(ValueError("bad json")))
        assert e2.value.code == "SOURCE_BAD_RESPONSE"

    def test_classified_failures(self):
        with pytest.raises(PipelineError) as e1:
            live_sources.fetch_rdap_domain(
                "example.com",
                http_get=lambda u: (_ for _ in ()).throw(
                    httpx.TimeoutException("t")))
        assert e1.value.code == "SOURCE_TIMEOUT" and e1.value.status == 503
        with pytest.raises(PipelineError) as e2:
            live_sources.fetch_rdap_domain(
                "example.com",
                http_get=lambda u: (_ for _ in ()).throw(
                    httpx.ConnectError("refused")))
        assert e2.value.code == "SOURCE_UNREACHABLE"
        with pytest.raises(PipelineError) as e3:
            live_sources.fetch_rdap_domain(
                "example.com", http_get=lambda u: _Resp({}, 429))
        assert e3.value.code == "SOURCE_THROTTLED"


# ------------------------------------------------------------ governed flow --
class TestRdapGovernedFlow:
    def test_connector_not_active_409(self, tmp_path):
        client = _client(tmp_path)
        inv = _make_case(_store())
        r = _post(client, inv["id"])
        assert r.status_code == 409
        assert r.json()["error_code"] == "CONNECTOR_NOT_ACTIVE"
        assert "rdap" in r.json()["detail"]

    def test_closed_case_403_and_scope_422(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        _activate(store, "rdap", "https://rdap.org")
        inv = _make_case(store)
        investigation.close(store, inv["id"], actor="pilot")
        assert _post(client, inv["id"]).status_code == 403
        inv2 = _make_case(store, subject="example.com")
        r = _post(client, inv2["id"], domain="other.org")
        assert r.status_code == 422 and "scope violation" in \
            r.json()["detail"].lower()

    def test_allowlist_deny_and_rbac(self, tmp_path):
        client = _client(tmp_path)
        store = _store()
        _activate(store, "rdap", "https://rdap.org")
        inv = _make_case(store, sources=["crtsh"])
        assert _post(client, inv["id"]).status_code == 403
        inv2 = _make_case(store)
        assert _post(client, inv2["id"],
                     headers={"X-TH360-Role": "viewer"}).status_code == 403

    def test_success_full_chain(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        conn = _activate(store, "rdap", "https://rdap.org")
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap_payload()))
        r = _post(client, inv["id"])
        assert r.status_code == 200
        body = r.json()
        assert body["registered"] is True
        assert body["registrar"] == "Example Registrar, Inc."
        assert body["connector"]["id"] == conn["id"]
        assert body["new_evidence"] is True and body["newly_linked"] is True
        ev = store.get_evidence(body["evidence_id"])
        meta = json.loads(ev["metadata_json"])
        assert meta["authority"] == "PRIMARY" and meta["collection"].startswith(
            "PASSIVE — RDAP")
        assert meta["parser_version"] == live_sources.LIVE_SOURCES_VERSION
        assert meta["query_domain"] == "example.com"
        actions = [a["action"] for a in store.audit_trail(limit=50)]
        assert "event:SourceQueried" in actions
        assert "event:ObservationReceived" in actions
        assert "event:ObservationChanged" not in actions
        health = client.get("/api/v1/feed/source-health").json()
        row = [s for s in health["sources"]
               if s["source_id"] == "connector:rdap"]
        assert row and row[0]["state"] == "ACTIVE"

    def test_unregistered_stores_honest_observation(self, tmp_path,
                                                    monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store, subject="unregistered-xyz.example")
        _activate(store, "rdap", "https://rdap.org")
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp({}, 404))
        r = _post(client, inv["id"], domain="unregistered-xyz.example")
        assert r.status_code == 200
        body = r.json()
        assert body["registered"] is False
        assert body["new_evidence"] is True
        # the stored row SAYS it plainly — 404-as-data, never a guess
        assert "NOT registered" in store.get_evidence(
            body["evidence_id"])["title"]
        assert body["status"] == [] and body["nameservers"] == []


# ------------------------------------------------------ §67 change detection
class TestChangeDetection:
    def test_idempotent_same_hash_no_change_event(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store, "rdap", "https://rdap.org")
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap_payload()))
        first = _post(client, inv["id"]).json()
        second = _post(client, inv["id"]).json()
        assert first["new_evidence"] is True
        assert second["new_evidence"] is False
        assert second["changed_from"] is None
        changes = store.kpi_sql(
            "SELECT COUNT(*) c FROM audit_trail "
            "WHERE action='event:ObservationChanged'")[0]["c"]
        assert changes == 0

    def test_changed_hash_supersedes_and_events(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store, "rdap", "https://rdap.org")
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap_payload()))
        first = _post(client, inv["id"]).json()
        monkeypatch.setattr(
            live_sources, "_http_get",
            lambda u: _Resp(_rdap_payload(registrar="New Registrar LLC",
                                          ns=["ns1.new.net"])))
        second = _post(client, inv["id"]).json()
        assert second["new_evidence"] is True
        assert second["changed_from"] == first["evidence_id"]
        assert second["result_hash"] != first["result_hash"]
        meta = json.loads(store.get_evidence(
            second["evidence_id"])["metadata_json"])
        assert meta["supersedes"] == first["evidence_id"]
        changes = [a for a in store.audit_trail(limit=50)
                   if a["action"] == "event:ObservationChanged"]
        assert len(changes) == 1 and "CHANGED" in changes[0]["detail"]
        # both rows stay in the case chain — supersession, never overwrite
        links = {(l["kind"], l["ref_id"])
                 for l in store.inv_links_for(inv["id"])}
        assert ("evidence", first["evidence_id"]) in links
        assert ("evidence", second["evidence_id"]) in links

    def test_unregistered_then_registered_flips_detector(self, tmp_path,
                                                         monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store, subject="newbrand.example")
        _activate(store, "rdap", "https://rdap.org")
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp({}, 404))
        first = _post(client, inv["id"], domain="newbrand.example").json()
        assert first["registered"] is False
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap_payload()))
        second = _post(client, inv["id"], domain="newbrand.example").json()
        assert second["registered"] is True
        assert second["changed_from"] == first["evidence_id"]

    def test_crtsh_change_detection_through_shared_plumbing(self, tmp_path,
                                                            monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store, "crtsh", "https://crt.sh")
        names_a = ["www.example.com"]
        names_b = ["www.example.com", "vpn.example.com"]
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp([{"name_value": n}
                                             for n in names_a]))
        first = _post(client, inv["id"],
                      path="/api/v1/osint/live/crtsh").json()
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp([{"name_value": n}
                                             for n in names_b]))
        second = _post(client, inv["id"],
                       path="/api/v1/osint/live/crtsh").json()
        assert second["observed_total"] == 2
        assert second["changed_from"] == first["evidence_id"]
        changes = store.kpi_sql(
            "SELECT COUNT(*) c FROM audit_trail "
            "WHERE action='event:ObservationChanged'")[0]["c"]
        assert changes == 1

    def test_crtsh_response_key_parity_after_rewrite(self, tmp_path,
                                                     monkeypatch):
        """The v4.7 rewrite of live_sources must keep the v4.5 response
        contract byte-stable for existing consumers."""
        client = _client(tmp_path)
        _activate(_store(), "crtsh", "https://crt.sh")
        inv = _make_case(_store())
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp([{"name_value": "www.example.com"}]))
        body = _post(client, inv["id"],
                     path="/api/v1/osint/live/crtsh").json()
        for key in ("investigation_id", "domain", "connector",
                    "observed_total", "names", "truncated", "new_evidence",
                    "newly_linked", "evidence_id", "result_hash",
                    "osint_class", "provenance", "degraded"):
            assert key in body, f"contract key missing: {key}"
        assert body["provenance"]["source"].startswith("crt.sh")


# -------------------------------------------------------------- KPI context --
class TestLiveSourceKpis:
    def test_live_observation_metrics_in_window(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store, "rdap", "https://rdap.org")
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap_payload()))
        _post(client, inv["id"])
        monkeypatch.setattr(
            live_sources, "_http_get",
            lambda u: _Resp(_rdap_payload(registrar="Other Registrar")))
        _post(client, inv["id"])
        iq = kpis.compute_kpis(store)["families"]["intelligence_quality"]
        assert iq["live_observations"]["value"] == 2
        assert iq["observation_changes"]["value"] == 1
        assert iq["observation_changes"]["status"] == "OK"

    def test_hash_is_over_canonical_subset(self):
        """Registrar-of-record fluff must not flip the detector: two payloads
        differing ONLY in unobserved fields produce the same hash."""
        a = _rdap_payload()
        b = _rdap_payload()
        b["ldhName"] = "EXAMPLE.COM"          # unobserved display field
        b["handle"] = "12345_DOMAIN"
        pa = live_sources.fetch_rdap_domain(
            "example.com", http_get=lambda u: _Resp(a))["result_payload"]
        pb = live_sources.fetch_rdap_domain(
            "example.com", http_get=lambda u: _Resp(b))["result_payload"]
        ha = hashlib.sha256(json.dumps(pa, sort_keys=True).encode()).hexdigest()
        hb = hashlib.sha256(json.dumps(pb, sort_keys=True).encode()).hexdigest()
        assert ha == hb
