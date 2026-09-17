"""v4.1 — FORENSICS & EVIDENCE FABRIC tests (§73 V1.5 + V1 leftovers).

Covers: dork builder (spec storage shape + why/expected/boundaries +
generation-only + passive-first), A-04 media forensics route, the
investigation graph (§5 chain as nodes/edges), and the Evidence Locker.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import dork_builder, investigation                    # noqa: E402
from app.core.errors import PipelineError                           # noqa: E402
from app.store.db import reset_store                                # noqa: E402


def _client(tmp_path, name="v41.db", seed=False):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.store.db import get_store
    reset_store(str(tmp_path / name))
    if seed:
        # same explicit demo-pack ingest pattern as tests/test_api.py
        import asyncio
        from app.scraper.orchestrator import load_sources, run_pipeline
        asyncio.run(run_pipeline(get_store(), load_sources()))
    return TestClient(app)


# ---------------------------------------------------------- dork builder ----
class TestDorkBuilder:
    def test_spec_storage_shape(self):
        out = dork_builder.build_dorks("assess exposure", "example.ng")
        assert out["count"] == len(out["dorks"]) > 0
        for d in out["dorks"]:
            # exact spec fields
            for k in ("objective", "search_engine", "syntax", "intended_use",
                      "risk_level", "authorized_scope", "source",
                      "last_verified"):
                assert k in d, k
            # + the spec's explanation requirement
            assert d["why"] and d["expected_results"] and d["boundaries"]

    def test_generation_only_never_execution(self):
        out = dork_builder.build_dorks("assess", "example.ng")
        assert "never executed" in out["execution_note"]
        assert all(d["risk_level"] == "PASSIVE" for d in out["dorks"])
        assert "Passive-first" in out["passive_first"]

    def test_subject_substitution(self):
        out = dork_builder.build_dorks("assess", "example.ng")
        assert any("site:example.ng" in d["syntax"] for d in out["dorks"])

    def test_unknown_subject_type_degrades_honestly(self):
        out = dork_builder.build_dorks("assess", "thing",
                                       subject_type="galaxy")
        assert out["degraded_note"] and "baseline" in out["degraded_note"]

    def test_unknown_engine_defaults_disclosed(self):
        out = dork_builder.build_dorks("assess", "x.ng",
                                       search_engine="altavista")
        assert out["dorks"][0]["search_engine"] == "google"
        assert "disclosed" in out["degraded_note"]

    def test_route_basic(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/osint/dorks", json={
            "objective": "quarterly exposure sweep", "subject": "example.ng"})
        assert r.status_code == 200
        assert r.json()["count"] >= 3

    def test_route_binds_case_scope_and_audits(self, tmp_path):
        client = _client(tmp_path)
        inv = client.post("/api/v1/investigations", json={
            "objective": "domain watch", "subject_type": "domain",
            "subject": "example.ng", "purpose": "owned asset",
            "authority": "organization_owned", "scope": "passive only",
            "user_id": "u"}).json()
        r = client.post("/api/v1/osint/dorks", json={
            "objective": "exposure sweep", "subject": "example.ng",
            "investigation_id": inv["id"]})
        assert r.status_code == 200
        assert all(d["authorized_scope"] == "passive only"
                   for d in r.json()["dorks"])
        assert r.json()["investigation_id"] == inv["id"]

    def test_route_refuses_closed_case(self, tmp_path):
        client = _client(tmp_path)
        inv = client.post("/api/v1/investigations", json={
            "objective": "domain watch", "subject_type": "domain",
            "subject": "example.ng", "purpose": "owned asset",
            "authority": "organization_owned", "user_id": "u"}).json()
        client.post(f"/api/v1/investigations/{inv['id']}/close",
                    json={"reason": "done"})
        r = client.post("/api/v1/osint/dorks", json={
            "objective": "exposure sweep", "subject": "example.ng",
            "investigation_id": inv["id"]})
        assert r.status_code == 403  # §76 — even generation, in a case's name


# ------------------------------------------------- media forensics (A-04) ---
class TestMediaForensics:
    def test_fixture_pass(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/osint/forensics/media",
                        json={"media_ref": "mock:pass"})
        assert r.status_code == 200
        body = r.json()
        assert body["assessment"] == "LIKELY_AUTHENTIC"
        assert body["trust_label"] == "EVIDENCE"

    def test_unrecognizable_never_fake(self, tmp_path):
        client = _client(tmp_path)
        r = client.post("/api/v1/osint/forensics/media",
                        json={"media_ref": "unknown-blob"})
        body = r.json()
        assert body["assessment"] == "UNVERIFIED"   # §1.9
        assert body["confidence"] == "UNDETERMINED"

    def test_link_to_investigation(self, tmp_path):
        client = _client(tmp_path)
        inv = client.post("/api/v1/investigations", json={
            "objective": "verify shared media", "subject_type": "url",
            "subject": "https://cdn.social/img/1.jpg",
            "purpose": "public research", "authority": "public_research",
            "user_id": "u"}).json()
        client.post("/api/v1/osint/forensics/media",
                    json={"media_ref": "mock:spoof",
                          "link_to_investigation": inv["id"]})
        links = client.get(f"/api/v1/investigations/{inv['id']}").json()["links"]
        assert any(l["kind"] == "evidence" and "media:" in l["ref_id"]
                   for l in links)


# ---------------------------------------------------- investigation graph ---
class TestInvestigationGraph:
    def test_chain_nodes_and_edges(self, store):
        inv = investigation.create(
            store, objective="chain demo", subject_type="domain",
            subject="example.ng", purpose="owned asset",
            authority="organization_owned", scope="",
            allowed_sources=None, expires_days=10, user_id="u")
        from app.swarm.pathfinder import propose_plan
        p = propose_plan("plan travel from Lagos to Abuja", store,
                         investigation_id=inv["id"])
        g = investigation.graph(store, inv["id"])
        types = {n["type"] for n in g["nodes"]}
        assert "Investigation" in types and "Tree" in types
        assert any(e["type"] == "HAS_TASK" for e in g["edges"])
        assert any(n["provenance"].get("link_created_at")
                   for n in g["nodes"] if n["type"] == "Tree")
        inv_node = next(n for n in g["nodes"] if n["type"] == "Investigation")
        assert inv_node["provenance"]["authority"] == "organization_owned"
        assert p["investigation_id"] == inv["id"]

    def test_removed_tree_link_retained_as_note(self, store):
        inv = investigation.create(
            store, objective="unlink demo", subject_type="domain",
            subject="example.ng", purpose="owned asset",
            authority="organization_owned", scope="",
            allowed_sources=None, expires_days=10, user_id="u")
        investigation.link(store, inv["id"], "ops_tree", "ghost-tree",
                           actor="u")
        g = investigation.graph(store, inv["id"])
        tree_node = next(n for n in g["nodes"] if n["type"] == "Tree")
        assert "removed" in tree_node["label"]
        assert "§26" in tree_node["provenance"]["note"]

    def test_unknown_404(self, store):
        with pytest.raises(PipelineError) as e:
            investigation.graph(store, "nope")
        assert e.value.status == 404

    def test_graph_route_shape(self, tmp_path):
        client = _client(tmp_path, seed=True)
        ev = client.get("/api/v1/feed/recent").json()
        inv = client.post("/api/v1/investigations", json={
            "objective": "graph route", "subject_type": "claim",
            "subject": "demo claim", "purpose": "public research",
            "authority": "public_research", "user_id": "u"}).json()
        # link a real evidence id from the seeded store
        any_ev = client.get("/api/v1/evidence/locker").json()["items"][0]
        client.post(f"/api/v1/investigations/{inv['id']}/link",
                    json={"kind": "evidence", "ref_id": any_ev["id"]})
        r = client.get(f"/api/v1/investigations/{inv['id']}/graph")
        assert r.status_code == 200
        g = r.json()
        assert {n["type"] for n in g["nodes"]} >= {"Investigation",
                                                   "Evidence"}
        assert any(e["type"] == "LINKED_TO" for e in g["edges"])
        assert ev is not None


# ------------------------------------------------------ evidence locker -----
class TestEvidenceLocker:
    def test_provenance_first_rows(self, tmp_path):
        client = _client(tmp_path, seed=True)
        r = client.get("/api/v1/evidence/locker")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] > 0
        for it in body["items"][:5]:
            assert it["source_id"] and it["authority"] and it["fetched_at"]

    def test_search_and_source_filter(self, tmp_path):
        client = _client(tmp_path, seed=True)
        all_items = client.get("/api/v1/evidence/locker").json()["items"]
        src = all_items[0]["source_id"]
        f = client.get(f"/api/v1/evidence/locker?source={src}").json()
        assert f["count"] > 0
        assert all(src in i["source_id"] for i in f["items"])
        q = all_items[0]["title"].split()[0]
        fq = client.get(f"/api/v1/evidence/locker?q={q}").json()
        assert fq["count"] >= 1

    def test_limit_clamped(self, tmp_path):
        client = _client(tmp_path, seed=True)
        r = client.get("/api/v1/evidence/locker?limit=9999")
        assert r.json()["count"] <= 200
