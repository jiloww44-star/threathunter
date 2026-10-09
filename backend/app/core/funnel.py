"""§72 EVIDENCE FUNNEL (v4.9) — the pipeline INTO the north-star, made visible.

Origin: design/ContextualSystems-v1.md hypothesis H3 (the self-applied
status-request loop): operators kept asking "is it working?" because the
denominators feeding §72's north-star were invisible — everything sat
UNAVAILABLE until a case closed, with no view of cases marching toward it.

Honesty contract (same as the KPI engine, §20):
  * every stage is a measured COUNT with a basis string naming its query —
    never a fabricated zero ("rate undefined" when a denominator is empty);
  * `observed` counts governed live-source ATTEMPTS (event:SourceQueried) —
    including DENIED ones, by design: an attempt is operator behavior, and
    v4.8 made denied rows carry the case id so failure is as visible as
    success;
  * `completed` is computed with the EXACT §72 north-star query — the
    consistency block in the payload proves the funnel cannot disagree
    with the KPI engine it explains.

Two lenses: all-time (mirrors the north-star basis) and, when
`window_hours` is given, a COHORT view: cases opened inside the window,
their current downstream state measured now — basis strings say which.
"""
from __future__ import annotations

__version__ = "funnel-engine/4.9.0"

from datetime import datetime, timedelta, timezone


def _ok(value, *, unit, sample, basis):
    return {"value": value, "unit": unit, "status": "OK", "sample": sample,
            "basis": basis}


def _unavailable(unit, basis):
    return {"value": None, "unit": unit, "status": "UNAVAILABLE",
            "sample": 0, "basis": basis}


def _count(store, sql: str, params: tuple = ()) -> int:
    return store.kpi_sql(sql, params)[0]["c"]


def _stages(store, where: str, params: tuple, cohort: str) -> list[dict]:
    """Cumulative-set stages over the `investigations` base filtered by
    `where` (empty for all-time, created_at cutoff for the cohort lens)."""
    opened = _count(store, f"SELECT COUNT(*) c FROM investigations i {where}",
                    params)
    observed = _count(
        store,
        "SELECT COUNT(*) c FROM investigations i " + (where + " AND" if where
         else "WHERE") + """ EXISTS (
             SELECT 1 FROM audit_trail a
             WHERE a.action='event:SourceQueried' AND INSTR(a.detail, i.id) > 0)""",
        params)
    linked = _count(
        store,
        "SELECT COUNT(*) c FROM investigations i " + (where + " AND" if where
         else "WHERE") + """ EXISTS (
             SELECT 1 FROM investigation_links l
             WHERE l.investigation_id = i.id AND l.kind='evidence')""",
        params)
    closed = _count(
        store,
        "SELECT COUNT(*) c FROM investigations i " + (where + " AND" if where
         else "WHERE") + " i.status='CLOSED'", params)
    # EXACT §72 north-star numerator (kpis._north_star), kept query-identical
    # on purpose — the consistency test pins it.
    completed = _count(
        store,
        "SELECT COUNT(*) c FROM investigations i " + (where + " AND" if where
         else "WHERE") + """ i.status='CLOSED' AND EXISTS (
             SELECT 1 FROM investigation_links l
             WHERE l.investigation_id = i.id AND l.kind='evidence')""",
        params)

    base = f"over {opened} investigations {cohort}."
    return [
        {"id": "opened", "label": "Cases opened",
         **_ok(opened, unit="count", sample=opened,
               basis="investigations rows created " + base)},
        {"id": "observed", "label": "Governed observation attempted",
         **_ok(observed, unit="count", sample=opened,
               basis=("investigations with ≥1 event:SourceQueried audit row "
                      "naming the case — attempts INCLUDING denied ones "
                      "(v4.8: failure is as visible as success), " + base))},
        {"id": "linked", "label": "Evidence linked",
         **_ok(linked, unit="count", sample=opened,
               basis=("investigations with ≥1 investigation_links row "
                      "kind='evidence', " + base))},
        {"id": "closed", "label": "Cases closed",
         **_ok(closed, unit="count", sample=opened,
               basis="investigations with status='CLOSED', " + base)},
        {"id": "completed", "label": "Evidence-backed completed (§72 numerator)",
         **_ok(completed, unit="count", sample=closed,
               basis=("CLOSED investigations carrying ≥1 linked evidence item "
                      "— the EXACT north-star query, " + base))},
    ]


def _conversions(stages: list[dict]) -> list[dict]:
    """Ratios between cumulative stages; empty denominator ⇒ UNAVAILABLE
    ('rate undefined, not zero' — §20), never a fabricated 0.0."""
    by = {s["id"]: s["value"] for s in stages}

    def ratio(rid, num_key, den_key, label, why):
        den = by[den_key]
        if not den:
            return {"id": rid, "label": label, "from": den_key, "to": num_key,
                    **_unavailable(
                        "ratio",
                        f"no {den_key} investigations ({den_key}=0) — "
                        f"{label.lower()} is undefined, not zero. {why}")}
        return {"id": rid, "label": label, "from": den_key, "to": num_key,
                **_ok(round(by[num_key] / den, 4), unit="ratio", sample=den,
                      basis=f"{by[num_key]}/{den} {num_key}÷{den_key} — {why}")}

    return [
        ratio("attempt_rate", "observed", "opened",
              "Opened → live attempt", "did anyone start observing?"),
        ratio("link_rate", "linked", "opened",
              "Opened → evidence linked", "did the case acquire evidence?"),
        ratio("close_rate", "closed", "opened",
              "Opened → closed", "do cases reach a completed decision?"),
        ratio("evidence_backed_completion", "completed", "closed",
              "Closed → evidence-backed (headline)",
              "the §72 property on completed decisions."),
    ]


def compute_funnel(store, window_hours: int | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    if window_hours is None:
        where, params, lens = "", (), "all-time"
    else:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=window_hours)).isoformat()
        where, params = "WHERE i.created_at >= ?", (cutoff,)
        lens = (f"COHORT: opened in the last {window_hours}h, downstream "
                "state measured now")

    stages = _stages(store, where, params, lens)
    completed = next(s["value"] for s in stages if s["id"] == "completed")
    # Consistency is only claimable against the all-time lens — the
    # north-star itself is all-time.
    consistency = None
    if window_hours is None:
        from . import kpis
        ns = kpis._north_star(store)["value"]
        consistency = {"funnel_completed": completed, "kpis_north_star": ns,
                       "match": completed == ns,
                       "basis": ("funnel.completed recomputed with the exact "
                                 "§72 query must equal kpis._north_star — "
                                 "a mismatch would be a defect, not a nuance.")}

    return {
        "funnel_version": __version__,
        "spec": ("§72 north-star pipeline made visible — ContextualSystems-v1 "
                 "H3 (engine-derived; documented openly, not a spec addition)"),
        "computed_at": now,
        "lens": lens,
        "stages": stages,
        "conversions": _conversions(stages),
        "north_star_consistency": consistency,
        "notes": [
            ("Stages are cumulative-set filters, not a strict order: a case "
             "can link seed evidence without a live attempt."),
            ("'observed' = governed live ATTEMPTS (allowed or denied) — "
             "denied attempts mean the §80/§76 gate fired honestly, so they "
             "still belong in the pipeline."),
            ("Empty denominators report UNAVAILABLE — a fabricated 0.0 "
             "would be intelligence theater (§20)."),
        ],
    }
