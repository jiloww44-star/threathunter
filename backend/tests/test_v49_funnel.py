"""v4.9 — EVIDENCE FUNNEL tests (§72 pipeline made visible).

Pins: cumulative-stage counting, honest conversion handling (empty
denominator ⇒ UNAVAILABLE, never a fabricated 0.0), denied attempts
counting as observed (v4.8 design), legacy rows without case ids NOT
counting (honest regression pin), funnel.completed ≡ north-star
(query-consistency), cohort lens filtering, and the read-gated route.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import funnel, investigation, kpis          # noqa: E402
from app.store.db import get_store, reset_store           # noqa: E402


def _store(tmp_path, name="v49.db"):
    reset_store(str(tmp_path / name))
    return get_store()


def _case(store, objective="funnel probe"):
    return investigation.create(
        store, objective=objective, subject_type="domain",
        subject="example.com", purpose="v4.9 funnel tests",
        authority="organization_owned", scope="unit",
            allowed_sources=None, expires_days=7, user_id="t49")


def _by_id(payload, key):
    return {row["id"]: row for row in payload[key]}


class TestStages:
    def test_empty_store_all_zero_conversions_unavailable(self, tmp_path):
        store = _store(tmp_path)
        f = funnel.compute_funnel(store)
        assert {s["id"]: s["value"] for s in f["stages"]} == {
            "opened": 0, "observed": 0, "linked": 0, "closed": 0,
            "completed": 0}
        conv = _by_id(f, "conversions")
        assert all(c["status"] == "UNAVAILABLE" for c in conv.values())
        assert "undefined, not zero" in conv["close_rate"]["basis"]
        assert f["north_star_consistency"]["match"] is True  # 0 == 0

    def test_opened_case_changes_open_and_attempt_rate_becomes_defined(
            self, tmp_path):
        store = _store(tmp_path)
        _case(store)
        f = funnel.compute_funnel(store)
        s = _by_id(f, "stages")
        assert s["opened"]["value"] == 1
        assert s["observed"]["value"] == 0
        conv = _by_id(f, "conversions")
        assert conv["attempt_rate"]["status"] == "OK"
        assert conv["attempt_rate"]["value"] == 0.0          # 0/1 defined
        assert conv["attempt_rate"]["sample"] == 1
        # but the headline still has no denominator — honest UNAVAILABLE
        assert conv["evidence_backed_completion"]["status"] == "UNAVAILABLE"

    def test_denied_attempt_counts_as_observed(self, tmp_path):
        """v4.8 design: a DENIED governed attempt is still operator behavior
        and the audit detail carries the case id — so it registers."""
        store = _store(tmp_path)
        inv = _case(store)
        store.audit(actor="agent:live-sources", action="event:SourceQueried",
                    decision="DENY",
                    detail=(f"rdap fetch for example.com on {inv['id']} "
                            "failed classified SOURCE_UNREACHABLE: …"),
                    policy_version="policy-engine/4.2.0")
        f = funnel.compute_funnel(store)
        assert _by_id(f, "stages")["observed"]["value"] == 1
        assert _by_id(f, "conversions")["attempt_rate"]["value"] == 1.0

    def test_legacy_row_without_case_id_does_not_count(self, tmp_path):
        """Honest regression pin: pre-v4.8 DENY rows lacked the case id —
        the funnel must NOT claim attempts it cannot attribute."""
        store = _store(tmp_path)
        _case(store)
        store.audit(actor="agent:live-sources", action="event:SourceQueried",
                    decision="DENY",
                    detail="rdap fetch for example.com failed classified "
                           "SOURCE_UNREACHABLE (no case id — legacy row)",
                    policy_version="policy-engine/4.2.0")
        assert _by_id(funnel.compute_funnel(store),
                      "stages")["observed"]["value"] == 0


class TestCompletion:
    def test_link_and_close_pipeline(self, tmp_path):
        store = _store(tmp_path)
        inv = _case(store)
        f0 = funnel.compute_funnel(store)
        assert _by_id(f0, "stages")["completed"]["value"] == 0

        store.inv_link("lk1", inv["id"], "evidence", "ev-123")
        f1 = funnel.compute_funnel(store)
        s1 = _by_id(f1, "stages")
        assert s1["linked"]["value"] == 1
        assert s1["completed"]["value"] == 0   # linked but NOT closed

        investigation.close(store, inv["id"], actor="t49", reason="done")
        f2 = funnel.compute_funnel(store)
        s2 = _by_id(f2, "stages")
        conv2 = _by_id(f2, "conversions")
        assert s2["closed"]["value"] == 1
        assert s2["completed"]["value"] == 1
        assert conv2["evidence_backed_completion"]["value"] == 1.0
        assert conv2["evidence_backed_completion"]["sample"] == 1

    def test_closed_without_evidence_is_not_completed(self, tmp_path):
        store = _store(tmp_path)
        inv = _case(store)
        investigation.close(store, inv["id"], actor="t49", reason="dry hole")
        f = funnel.compute_funnel(store)
        s = _by_id(f, "stages")
        assert s["closed"]["value"] == 1
        assert s["completed"]["value"] == 0
        conv = _by_id(f, "conversions")
        assert conv["evidence_backed_completion"]["value"] == 0.0
        assert conv["evidence_backed_completion"]["status"] == "OK"

    def test_completed_equals_north_star_numerator(self, tmp_path):
        """Query-consistency: funnel.completed MUST equal kpis' §72 north-
        star across a mixed state — a mismatch is a defect, not a nuance."""
        store = _store(tmp_path)
        a, b, c = _case(store, "a"), _case(store, "b"), _case(store, "c")
        store.inv_link("lk-a", a["id"], "evidence", "e1")
        store.inv_link("lk-b", b["id"], "watch", "w1")      # wrong kind
        investigation.close(store, a["id"], actor="t", reason="done")
        investigation.close(store, b["id"], actor="t", reason="done")
        # c stays open with a link — must not count as completed
        store.inv_link("lk-c", c["id"], "evidence", "e3")

        f = funnel.compute_funnel(store)
        ns = kpis._north_star(store)["value"]
        s = _by_id(f, "stages")
        assert s["opened"]["value"] == 3
        assert s["linked"]["value"] == 2       # a + c (watch link is not evidence)
        assert s["closed"]["value"] == 2
        assert s["completed"]["value"] == 1
        assert ns == 1
        assert f["north_star_consistency"] == {
            "funnel_completed": 1, "kpis_north_star": 1, "match": True,
            "basis": f["north_star_consistency"]["basis"]}

    def test_cohort_lens_filters_and_drops_consistency_claim(self, tmp_path):
        store = _store(tmp_path)
        _case(store)
        cohort = funnel.compute_funnel(store, window_hours=1)
        assert cohort["lens"].startswith("COHORT")
        assert cohort["north_star_consistency"] is None  # ns is all-time
        assert _by_id(cohort, "stages")["opened"]["value"] == 1
        zero = funnel.compute_funnel(store, window_hours=0)
        assert _by_id(zero, "stages")["opened"]["value"] == 0


class TestRoute:
    def test_funnel_endpoint_shape(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "v49api.db"))
        client = TestClient(app)
        resp = client.get("/api/v1/ops/funnel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["funnel_version"] == "funnel-engine/4.9.0"
        assert [s["id"] for s in body["stages"]] == [
            "opened", "observed", "linked", "closed", "completed"]
        assert {c["id"] for c in body["conversions"]} == {
            "attempt_rate", "link_rate", "close_rate",
            "evidence_backed_completion"}
        assert body["north_star_consistency"]["match"] is True
        for stage in body["stages"]:
            assert stage["basis"]                      # §20 measured-or-said
        assert body["notes"]

    def test_funnel_endpoint_cohort_param(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "v49api2.db"))
        client = TestClient(app)
        resp = client.get("/api/v1/ops/funnel", params={"window_hours": 24})
        assert resp.status_code == 200
        assert resp.json()["lens"].startswith("COHORT")
