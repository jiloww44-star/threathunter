"""Safety-by-design primitives — v3.2 UX review (checklist J + blockers).

Single place for safety events so the learning loop stays honest: events
are written onto the AUDITOR trail (`safety_event:<name>`) — one source of
truth, no shadow counters. `/api/v1/ops/kpis` exposes the counts.

Disclaimer text is the review's hard requirement (risk 2/5/7): every AI
report must visibly carry it.
"""
from __future__ import annotations

from ..store.db import EvidenceStore
from .registry import POLICY_VERSION

# Every AI-generated artifact prepends this (review §F/risks 2,5,7 + flow
# improvement #4). Kept short so it survives every surface.
AI_DISCLAIMER = ("AI-generated output — verify all findings and "
                 "recommendations with your team's protocols before taking "
                 "action.")


def log_event(store: EvidenceStore, event: str, *, actor: str,
              detail: str) -> None:
    """Safety learning loop (checklist J). Named events (keep closed set):
    halt_requested · plan_approved · plan_rejected · incident_declared ·
    ethics_flag · pii_masked · tree_deleted · user_data_deleted ·
    crisis_signal_detected (v3.4)"""
    store.audit(actor=actor, action=f"safety_event:{event}",
                decision="ALLOW", detail=detail,
                policy_version=POLICY_VERSION)
