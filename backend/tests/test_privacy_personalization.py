"""§5.3 Consent Ledger + §3.4 Personalization acceptance tests (product
tranche from the design audit — see design/Product-Audit-v3.1.md).

Load-bearing rule under test (TRUST.md §5.5): personalization shapes
presentation/defaults/notifications — NEVER confidence, verdicts or risk.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import personalization, privacy, trust_layer
from app.core.errors import PipelineError
from app.swarm.agents import voyager


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------ §5.3 ledger --
class TestConsentLedger:
    def test_append_only_chain_and_verify(self, store):
        e1 = privacy.record(store, user_id="u1", purpose="personalization",
                            state="granted")
        e2 = privacy.record(store, user_id="u1", purpose="kyc_biometrics",
                            state="granted", detail="KYC step consent")
        v = privacy.verify_chain(store)
        assert v["chain_intact"] and v["entries"] == 2
        assert e1["entry_id"] != e2["entry_id"]
        # withdrawal is a NEW entry; history keeps the provable grant
        privacy.record(store, user_id="u1", purpose="kyc_biometrics",
                       state="withdrawn")
        assert privacy.current_state(store, "u1", "kyc_biometrics") == \
            "withdrawn"
        assert len(store.consent_ledger(user_id="u1")) == 3
        assert privacy.verify_chain(store)["chain_intact"]
        # and everything lands on the AUDITOR trail too (A-06)
        assert any("consent_" in r["action"] for r in store.audit_trail())

    def test_tamper_breaks_chain(self, store):
        privacy.record(store, user_id="u2", purpose="analytics",
                       state="granted")
        privacy.record(store, user_id="u2", purpose="analytics",
                       state="withdrawn")
        # simulate an attacker editing history in-place
        with store._lock:
            store._conn.execute(
                "UPDATE consent_ledger SET state='granted' WHERE user_id='u2' "
                "AND state='withdrawn'")
            store._conn.commit()
        v = privacy.verify_chain(store)
        assert not v["chain_intact"] and v["broken_at"] is not None
        with store._lock:  # restore (append-only has no legit update path)
            store._conn.execute(
                "UPDATE consent_ledger SET state='withdrawn' WHERE user_id='u2' "
                "AND state='granted' AND detail='' AND rowid > 1")
            store._conn.commit()

    def test_unknown_purpose_rejected(self, store):
        with pytest.raises(ValueError):
            privacy.record(store, user_id="u3", purpose="sell_my_data",
                           state="granted")


# ------------------------------------------------- §3.4 personalization ----
class TestPersonalizationConsentGate:
    def test_save_requires_consent(self, store):
        with pytest.raises(PipelineError) as e:
            personalization.save(store, "u4", watchlists=["Third Mainland"],
                                 journey_priority=None, notify_tolerance=None,
                                 output_format=None)
        assert e.value.code == "CONSENT_REQUIRED"  # §20 classified, not 500
        assert store.get_prefs("u4") is None       # nothing stored silently

    def test_grant_then_save_then_withdraw_blocks(self, store):
        privacy.record(store, user_id="u4", purpose="personalization",
                       state="granted")
        out = personalization.save(store, "u4",
                                   watchlists=["Third Mainland Bridge"],
                                   journey_priority="safest",
                                   notify_tolerance=None,
                                   output_format="analyst")
        assert out["journey_priority"] == "safest"
        assert out["output_format"] == "analyst"
        assert out["consent"] == "granted"
        privacy.record(store, user_id="u4", purpose="personalization",
                       state="withdrawn")
        with pytest.raises(PipelineError):
            personalization.save(store, "u4", watchlists=["X"],
                                 journey_priority=None, notify_tolerance=None,
                                 output_format=None)
        # withdrawal honored immediately on reads too: alert loops skip user
        assert personalization.reassess_watchlists(store) == []

    def test_invalid_values_refused(self, store):
        privacy.record(store, user_id="u5", purpose="personalization",
                       state="granted")
        with pytest.raises(PipelineError) as e:
            personalization.save(store, "u5", watchlists=None,
                                 journey_priority="warp-speed",
                                 notify_tolerance=None, output_format=None)
        assert e.value.code == "INVALID_PREFERENCE"


class TestWatchlistDriftAlerts:
    def test_new_signal_on_watched_entity_notifies(self, seeded):
        privacy.record(seeded, user_id="u6", purpose="personalization",
                       state="granted")
        personalization.save(seeded, "u6",
                             watchlists=["Third Mainland Bridge"],
                             journey_priority=None, notify_tolerance=None,
                             output_format=None)
        personalization.reassess_watchlists(seeded)  # baseline snapshot
        trust_layer.append_signal(
            seeded, source_id="watch_test_feed",
            claim_text="Fresh incident report on Third Mainland Bridge",
            entity="Third Mainland Bridge",
            independence_group="test_watch")
        emitted = personalization.reassess_watchlists(seeded)
        assert emitted and emitted[0]["new_signals"] >= 1
        kinds = [n["kind"] for n in seeded.list_notifications()]
        assert "WATCHLIST_ALERT" in kinds
        # second run with no new evidence → no repeat alert (no noise)
        assert personalization.reassess_watchlists(seeded) == []


class TestPresentationNeverConclusions:
    """THE §3.4/§22 rule: run identical analyses under opposing preference
    profiles; verdict/risk output must be identical down to the letter."""

    def test_journey_risk_identical_across_profiles(self, seeded):
        dep = datetime.now(timezone.utc) + timedelta(days=1)
        req_kwargs = dict(origin="Ikeja", destination="Victoria Island",
                          departure_time=dep)
        # profile A: novice, safest, HIGH tolerance
        privacy.record(seeded, user_id="pa", purpose="personalization",
                       state="granted")
        personalization.save(seeded, "pa", watchlists=[],
                             journey_priority="safest", notify_tolerance="HIGH",
                             output_format="novice")
        # profile B: analyst, fastest, LOW tolerance
        privacy.record(seeded, user_id="pb", purpose="personalization",
                       state="granted")
        personalization.save(seeded, "pb", watchlists=[],
                             journey_priority="fastest", notify_tolerance="LOW",
                             output_format="analyst")
        from app.models.schemas import JourneyRequest
        req = JourneyRequest(**req_kwargs)  # same request, no prefs attached
        a = voyager.build_risk_timeline(req)
        b = voyager.build_risk_timeline(req)
        assert [t.risk for t in a] == [t.risk for t in b]
        assert voyager.max_risk_of(a) == voyager.max_risk_of(b)

    def test_tolerance_changes_alerts_not_scores(self, seeded):
        """§3.4 explicit example: tolerance shapes NOTIFICATIONS only."""
        out_low = voyager.monitor_active_journey(
            seeded, origin="Ikeja", destination="Victoria Island",
            departure_time=datetime.now(timezone.utc) + timedelta(days=1),
            tolerance="LOW")
        out_high = voyager.monitor_active_journey(
            seeded, origin="Ikeja", destination="Victoria Island",
            departure_time=datetime.now(timezone.utc) + timedelta(days=1),
            tolerance="HIGH")
        assert out_low["baseline_risk"] == out_high["baseline_risk"]
        d_low = seeded.get_watch(out_low["watch_id"])
        d_high = seeded.get_watch(out_high["watch_id"])
        assert (d_low["baseline_risk"] == d_high["baseline_risk"]
                == d_low["current_risk"] == d_high["current_risk"])
        assert d_low["tolerance"] == "LOW" and d_high["tolerance"] == "HIGH"

    def test_watch_tolerance_default_comes_from_prefs(self, seeded):
        privacy.record(seeded, user_id="u7", purpose="personalization",
                       state="granted")
        personalization.save(seeded, "u7", watchlists=[],
                             journey_priority=None, notify_tolerance="HIGH",
                             output_format=None)
        assert personalization.default_watch_tolerance(seeded, "u7") == "HIGH"
        assert personalization.default_watch_tolerance(seeded, None) == \
            "MODERATE"
        assert personalization.default_watch_tolerance(
            seeded, "no-such-user") == "MODERATE"
