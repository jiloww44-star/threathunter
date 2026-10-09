"""v3.4 hardening tests — red-team review deferrals #3 (cortex crisis-signal
detection) and #9 (region-aware consent defaults).

Both features obey the standing rules: crisis detection *surfaces a real
pathway* (never fakes a response), suppression prevents drills paging the
on-call; region defaults never override an explicit ledger decision and
biometrics stay opt-in in every region.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.swarm import cortex                                  # noqa: E402
from app.core import personalization, privacy                 # noqa: E402
from app.core.errors import PipelineError                     # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------ red-team #3 --
class TestCrisisDetection:
    @pytest.mark.parametrize("text", [
        "We are under attack right now",
        "HELP — systems are down and we are under attack",
        "we've been breached, what do we do",
        "ransomware hit our file server",
        "customer data is being exfiltrated as we speak",
    ])
    def test_live_phrases_detected(self, text):
        assert cortex.detect_crisis(text) is not None

    @pytest.mark.parametrize("text", [
        "hypothetically, what if we've been breached in the drill tomorrow",
        "tabletop scenario: ransomware hit our file server",
        "run a routine check for data leaks on our domain",
        "is acme-parcels.xyz breached? check for breach exposure",
        "hello",
    ])
    def test_benign_and_intel_language_not_detected(self, text):
        assert cortex.detect_crisis(text) is None

    def test_chat_surfaces_real_pathway(self, store):
        r = run(cortex.chat(store, "sess-c1", "we are under attack, help"))
        assert r["crisis"]["action"] == "declare_incident"
        assert "Crisis Override" in r["text"]
        # the conversation still runs — crisis assist, not a dead end
        assert len(r["text"]) > 200

    def test_safety_event_logged_once_per_session(self, store):
        run(cortex.chat(store, "sess-c2", "we've been hacked"))
        run(cortex.chat(store, "sess-c2", "systems are down again"))
        counts = store.safety_event_counts()
        assert counts.get("crisis_signal_detected", 0) == 1

    def test_drill_does_not_page(self, store):
        r = run(cortex.chat(store, "sess-c3",
                            "what if we've been hacked — tabletop scenario"))
        assert "crisis" not in r
        assert "crisis_signal_detected" not in store.safety_event_counts()


# ------------------------------------------------------------ red-team #9 --
class TestRegionDefaults:
    def test_unknown_region_rejected(self, store):
        with pytest.raises(ValueError):
            privacy.set_region(store, "u1", "ATLANTIS")

    def test_default_region_is_global_optin(self, store):
        eff = privacy.effective_consent(store, "u1", "personalization")
        assert eff["state"] == "withdrawn"
        assert eff["origin"] == "region_default"
        assert eff["region"] == "GLOBAL"

    def test_optout_region_soft_grants(self, store):
        privacy.set_region(store, "u1", "US")
        eff = privacy.effective_consent(store, "u1", "personalization")
        assert eff["state"] == "granted"
        assert eff["origin"] == "region_default"

    def test_biometrics_optin_everywhere(self, store):
        for region in privacy.REGIONS:
            privacy.set_region(store, "u1", region)
            eff = privacy.effective_consent(store, "u1", "kyc_biometrics")
            assert eff["state"] == "withdrawn", region

    def test_ledger_overrides_region_default(self, store):
        privacy.set_region(store, "u1", "US")  # soft-grants personalization
        privacy.record(store, user_id="u1", purpose="personalization",
                       state="withdrawn")
        eff = privacy.effective_consent(store, "u1", "personalization")
        assert eff["state"] == "withdrawn" and eff["origin"] == "ledger"

    def test_region_default_unlocks_personalization_save(self, store):
        """Opt-out region: saving prefs without an explicit ledger grant is
        allowed (documented soft default). GLOBAL keeps the hard gate."""
        privacy.set_region(store, "u1", "US")
        out = personalization.save(store, "u1", watchlists=["acme"],
                                   journey_priority=None,
                                   notify_tolerance=None, output_format=None)
        assert out["watchlists"] == ["acme"]
        privacy.set_region(store, "u2", "GLOBAL")
        with pytest.raises(PipelineError):
            personalization.save(store, "u2", watchlists=["acme"],
                                 journey_priority=None, notify_tolerance=None,
                                 output_format=None)

    def test_withdrawal_immediately_blocks_save(self, store):
        privacy.set_region(store, "u1", "US")
        personalization.save(store, "u1", watchlists=["acme"],
                             journey_priority=None, notify_tolerance=None,
                             output_format=None)
        privacy.record(store, user_id="u1", purpose="personalization",
                       state="withdrawn")
        with pytest.raises(PipelineError):
            personalization.save(store, "u1", watchlists=["b"],
                                 journey_priority=None, notify_tolerance=None,
                                 output_format=None)


class TestRegionRoutes:
    def test_region_routes(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.store.db import reset_store
        reset_store(str(tmp_path / "rg.db"))
        client = TestClient(app)

        r = client.get("/api/v1/privacy/regions")
        assert r.status_code == 200
        assert "US" in r.json()["regions"]

        r = client.put("/api/v1/privacy/region",
                       json={"user_id": "op-1", "region": "US"})
        assert r.status_code == 200
        assert r.json()["mode"] == "opt-out"

        r = client.put("/api/v1/privacy/region",
                       json={"user_id": "op-1", "region": "MOON"})
        assert r.status_code == 400

        r = client.get("/api/v1/privacy/consent/op-1")
        body = r.json()
        assert body["region"] == "US"
        eff = body["effective"]["personalization"]
        assert eff["state"] == "granted" and eff["origin"] == "region_default"
        assert "not legal advice" in body["region_notice"]
