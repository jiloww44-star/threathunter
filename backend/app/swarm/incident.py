"""Functional crisis pathway — v3.2 blocker G (UX review).

"Crisis Override" must DO something: an Incident Declaration records the
SEV, notifies the notification center, lands on the AUDITOR trail + safety
learning loop, and attempts real external delivery via
TH360_INCIDENT_WEBHOOK (PagerDuty/Slack-style hook). Delivery outcome is
always reported honestly (§20): configured/delivered/unreachable/
not_configured — a cosmetic button is worse than no button.
"""
from __future__ import annotations

import os
import uuid

from ..store.db import EvidenceStore
from . import safety

SEVERITIES = ("SEV1", "SEV2", "SEV3")

# Crisis-mode UI checklist (flow improvement: crisis SIMPLIFIES the
# interface; it must never accelerate feeds or crank red for its own sake).
RESPONSE_CHECKLIST = [
    "Confirm the incident is real and scoped (what systems, what data).",
    "Notify your on-call lead via your primary channel NOW.",
    "Preserve evidence — do not wipe logs or rebuild hosts yet.",
    "Isolate affected segments only per your team's runbook.",
    "Record a timeline: detection time, actions taken, decisions made.",
    "Do not execute AI-suggested remediation without human review.",
]

# Guidance surfaced wherever crisis mode renders (declare response AND the
# active-incident poll, so restored sessions see the same contract).
UI_GUIDANCE = ("Crisis mode simplifies the interface — essential checklist "
               "only, reduced motion, no feed acceleration (review risk "
               "#10). This checklist is guidance, not a substitute for your "
               "team's runbook.")


async def declare(store: EvidenceStore, *, severity: str, summary: str,
                  declared_by: str) -> dict:
    if severity not in SEVERITIES:
        from ..core.errors import PipelineError
        raise PipelineError("INVALID_SEVERITY", status=400,
                            detail=f"severity must be one of {SEVERITIES}")
    incident_id = str(uuid.uuid4())[:12]

    delivery: dict
    hook = os.getenv("TH360_INCIDENT_WEBHOOK", "").strip()
    if hook:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.post(hook, json={
                    "incident_id": incident_id, "severity": severity,
                    "summary": summary, "declared_by": declared_by,
                    "source": "threathunter360"})
            delivery = {"state": "delivered" if r.status_code < 300
                        else "unreachable",
                        "status_code": r.status_code,
                        "channel": "webhook"}
        except Exception as e:
            delivery = {"state": "unreachable", "channel": "webhook",
                        "classified_error": "SOURCE_UNAVAILABLE",
                        "note": f"webhook call failed: {str(e)[:120]}"}
    else:
        delivery = {
            "state": "not_configured", "channel": None,
            "note": ("No TH360_INCIDENT_WEBHOOK configured — the declaration "
                     "is recorded locally (audit trail + notification "
                     "center). Configure the webhook to reach PagerDuty/"
                     "Slack in production. This is disclosed honestly per "
                     "§20 — no pretend escalation.")}

    store.declare_incident(incident_id, severity, summary, declared_by,
                           delivery)
    store.notify(kind="GOVERNANCE",
                 title=f"Incident declared: {severity}",
                 body=(f"{summary} — declared by {declared_by}. Delivery: "
                       f"{delivery['state']}. Response checklist is active "
                       f"in the Ops Node."),
                 ref=incident_id)
    safety.log_event(store, "incident_declared", actor=declared_by,
                     detail=f"{severity}: {summary[:120]}")
    return {
        "incident_id": incident_id, "severity": severity,
        "status": "ACTIVE", "declared_by": declared_by,
        "delivery": delivery,
        "checklist": RESPONSE_CHECKLIST,
        "ui_guidance": UI_GUIDANCE,
    }
