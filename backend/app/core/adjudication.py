"""Human-outcome adjudication — v4.6 MEASUREMENT CLOSURE (§71 write-paths).

Until v4.6 the platform could not measure five spec §71 KPIs because the
write-paths did not exist (honestly reported UNAVAILABLE in v4.5 — "sample
0 with no denominator"). This module IS those write-paths:

    review decisions        → analyst_correction_rate (intelligence quality)
                              + fact_checker.correction_rate
    reroute adjudication    → journey.reroute_acceptance_rate
    alert adjudication      → journey.false_alarm_rate
    (fact-check latency is a one-line engine patch — see reasoning_engine)

Discipline (§76 applied to measurement): every human outcome is a
single-decision atomic write (a second attempt 409s; the attempt is still
audited), every decision mints an event on the permanent audit trail, and
the KPI engine only ever computes over these rows — a KPI can still be
UNAVAILABLE, but now only when nobody has decided anything yet, which is
the true statement.

Event vocabulary: ReviewDecided / RerouteAdjudicated / AlertAdjudicated are
platform extensions beyond §26's fourteen — documented as such in the
v4.6 mapping doc and TRUST §15 (the SourceHealthChanged precedent of v4.3:
platform events are named honestly, never smuggled into the spec list).
"""
from __future__ import annotations

from .errors import PipelineError

ADJUDICATION_VERSION = "adjudication/4.6.0"

REVIEW_DECISIONS = ("CONFIRMED", "CORRECTED")
ALERT_VERDICTS = ("TRUE_POSITIVE", "FALSE_POSITIVE")
REROUTE_OUTCOMES = ("ACCEPTED", "DECLINED", "AUTO_RESOLVED")


def _event(store, name: str, actor: str, detail: str) -> None:
    store.audit(actor=actor, action=f"event:{name}", decision="ALLOW",
                detail=detail, policy_version=ADJUDICATION_VERSION)


# ------------------------------------------------------------ review queue --
def decide_review(store, review_id: str, *, decision: str, decided_by: str,
                  corrected_outcome: str | None = None) -> dict:
    """§27 human-in-the-loop, now with a decision: the reviewer CONFIRMs the
    system output stands, or CORRECTs it with the right outcome in writing.

    prior_outcome is resolved from the system's own persisted verdict where
    one exists (factcheck/kyc review items reference a checks row); where
    the module has no persisted system verdict we store NULL and SAY so in
    the audit detail — no back-filled "system said" claims.
    """
    decision = (decision or "").upper()
    if decision not in REVIEW_DECISIONS:
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=f"decision must be one of {REVIEW_DECISIONS}")
    row = store.review_get(review_id)
    if not row:
        raise PipelineError("REVIEW_NOT_FOUND", status=404,
                            detail=f"review item {review_id} does not exist.")
    corrected = (corrected_outcome or "").strip() or None
    if decision == "CORRECTED" and not corrected:
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=("CORRECTED requires the corrected outcome in writing — "
                    "an unwritten correction is not an analyst correction "
                    "(§71 needs the diff, §76 needs the words)."))
    prior = None
    if row["module"] in ("factcheck", "kyc") and row.get("case_ref"):
        check = store.get_check(row["case_ref"])
        if check:
            prior = check["outcome"]
    changed = store.review_decide(
        review_id, decision=decision, decided_by=decided_by,
        prior_outcome=prior, corrected_outcome=corrected)
    if changed != 1:
        raise PipelineError("REVIEW_ALREADY_DECIDED", status=409,
                            detail=f"review item is {row['status']}, not "
                                   "OPEN — decisions are single-use.")
    _event(store, "ReviewDecided", decided_by,
           f"{row['module']} review {review_id[:8]}: {decision}"
           + (f" (system said {prior!r}, analyst says {corrected!r})"
              if decision == "CORRECTED"
              else f" (system said {prior!r}, confirmed)"
              if prior else " (no persisted system verdict to diff)"))
    return store.review_get(review_id)


# -------------------------------------------------------------- alert queue --
def adjudicate_alert(store, notification_id: str, *, verdict: str,
                     decided_by: str) -> dict:
    """Mark an AlertTriggered notification TRUE_POSITIVE or FALSE_POSITIVE.
    Denominator hygiene: exactly one adjudication per alert, atomically."""
    verdict = (verdict or "").upper()
    if verdict not in ALERT_VERDICTS:
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=f"verdict must be one of {ALERT_VERDICTS}")
    row = store.notification_get(notification_id)
    if not row:
        raise PipelineError("NOTIFICATION_NOT_FOUND", status=404,
                            detail=f"notification {notification_id} does "
                                   "not exist.")
    changed = store.adjudicate_notification(
        notification_id, verdict=verdict, adjudicated_by=decided_by)
    if changed != 1:
        raise PipelineError("ALERT_ALREADY_ADJUDICATED", status=409,
                            detail=f"alert already adjudicated "
                                   f"{row['adjudication']} by "
                                   f"{row['adjudicated_by']}.")
    _event(store, "AlertAdjudicated", decided_by,
           f"notification {notification_id[:8]} → {verdict} "
           f"(kind={row['kind']}: {row['title'][:60]})")
    return store.notification_get(notification_id)


# ------------------------------------------------------------- reroutes (§j)
def decide_reroute(store, watch_id: str, *, accept: bool,
                   decided_by: str) -> dict:
    """Human answer to a machine reroute recommendation: ACCEPT (take the
    new route) or DECLINE (keep the plan with the risk noted). The ratio of
    the two over time is how much operators actually trust the rerouter."""
    outcome = "ACCEPTED" if accept else "DECLINED"
    row = store.get_watch(watch_id)
    if not row:
        raise PipelineError("WATCH_NOT_FOUND", status=404,
                            detail=f"watch {watch_id} does not exist.")
    changed = store.decide_watch_reroute(watch_id, outcome=outcome)
    if changed != 1:
        raise PipelineError("REROUTE_NOT_PENDING", status=409,
                            detail=(f"watch {watch_id} has no PENDING reroute"
                                    " recommendation (outcome="
                                    f"{row.get('reroute_outcome')!r})."))
    _event(store, "RerouteAdjudicated", decided_by,
           f"watch {watch_id[:12]} {row['origin']}→{row['destination']}: "
           f"reroute {outcome} (risk {row.get('current_risk')})")
    return store.get_watch(watch_id)


def auto_resolve_reroute(store, watch_id: str) -> bool:
    """The engine's own out: when corridor risk eases back under tolerance,
    a stale pending recommendation is AUTO_RESOLVED — never counted as
    human acceptance or rejection."""
    return store.decide_watch_reroute(watch_id, outcome="AUTO_RESOLVED") == 1
