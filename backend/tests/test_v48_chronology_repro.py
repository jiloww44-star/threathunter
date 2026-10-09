"""v4.8 — CHRONOLOGY & REPRODUCIBILITY tests (§67 + §68 closure).

§67: the case chronology is derived from the permanent trail, ordered,
kinded, and committed by a recomputable digest — tamper with the trail and
the digest tells on you.
§68: "Re-run investigation" replays a recorded observation from its own
stored provenance tuple and reports UNCHANGED or CHANGED; replays obey the
same §76/§80 gates as the original (no resurrecting closed cases or
retired connectors).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import approvals, chronology, connectors, investigation  # noqa: E402
from app.core import live_sources                                     # noqa: E402
from app.core.errors import PipelineError                             # noqa: E402
from app.store.db import get_store, reset_store                      # noqa: E402


def _client(tmp_path, name="v48.db"):
    from fastapi.testclient import TestClient
    from app.main import app
    reset_store(str(tmp_path / name))
    return TestClient(app)


def _store():
    return get_store()


def _make_case(store):
    return investigation.create(
        store, objective="Surface mapping", subject_type="domain",
        subject="example.com", purpose="pilot",
        authority="organization_owned", scope="passive",
        allowed_sources=None, expires_days=7, user_id="pilot")


def _activate(store, name="rdap", base_url="https://rdap.org"):
    row = connectors.register(store, name=name, kind="C_data_api",
                              base_url=base_url, auth_env=None, actor="admin")
    approvals.decide(store, row["approval"]["id"], approved=True,
                     decided_by="gov")
    return row["id"]


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


def _rdap(registrar="Example Registrar, Inc."):
    return {
        "objectClassName": "domain", "rdapConformance": ["rdap_level_0"],
        "entities": [{"roles": ["registrar"],
                      "vcardArray": ["vcard", [["fn", {}, "text",
                                                  registrar]]]}],
        "nameservers": [{"ldhName": "a.iana-servers.net"}],
        "status": ["active"],
        "events": [{"eventAction": "registration",
                    "eventDate": "1995-08-14T04:00:00Z"}],
    }


def _observe(client, inv_id, domain="example.com"):
    return client.post("/api/v1/osint/live/rdap", json={
        "investigation_id": inv_id, "domain": domain})


# ------------------------------------------------------------- chronology --
class TestChronology:
    def test_derived_ordered_and_digest_stable(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store)
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap()))
        _observe(client, inv["id"])
        r = client.get(f"/api/v1/investigations/{inv['id']}/chronology")
        assert r.status_code == 200
        body = r.json()
        assert body["event_count"] >= 4
        ats = [e["at"] for e in body["events"]]
        assert ats == sorted(ats)
        kinds = {e["kind"] for e in body["events"]}
        assert "LIFECYCLE" in kinds and "OBSERVATION" in kinds
        assert any(e["action"] == "case:Opened" for e in body["events"])
        assert any(e["action"] == "event:ObservationReceived"
                   for e in body["events"])
        # digest is deterministic on read — recomputing changes nothing
        again = client.get(
            f"/api/v1/investigations/{inv['id']}/chronology").json()
        assert again["digest"] == body["digest"]

    def test_digest_moves_with_history(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store)
        d1 = chronology.build_chronology(store, inv["id"])["digest"]
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap()))
        _observe(client, inv["id"])
        d2 = chronology.build_chronology(store, inv["id"])["digest"]
        assert d1 != d2

    def test_tamper_is_visible_in_digest(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store)
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap()))
        _observe(client, inv["id"])
        before = chronology.build_chronology(store, inv["id"])["digest"]
        # an attacker quietly edits one audit row
        with store._lock:
            store._conn.execute(
                "UPDATE audit_trail SET detail='nothing happened' "
                "WHERE action='event:ObservationReceived'")
            store._conn.commit()
        after = chronology.build_chronology(store, inv["id"])["digest"]
        assert after != before
        assert after != "GENESIS"

    def test_missing_case_404(self, tmp_path):
        client = _client(tmp_path)
        assert client.get("/api/v1/investigations/nope/chronology"
                          ).status_code == 404

    def test_derivation_note_states_scoping(self, tmp_path):
        _client(tmp_path)
        inv = _make_case(_store())
        body = chronology.build_chronology(_store(), inv["id"])
        assert "permanent audit trail" in body["derivation"]
        assert "not padded" in body["derivation"]

    def test_failed_attempts_belong_to_the_case_chronology(self, tmp_path,
                                                           monkeypatch):
        """Caught live: a DENIED SourceQueried must appear on the case's
        chronology — an auditor sees failed attempts too, not only wins."""
        import httpx
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store)
        monkeypatch.setattr(
            live_sources, "_http_get",
            lambda u: (_ for _ in ()).throw(httpx.TimeoutException("down")))
        r = _observe(client, inv["id"])
        assert r.status_code == 503
        body = client.get(
            f"/api/v1/investigations/{inv['id']}/chronology").json()
        denials = [e for e in body["events"]
                   if e["action"] == "event:SourceQueried"
                   and e["decision"] == "DENY"]
        assert denials, "denied attempts must be on the case chronology"
        assert inv["id"] in denials[0]["detail"]


# ------------------------------------------------------------ §68 re-run ---
class TestRerun:
    def _setup(self, tmp_path, monkeypatch):
        client = _client(tmp_path)
        store = _store()
        inv = _make_case(store)
        _activate(store)
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap()))
        obs = _observe(client, inv["id"]).json()
        return client, store, inv, obs

    def test_unchanged_replay_is_honest_noop(self, tmp_path, monkeypatch):
        client, store, inv, obs = self._setup(tmp_path, monkeypatch)
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": obs["evidence_id"]})
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] == "UNCHANGED"
        assert body["new_evidence"] is False
        assert body["re_run"] is True
        assert body["replay_of"] == obs["evidence_id"]
        assert body["result_hash"] == body["previous_hash"]
        # no duplicate row, no change event
        n = store.kpi_sql(
            "SELECT COUNT(*) c FROM evidence WHERE source_id=?",
            ("connector:rdap",))[0]["c"]
        assert n == 1
        assert store.kpi_sql(
            "SELECT COUNT(*) c FROM audit_trail "
            "WHERE action='event:ObservationChanged'")[0]["c"] == 0
        # the replay itself is on the trail (extension, documented)
        actions = [a["action"] for a in store.audit_trail(limit=50)]
        assert "event:ObservationRerun" in actions

    def test_changed_replay_supersedes(self, tmp_path, monkeypatch):
        client, store, inv, obs = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr(live_sources, "_http_get",
                            lambda u: _Resp(_rdap("Hijacked Registrar LLC")))
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": obs["evidence_id"]})
        body = r.json()
        assert body["outcome"] == "CHANGED"
        assert body["changed_from"] == obs["evidence_id"]
        import json as _json
        meta = _json.loads(store.get_evidence(
            body["evidence_id"])["metadata_json"])
        assert meta["supersedes"] == obs["evidence_id"]

    def test_replay_fails_closed_on_dead_case(self, tmp_path, monkeypatch):
        client, store, inv, obs = self._setup(tmp_path, monkeypatch)
        investigation.close(store, inv["id"], actor="pilot")
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": obs["evidence_id"]})
        assert r.status_code == 403
        assert "authorization" in r.json()["meaning"].lower()

    def test_seed_evidence_not_replayable_honest_422(self, tmp_path):
        import asyncio
        client = _client(tmp_path)
        store = _store()
        from app.scraper.orchestrator import load_sources, run_pipeline
        asyncio.run(run_pipeline(store, load_sources()))
        seed_row = store.all_evidence()[0]
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": seed_row["id"]})
        assert r.status_code == 422
        assert r.json()["error_code"] == "REPLAY_NOT_AVAILABLE"
        assert "no recorded live-query provenance" in r.json()["detail"]

    def test_missing_evidence_404(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": "does-not-exist-1"})
        assert r.status_code == 404
        assert r.json()["error_code"] == "EVIDENCE_NOT_FOUND"

    def test_retired_connector_blocks_replay(self, tmp_path, monkeypatch):
        client, store, inv, obs = self._setup(tmp_path, monkeypatch)
        conn = [c for c in store.connector_list() if c["name"] == "rdap"][0]
        store.connector_set_status(conn["id"], "RETIRED")
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": obs["evidence_id"]})
        assert r.status_code == 409
        assert r.json()["error_code"] == "CONNECTOR_NOT_ACTIVE"

    def test_replay_rbac(self, tmp_path, monkeypatch):
        client, store, inv, obs = self._setup(tmp_path, monkeypatch)
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": obs["evidence_id"]},
                        headers={"X-TH360-Role": "viewer"})
        assert r.status_code == 403

    def test_replay_writes_nothing_when_source_down(self, tmp_path,
                                                    monkeypatch):
        """§20 on replays too: a classified fetch failure leaves zero new
        evidence and an honest DENY trail — no zombie half-results."""
        import httpx
        client, store, inv, obs = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr(
            live_sources, "_http_get",
            lambda u: (_ for _ in ()).throw(httpx.TimeoutException("down")))
        before = store.kpi_sql("SELECT COUNT(*) c FROM evidence")[0]["c"]
        r = client.post("/api/v1/osint/live/rerun",
                        json={"evidence_id": obs["evidence_id"]})
        assert r.status_code == 503
        after = store.kpi_sql("SELECT COUNT(*) c FROM evidence")[0]["c"]
        assert after == before
