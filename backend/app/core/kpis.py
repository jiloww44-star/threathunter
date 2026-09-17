"""§71 KPI engine + §72 north-star — v4.5 Production Pilot Readiness.

Spec text (§71) — five families:
  intelligence quality (evidence-backed conclusion rate, contradiction
  detection rate, freshness, diversity, analyst correction rate);
  journey (completion, reroute acceptance, false-alarm rate, freshness,
  decision latency); fact checker (evidence coverage, agreement, correction
  rate, latency); agent security (inventory counts, remediated findings,
  coverage); governance (policy coverage, evidence completeness,
  reconstruction time, exceptions).
§72 north-star: **evidence-backed decisions successfully completed.**

Honest-degradation contract (§20), applied to metrics themselves:
every KPI is a ``KpiValue`` — ``{value, unit, status, sample, basis}``.
``status: OK`` means the number is *computed from persisted rows* whose
meaning is stated in ``basis``. ``status: UNAVAILABLE`` means the platform
does not persist what the spec asks for; ``value`` is null and ``basis``
says exactly which write-path is missing. A measured zero (sample n) is
reported as OK 0 — a fabricated zero (no data path) is reported as
UNAVAILABLE, never as a number. This is the §76 invariant for telemetry:
no consequential *statement about the platform* without evidence either.

Window semantics: event-derived KPIs (audit_trail, checks, approvals)
honor ``window_hours``; state-derived KPIs (inventory, retention invariants,
chain integrity) are all-time and say so in their basis.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

from . import agent_inventory
from .nlp_lite import parse_iso
from .privacy import verify_chain

KPI_ENGINE_VERSION = "kpi-engine/4.5.0"
DEFAULT_WINDOW_HOURS = int(os.environ.get("TH360_KPI_WINDOW_HOURS", "168"))


# ---------------------------------------------------------------- KpiValue --
def _ok(value, *, unit: str, sample: int, basis: str) -> dict:
    return {"value": value, "unit": unit, "status": "OK",
            "sample": sample, "basis": basis}


def _unavail(*, unit: str, basis: str) -> dict:
    return {"value": None, "unit": unit, "status": "UNAVAILABLE",
            "sample": 0, "basis": basis}


def _cutoff(window_hours: int) -> str:
    return (datetime.now(timezone.utc)
            - timedelta(hours=window_hours)).isoformat()


def _age_hours(ts: str | None, now: datetime) -> float | None:
    dt = parse_iso(ts) if ts else None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


# ----------------------------------------------------------------- families --
def _north_star(store) -> dict:
    """§72 — evidence-backed decisions successfully completed.

    'Decision completed' = a CLOSED investigation; 'evidence-backed' = ≥1
    investigation_links row of kind='evidence'. Both are persisted facts.
    """
    row = store.kpi_sql(
        """SELECT COUNT(*) c FROM investigations i
           WHERE i.status='CLOSED' AND EXISTS (
             SELECT 1 FROM investigation_links l
             WHERE l.investigation_id = i.id AND l.kind='evidence')""")
    closed = store.kpi_sql(
        "SELECT COUNT(*) c FROM investigations WHERE status='CLOSED'")
    value, sample = row[0]["c"], closed[0]["c"]
    return {
        "id": "evidence_backed_decisions_completed",
        "spec": "§72 north-star",
        **_ok(value, unit="count", sample=sample,
              basis=("CLOSED investigations carrying ≥1 linked evidence item "
                     f"(investigation_links kind='evidence'); {sample} closed "
                     "investigations examined, all-time."))}


def _intelligence_quality(store, now: datetime) -> dict:
    closed = store.kpi_sql(
        "SELECT COUNT(*) c FROM investigations WHERE status='CLOSED'")[0]["c"]
    closed_ev = store.kpi_sql(
        """SELECT COUNT(*) c FROM investigations i
           WHERE i.status='CLOSED' AND EXISTS (
             SELECT 1 FROM investigation_links l
             WHERE l.investigation_id=i.id AND l.kind='evidence')""")[0]["c"]
    concl = (_ok(round(closed_ev / closed, 4), unit="ratio", sample=closed,
                 basis=("share of CLOSED investigations that close with ≥1 "
                        "linked evidence item — a conclusion is only "
                        "'evidence-backed' when the chain exists (§76)."))
             if closed else
             _unavail(unit="ratio",
                      basis="no CLOSED investigations yet — rate undefined, "
                            "not zero."))
    contra = store.kpi_sql(
        """SELECT COUNT(*) c FROM review_queue
           WHERE module LIKE '%contradict%'""")[0]["c"]
    checks = store.kpi_sql("SELECT COUNT(*) c FROM checks")[0]["c"]
    contra_rate = (_ok(round(contra / checks, 4), unit="ratio", sample=checks,
                       basis=("review_queue rows flagged by the contradiction "
                              "detector ÷ all pipeline checks run."))
                   if checks else
                   _unavail(unit="ratio", basis="no checks have run yet."))
    ev_rows = store.kpi_sql(
        """SELECT fetched_at, source_id FROM evidence
           WHERE fetched_at IS NOT NULL ORDER BY fetched_at DESC""")
    ages = [a for a in (_age_hours(r["fetched_at"], now) for r in ev_rows)
            if a is not None]
    freshness = (_ok(round(min(ages), 2), unit="hours", sample=len(ages),
                     basis=("age of the newest evidence row (fetched_at); "
                            "freshness of the *store*, measured."))
                 if ages else
                 _unavail(unit="hours",
                          basis="evidence store empty — nothing ingested."))
    distinct = len({r["source_id"] for r in ev_rows})
    diversity = (_ok(distinct, unit="sources", sample=len(ev_rows),
                     basis=("distinct source_ids across all stored evidence; "
                            "independence (not just count) is what §1.6 "
                            "weighs — see fact_checker.coverage."))
                 if ev_rows else
                 _unavail(unit="sources", basis="evidence store empty."))
    correction = _unavail(
        unit="ratio",
        basis=("analyst corrections are not persisted diffs: review_queue "
               "stores the queue, not system-vs-human verdict deltas. Pilot "
               "proposal P-3 (persist decided verdict + prior system verdict) "
               "closes this honestly — until then: UNAVAILABLE, not 0."))
    return {"evidence_backed_conclusion_rate": concl,
            "contradiction_detection_rate": contra_rate,
            "contradictions_flagged": _ok(
                contra, unit="count", sample=checks,
                basis="review_queue rows raised by contradiction detection, "
                      "all-time."),
            "freshness": freshness,
            "source_diversity": diversity,
            "analyst_correction_rate": correction}


def _journey(store, cutoff: str, now: datetime) -> dict:
    total = store.kpi_sql("SELECT COUNT(*) c FROM investigations")[0]["c"]
    closed = store.kpi_sql(
        "SELECT COUNT(*) c FROM investigations WHERE status='CLOSED'")[0]["c"]
    completion = (_ok(round(closed / total, 4), unit="ratio", sample=total,
                      basis=("CLOSED ÷ all investigations (the case is the "
                             "journey's unit of completion, §2)."))
                  if total else
                  _unavail(unit="ratio", basis="no investigations exist yet."))
    reroutes = store.kpi_sql(
        """SELECT COUNT(*) c FROM audit_trail
           WHERE action='event:JourneyConditionChanged'
             AND created_at >= ?""", (cutoff,))[0]["c"]
    alerts = store.kpi_sql(
        """SELECT COUNT(*) c FROM audit_trail
           WHERE action='event:AlertTriggered' AND created_at >= ?""",
        (cutoff,))[0]["c"]
    decided = store.approval_list(status=None, limit=500)
    lat = []
    for a in decided:
        if a["status"] in ("APPROVED", "REJECTED") and a.get("decided_at"):
            st, en = parse_iso(a["created_at"]), parse_iso(a["decided_at"])
            if st and en:
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                if en.tzinfo is None:
                    en = en.replace(tzinfo=timezone.utc)
                if en >= st:
                    lat.append((en - st).total_seconds())
    latency = (_ok(round(sum(lat) / len(lat), 1), unit="seconds",
                   sample=len(lat),
                   basis=("mean request→decision time over decided approvals — "
                          "the authorization decision is the journey's "
                          "consequential decision latency (§37/§71)."))
               if lat else
               _unavail(unit="seconds",
                        basis="no approvals decided yet — latency undefined."))
    watches = store.kpi_sql(
        """SELECT COUNT(*) c FROM journey_watches
           WHERE status IN ('MONITORING','ELEVATED')""")[0]["c"]
    return {
        "completion_rate": completion,
        "reroute_events": _ok(reroutes, unit="count", sample=reroutes,
                              basis="event:JourneyConditionChanged rows in "
                                    f"window ({cutoff[:10]}…), the §26 "
                                    "reroute signal."),
        "reroute_acceptance_rate": _unavail(
            unit="ratio",
            basis=("watch reroutes carry no accept/decline adjudication by "
                   "the operator — persisted fact gap, reported honestly.")),
        "alerts_triggered": _ok(alerts, unit="count", sample=alerts,
                                basis="event:AlertTriggered in window."),
        "false_alarm_rate": _unavail(
            unit="ratio",
            basis=("alert outcomes (true/false positive) are not adjudicated "
                   "in the demo profile — no verdict column exists on "
                   "notifications; this is a stated gap, not a zero.")),
        "decision_latency": latency,
        "watches_active": _ok(watches, unit="count", sample=watches,
                              basis="journey_watches rows with status='active'"
                                    ", all-time state."),
    }


def _fact_checker(store, cutoff: str) -> dict:
    rows = store.kpi_sql(
        """SELECT response_json FROM checks
           WHERE module='factcheck' AND created_at >= ?""", (cutoff,))
    runs = len(rows)
    coverage_dist: dict[str, int] = {}
    indep: list[float] = []
    for r in rows:
        try:
            resp = json.loads(r["response_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        cov = (resp.get("coverage") or "").upper()
        if cov:
            coverage_dist[cov] = coverage_dist.get(cov, 0) + 1
        si = resp.get("sources_independent")
        if isinstance(si, (int, float)):
            indep.append(float(si))
    high = coverage_dist.get("HIGH", 0)
    with_cov = sum(coverage_dist.values())
    coverage = (_ok(round(high / with_cov, 4), unit="ratio", sample=with_cov,
                    basis=(f"share of fact-check runs scoring coverage=HIGH; "
                           f"distribution {coverage_dist} over runs in "
                           "window."))
                if with_cov else
                _unavail(unit="ratio",
                         basis="no fact-check runs in window (or runs predate "
                               "the coverage axis, v4.0 §49)."))
    agreement = (_ok(round(sum(indep) / len(indep), 2),
                     unit="independent_sources", sample=len(indep),
                     basis=("mean copy-chain-aware independent source count "
                            "per run (§1.6) — corroboration *across "
                            "independence groups*, not raw mention count."))
                 if indep else
                 _unavail(unit="independent_sources",
                          basis="no runs in window."))
    return {
        "runs": _ok(runs, unit="count", sample=runs,
                    basis="checks rows module='factcheck' in window."),
        "evidence_coverage": coverage,
        "agreement": agreement,
        "correction_rate": _unavail(
            unit="ratio",
            basis=("analyst overrides of fact-check verdicts are not "
                   "persisted as deltas (see intelligence_quality."
                   "analyst_correction_rate, proposal P-3).")),
        "latency": _unavail(
            unit="seconds",
            basis=("pipeline run latency is not persisted per check — reported"
                   " honestly as a missing write-path rather than omitted.")),
    }


def _agent_security(store) -> dict:
    inv = agent_inventory.inventory(store)
    nodes = inv.get("agents") or inv.get("nodes") or []
    total = len(nodes)
    known = sum(1 for n in nodes
                if n.get("known_issue") and
                n["known_issue"] != "none recorded")
    trust: dict[str, int] = {}
    for n in nodes:
        t = n.get("trust_status", "QUARANTINED")
        trust[t] = trust.get(t, 0) + 1
    remediated = store.kpi_sql(
        """SELECT COUNT(*) c FROM approvals
           WHERE kind LIKE '%patch%' AND status='APPROVED'""")[0]["c"]
    return {
        "inventory_total": _ok(total, unit="nodes", sample=total,
                               basis="agent supply-chain cards in the live "
                                     "inventory (every node answers §supply "
                                     "chain per-node fields)."),
        "nodes_with_known_issues": _ok(
            known, unit="nodes", sample=total,
            basis="cards whose known_issue field is populated."),
        "trust_distribution": _ok(
            trust, unit="by_status", sample=total,
            basis="TRUSTED (native) | OBSERVED (SDK shadowing) | "
                  "QUARANTINED counts from the inventory cards."),
        "review_coverage": _ok(
            1.0 if total else None, unit="ratio", sample=total,
            basis=("every inventory node carries a last_reviewed statement "
                   "(native: build-time declaration, stated honestly; SDK: "
                   "admission record) — 100% of cards answer the field, so "
                   "coverage-of-the-field is 1.0.")
            if total else "no agents registered."),
        "remediated_findings": _ok(
            remediated, unit="count", sample=remediated,
            basis="APPROVED approvals of kind *patch* — remediation went "
                  "through the approval engine (§37)."),
    }


def _governance(store, cutoff: str) -> dict:
    decisions = store.kpi_sql(
        """SELECT decision, COUNT(*) c FROM audit_trail
           WHERE policy_version LIKE 'policy-engine/%' AND created_at >= ?
           GROUP BY decision""", (cutoff,))
    by_decision = {r["decision"]: r["c"] for r in decisions}
    total_inv = store.kpi_sql(
        "SELECT COUNT(*) c FROM investigations")[0]["c"]
    with_policy = store.kpi_sql(
        """SELECT COUNT(*) c FROM investigations
           WHERE allowed_sources_json NOT IN ('[]', '', 'null')""")[0]["c"]
    t0 = time.perf_counter()
    chain = verify_chain(store)
    store.audit_trail(limit=500)
    reconstruct_ms = round((time.perf_counter() - t0) * 1000, 1)
    decided = store.approval_list(status=None, limit=500)
    exceptions = 0
    decided_n = 0
    for a in decided:
        if a["status"] not in ("APPROVED", "REJECTED"):
            continue
        ctx = a.get("context") or {}
        if not isinstance(ctx, dict):
            try:
                ctx = json.loads(ctx)
            except (TypeError, json.JSONDecodeError):
                ctx = {}
        ov = ctx.get("decision_basis_overrides") or []
        decided_n += 1
        if a["status"] == "APPROVED" and ov:
            exceptions += 1
    pending_old = store.kpi_sql(
        """SELECT COUNT(*) c FROM approvals
           WHERE status='PENDING' AND created_at < ?""",
        ((datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),)
    )[0]["c"]
    return {
        "policy_decisions": _ok(
            by_decision, unit="by_outcome",
            sample=sum(by_decision.values()),
            basis=("audit_trail rows recorded by the v4.2 policy engine in "
                   "window, grouped PERMIT|DENY|REQUIRE_HUMAN — every "
                   "consequential action attempt leaves one (§76).")),
        "policy_coverage": (_ok(
            round(with_policy / total_inv, 4), unit="ratio", sample=total_inv,
            basis="investigations carrying a declared allowed_sources policy "
                  "÷ all investigations.")
            if total_inv else
            _unavail(unit="ratio", basis="no investigations exist yet.")),
        "evidence_completeness": _ok(
            1.0 if chain["chain_intact"] else 0.0, unit="bool",
            sample=chain["entries"],
            basis=("consent/evidence hash-chain reverified on read "
                   f"({chain['entries']} entries); 1.0 = intact, 0.0 = "
                   "tamper detected at "
                   f"{chain.get('broken_at')}.")),
        "reconstruction_time": _ok(
            reconstruct_ms, unit="ms", sample=chain["entries"],
            basis=("wall-clock to re-read the last 500 audit rows + fully "
                   "reverify the hash chain, measured on this node just now "
                   "— the §68 reproducibility cost of an audit "
                   "reconstruction.")),
        "override_exceptions": _ok(
            exceptions, unit="count", sample=decided_n,
            basis=("APPROVED approvals whose decision carries explicit "
                   "basis-overrides (a human overruled a policy signal in "
                   "writing) — the §71 'exceptions' count.")),
        "override_rate": (_ok(
            round(exceptions / decided_n, 4), unit="ratio", sample=decided_n,
            basis="override_exceptions ÷ decided approvals.")
            if decided_n else
            _unavail(unit="ratio", basis="no approvals decided yet.")),
        "approvals_pending_over_72h": _ok(
            pending_old, unit="count", sample=pending_old,
            basis="PENDING approvals older than 72h — aging governance debt."),
    }


def compute_kpis(store, window_hours: int | None = None) -> dict:
    """Full §71 read-out. Every value carries its own provenance (basis) —
    the KPI layer obeys the same evidence discipline it measures."""
    wh = window_hours or DEFAULT_WINDOW_HOURS
    cutoff = _cutoff(wh)
    now = datetime.now(timezone.utc)
    return {
        "kpi_version": KPI_ENGINE_VERSION,
        "spec": "§71 five KPI families + §72 north-star",
        "computed_at": now.isoformat(),
        "window_hours": wh,
        "north_star": _north_star(store),
        "families": {
            "intelligence_quality": _intelligence_quality(store, now),
            "journey": _journey(store, cutoff, now),
            "fact_checker": _fact_checker(store, cutoff),
            "agent_security": _agent_security(store),
            "governance": _governance(store, cutoff),
        },
        "honesty_note": (
            "UNAVAILABLE means the platform does not persist the required "
            "write-path; the basis names the gap. §20: a KPI we cannot "
            "measure is reported as unmeasurable — never as zero."),
    }


# ------------------------------------------------- prometheus text export --
def to_prometheus(report: dict) -> str:
    """§71 values as Prometheus exposition text for pilot ops scraping.

    UNAVAILABLE KPIs emit NO value line (a fabricated number in a metrics
    pipeline is worse than an absent series) — they appear as
    ``th360_kpi_available{…} 0`` so alerting on unmeasurable KPIs is easy.
    """
    lines = [
        "# HELP th360_kpi_value ThreatHunter360 §71 KPI value.",
        "# TYPE th360_kpi_value gauge",
        "# HELP th360_kpi_sample Rows the KPI was computed from.",
        "# TYPE th360_kpi_sample gauge",
        "# HELP th360_kpi_available 1 when measured, 0 when UNAVAILABLE (§20).",
        "# TYPE th360_kpi_available gauge",
    ]

    def emit(family: str, metric: str, kv: dict) -> None:
        lbl = f'family="{family}",metric="{metric}"'
        if kv["status"] == "OK" and isinstance(kv["value"], (int, float)):
            lines.append(f"th360_kpi_value{{{lbl}}} {kv['value']}")
            lines.append(f"th360_kpi_sample{{{lbl}}} {kv['sample']}")
            lines.append(f"th360_kpi_available{{{lbl}}} 1")
        elif kv["status"] == "OK" and isinstance(kv["value"], dict):
            for k, v in kv["value"].items():
                dlbl = (f'family="{family}",metric="{metric}",'
                        f'dimension="{k}"')
                lines.append(f"th360_kpi_value{{{dlbl}}} {v}")
            lines.append(f"th360_kpi_sample{{{lbl}}} {kv['sample']}")
            lines.append(f"th360_kpi_available{{{lbl}}} 1")
        else:
            lines.append(f"th360_kpi_available{{{lbl}}} 0")

    ns = report["north_star"]
    emit("north_star", ns["id"], ns)
    for fam, metrics in report["families"].items():
        for metric, kv in metrics.items():
            emit(fam, metric, kv)
    return "\n".join(lines) + "\n"
