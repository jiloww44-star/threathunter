"""Analytics endpoints — spec §4 (analytics data sheet + dashboard JSON).

/api/v1/admin/analytics/summary  → dashboard series (KPIs + daily rows)
/api/v1/admin/analytics/export   → data sheet as CSV (XLSX when openpyxl
                                   present — Sheet layout per §4.2)
/api/v1/admin/budget             → ledger snapshot (Part E governance)
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta, timezone, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ...api.deps import current_user, get_db
from ...core.budget import get_budget

router = APIRouter(prefix="/api/v1/admin", tags=["Analytics & Admin"])


@router.get("/analytics/summary")
async def analytics_summary(days: int = Query(30, ge=1, le=365),
                            db=Depends(get_db), user=Depends(current_user)):
    rows = db.analytics_daily(days=min(days, 365))
    total_checks = sum(r["checks_total"] for r in rows)
    total_cost = sum(r["llm_cost_usd"] for r in rows)
    total_calls = sum(r["llm_calls"] for r in rows)
    avg_conf = (sum(r["avg_confidence"] * r["checks_total"] for r in rows)
                / total_checks) if total_checks else 0
    week = [r for r in rows if r["day"] >= str(
        (datetime.now(timezone.utc) - timedelta(days=7)).date())]
    prev = [r for r in rows if str(
        (datetime.now(timezone.utc) - timedelta(days=14)).date())
        <= r["day"] < str((datetime.now(timezone.utc) - timedelta(days=7)).date())]
    cur_n, prev_n = (sum(r["checks_total"] for r in week),
                     sum(r["checks_total"] for r in prev))
    wow = round((cur_n - prev_n) / prev_n, 3) if prev_n else None
    stats = db.statistics()
    return {
        "days": days,
        "daily": rows,
        "kpis": {
            "checks_total": total_checks,
            "avg_confidence": round(avg_conf, 3),
            "llm_cost_usd": round(total_cost, 6),
            "cost_per_check": round(total_cost / total_checks, 6)
                if total_checks else 0,
            "llm_calls": total_calls,
            "wow_change": wow,
            "copy_chain_ratio": stats["copy_chain_ratio"],
            "review_queue_depth": stats["review_queue_depth"],
        },
        "budget": get_budget().summary(),
    }


SHEETS = [
    ("Daily", ["day", "checks_total", "verified", "unverified",
               "false_or_misleading", "avg_confidence",
               "avg_source_diversity", "llm_cost_usd", "llm_calls"]),
]


def build_daily_csv(rows: list[dict]) -> str:
    """§4.2 Sheet 'Daily' as CSV text — shared by the export route and the
    e2e free-stack demo's Stage 5 (demo/e2e_free_stack_demo.py)."""
    buf = io.StringIO()
    headers = SHEETS[0][1]
    w = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


@router.get("/analytics/export")
async def export_sheet(format: str = Query("csv", enum=["csv", "xlsx"]),
                       days: int = Query(30, ge=1, le=365),
                       db=Depends(get_db), user=Depends(current_user)):
    rows = db.analytics_daily(days=min(days, 365))

    if format == "xlsx":
        try:
            from openpyxl import Workbook  # §4.2 xlsx export
        except ImportError:
            format = "csv"   # honest degradation: xlsx unavailable → CSV
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = "Daily"
            headers = SHEETS[0][1]
            ws.append(["ThreatHunter360 Analytics — Daily"])
            ws.append(headers)
            for r in rows:
                ws.append([r.get(h) for h in headers])
            # Sheet 2: verdict×week pivot; Sheet 5: KYC funnel — from checks
            ws2 = wb.create_sheet("By Verdict")
            from collections import Counter
            tally = Counter()
            db_checks = db.recent_checks(limit=500)
            ws2.append(["outcome", "count"])
            with db._lock:
                raw = db._conn.execute(
                    "SELECT outcome, COUNT(*) c FROM checks GROUP BY outcome"
                ).fetchall()
            for row in raw:
                ws2.append([row[0], row[1]])
            ws3 = wb.create_sheet("KYC funnel")
            ws3.append(["stage", "count"])
            with db._lock:
                kyc_rows = db._conn.execute(
                    "SELECT outcome, COUNT(*) c FROM checks "
                    "WHERE module='kyc' GROUP BY outcome").fetchall()
            ws3.append(["submitted", sum(r[1] for r in kyc_rows)])
            for row in kyc_rows:
                ws3.append([row[0], row[1]])
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-"
                           "officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition":
                         "attachment; filename=th360-analytics.xlsx"})

    # CSV — Sheet 1 "Daily"
    return StreamingResponse(
        iter([build_daily_csv(rows)]), media_type="text/csv",
        headers={"Content-Disposition":
                 "attachment; filename=th360-analytics.csv"})


@router.get("/budget")
async def budget_ledger(user=Depends(current_user)):
    return get_budget().summary()


# ------------------------------------------------------- Part 18 D1 queue --
@router.get("/review-queue")
async def review_queue_admin(db=Depends(get_db), user=Depends(current_user)):
    """Human-in-the-loop queue with Part 18 D1 tier labels and lane counts —
    reviewer demand becomes proportional to UNCERTAINTY, not volume."""
    queue = db.review_queue()
    by_tier: dict[str, int] = {}
    for q in queue:
        by_tier[q.get("tier") or "UNROUTED"] = \
            by_tier.get(q.get("tier") or "UNROUTED", 0) + 1
    return {
        "queue": queue,
        "depth": len(queue),
        "by_tier": by_tier,
        "sla": "4 business hours per item (§14)",
        "policy": {
            "MANDATORY_REVIEW": "≥2 contradictions · copy-chain dominance · "
                                "confidence ≤ MODERATE · high-stakes surfaces",
            "AUDIT_SAMPLE": "5% random QA of auto-published high-confidence "
                            "low-stakes verdicts",
            "CURATOR_REVIEW": "automated source demotions/recoveries (§U1)",
            "note": "KYC identity decisions are never sampled — exhaustive "
                    "by design (§Willison, the named new constraint)",
        },
    }


# ------------------------------------------------------------- §U1 health --
@router.get("/source-health")
async def source_health(db=Depends(get_db), user=Depends(current_user)):
    """Stored per-source auto scorecards (computed after every ingest run)."""
    return {"sources": db.all_source_meta(),
            "policy": {"demote": "freshness SLA breach OR composite "
                                 "health < 0.45",
                       "recover": "SLA met AND health ≥ 0.65",
                       "weights": {"freshness": 0.45,
                                   "contradiction": 0.30,
                                   "copy_chain": 0.25},
                       "curator_flow": "humans review demotions/recoveries "
                                       "only — never steady state"}}


@router.post("/source-health/refresh")
async def source_health_refresh(db=Depends(get_db), user=Depends(current_user)):
    """On-demand recompute — demotes/recovers sources with curator audit."""
    from ...scraper.source_health import score_sources
    return {"scorecard": [h.as_dict() for h in score_sources(db)]}
