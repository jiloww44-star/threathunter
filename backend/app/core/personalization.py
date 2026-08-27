"""Adaptive Personalization layer — v3.0 spec §3.4 (P3 exit criterion).

Reinstates v1 §22 WITHIN evidence bounds. Allowed surface:

    watchlists        saved entity watchlists → Trust Layer drift alerts
    journey_priority  default route priority in the UI
    notify_tolerance  default alert threshold for journey watches
    output_format     novice | analyst — default disclosure depth (§19)

THE LOAD-BEARING RULE (TRUST.md §5.5): preferences shape presentation,
defaults and notifications — they NEVER adjust confidence, verdicts, risk
scores or hypothesis weighting. The test suite proves this by running the
same claim/journey under opposing preference profiles and asserting identical
verdict/risk output.

Storage also requires explicit consent (§5.3): saving preferences without a
'personalization' grant on the ledger is refused with a classified §20 error
(CONSENT_REQUIRED), never silently accepted.
"""
from __future__ import annotations

from . import privacy
from ..store.db import EvidenceStore
from .errors import PipelineError

DEFAULTS = {
    "watchlists": [],
    "journey_priority": "balanced",
    "notify_tolerance": "MODERATE",
    "output_format": "novice",
}
_PRIORITIES = ("balanced", "safest", "fastest", "lowest_exposure")
_TOLERANCES = ("LOW", "MODERATE", "HIGH", "CRITICAL")
_FORMATS = ("novice", "analyst")


def get(store: EvidenceStore, user_id: str) -> dict:
    """Preferences for a user, falling back to platform defaults. A consent
    state of anything but 'granted' means defaults only are used — stored
    rows are still returned for transparency + the consent status attached."""
    row = store.get_prefs(user_id)
    consent = privacy.current_state(store, user_id, "personalization")
    if not row:
        return {"user_id": user_id, **DEFAULTS,
                "consent": consent, "source": "defaults"}
    return {"user_id": user_id,
            "watchlists": row["watchlists"],
            "journey_priority": row["journey_priority"],
            "notify_tolerance": row["notify_tolerance"],
            "output_format": row["output_format"],
            "consent": consent, "source": "stored"}


def save(store: EvidenceStore, user_id: str, *, watchlists: list[str] | None,
         journey_priority: str | None, notify_tolerance: str | None,
         output_format: str | None) -> dict:
    """Consent-gated write (§5.3): no effective 'personalization' grant →
    §20-classified CONSENT_REQUIRED. Withdrawn consent always blocks
    (withdrawal is honored immediately). v3.4: the gate reads the EFFECTIVE
    state — an explicit ledger entry wins, else the region default applies
    (e.g. an opt-out region's soft grant), never silently."""
    eff = privacy.effective_consent(store, user_id, "personalization")
    state = eff["state"]
    if state != "granted":
        raise PipelineError(
            "CONSENT_REQUIRED", status=403,
            detail=("storing preferences requires consent to the "
                    f"'personalization' purpose (current: "
                    f"{privacy.current_state(store, user_id, 'personalization')}"
                    f", region default: {eff['region']})"))
    cur = get(store, user_id)
    w = watchlists if watchlists is not None else cur["watchlists"]
    w = [x.strip() for x in w if x and x.strip()][:20]
    jp = journey_priority or cur["journey_priority"]
    nt = notify_tolerance or cur["notify_tolerance"]
    of = output_format or cur["output_format"]
    if jp not in _PRIORITIES:
        raise PipelineError("INVALID_PREFERENCE", status=400,
                            detail=f"journey_priority must be one of {_PRIORITIES}")
    if nt not in _TOLERANCES:
        raise PipelineError("INVALID_PREFERENCE", status=400,
                            detail=f"notify_tolerance must be one of {_TOLERANCES}")
    if of not in _FORMATS:
        raise PipelineError("INVALID_PREFERENCE", status=400,
                            detail=f"output_format must be one of {_FORMATS}")
    # carry the existing watchlist drift state forward; prune removed entities
    prev_state = (store.get_prefs(user_id) or {}).get("watchlist_state", {})
    state_map = {e: prev_state.get(e, 0) for e in w}
    store.upsert_prefs(user_id, watchlists=w, journey_priority=jp,
                       notify_tolerance=nt, output_format=of,
                       watchlist_state=state_map)
    store.audit(actor=user_id, action="save_preferences", decision="ALLOW",
                detail=(f"priority={jp} tolerance={nt} format={of} "
                        f"watchlists={len(w)}"),
                policy_version="sovereign-policy/3.0.0")
    return get(store, user_id)


def default_watch_tolerance(store: EvidenceStore, user_id: str | None) -> str:
    """Journey-watch enrolment default — presentation only (§3.4)."""
    if not user_id:
        return "MODERATE"
    return get(store, user_id)["notify_tolerance"]


def reassess_watchlists(store: EvidenceStore) -> list[dict]:
    """§3.4 + §1.10: for every stored watchlist entity, drift = new signals
    since last check → WATCHLIST_ALERT notification. Read-only over the
    evidence graph; no scoring changes."""
    emitted: list[dict] = []
    seen_users = store.all_prefs()
    for prefs in seen_users:
        if not prefs or not prefs["watchlists"]:
            continue
        if privacy.current_state(store, prefs["user_id"],
                                 "personalization") != "granted":
            continue  # withdrawal honored immediately, everywhere
        state = dict(prefs["watchlist_state"])
        changed = False
        for entity in prefs["watchlists"]:
            count = len(store.search_signals(entity, limit=50))
            prev = state.get(entity)
            state[entity] = count
            if prev is not None and count > prev:
                changed = True
                nid = store.notify(
                    kind="WATCHLIST_ALERT",
                    title=f"New signals on watched entity: {entity}",
                    body=(f"{count - prev} new evidence signal(s) now mention "
                          f"'{entity}' (your saved watchlist). Review them in "
                          f"the evidence graph — watchlists trigger alerts, "
                          f"never verdict changes (§3.4)."),
                    ref=entity)
                emitted.append({"notification_id": nid, "entity": entity,
                                "new_signals": count - prev})
            elif prev is None:
                changed = True  # first sighting snapshot, no alert
        if changed:
            store.update_watchlist_state(prefs["user_id"], state)
    return emitted
