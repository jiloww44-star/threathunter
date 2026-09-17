"""Source-health state mapping — v4.0 §6/§32 vocabulary, shared core.

Lives in core (not routes) so the assurance loop (v4.3) and the feed
monitor compute the SAME lifecycle states from the same rules — one
deterministic mapping (§54), two consumers.
"""
from __future__ import annotations

SOURCE_HEALTH_STATES = ("ACTIVE", "DEGRADED", "AUTH_REQUIRED",
                        "SCHEMA_CHANGED", "DEPRECATED", "UNAVAILABLE")


def health_state(meta: dict) -> str:
    """Deterministic mapping from a sources_meta row to the §6/§32 state."""
    note = (meta.get("health_note") or "").upper()
    if "DEPRECATED" in note:
        return "DEPRECATED"
    if "SCHEMA" in note:
        return "SCHEMA_CHANGED"
    if "AUTH" in note or "401" in note or "403" in note:
        return "AUTH_REQUIRED"
    score = meta.get("health_score")
    if score is None:
        # no scorecard yet — judge only by last outcome (§20 honesty)
        return "ACTIVE" if meta.get("last_success_at") else "DEGRADED"
    if score < 0.4:
        return "UNAVAILABLE"
    if score < 0.7:
        return "DEGRADED"
    return "ACTIVE"
