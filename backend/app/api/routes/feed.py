"""Recent Checks & Statistics — spec Part 1 (RECENT CHECKS module) + Part 4.4
monitoring metrics surface."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ...api.deps import current_user, get_db
from ...models.schemas import RecentCheck, Statistics

router = APIRouter(prefix="/api/v1/feed", tags=["Recent Checks & Statistics"])


@router.get("/recent", response_model=list[RecentCheck])
async def recent(limit: int = 10, db=Depends(get_db),
                 user=Depends(current_user)):
    rows = db.recent_checks(limit=min(limit, 50))
    return [
        RecentCheck(
            check_id=r["id"], module=r["module"], subject=r["subject"],
            outcome=r["outcome"], confidence=r["confidence"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/statistics", response_model=Statistics)
async def statistics(db=Depends(get_db), user=Depends(current_user)):
    stats = db.statistics()
    # source freshness (Part 4.4 — a stale feed must be visible, never hidden)
    freshness = {}
    with db._lock:
        rows = db._conn.execute(
            "SELECT source_id, last_success_at FROM sources_meta").fetchall()
    now = datetime.now(timezone.utc)
    for r in rows:
        lag = 0.0
        if r[1]:
            try:
                ts = datetime.fromisoformat(r[1].replace("Z", "+00:00"))
                lag = (now - ts).total_seconds() / 60
            except Exception:
                lag = -1
        else:
            lag = -1  # never succeeded
        freshness[r[0]] = round(lag, 1)
    stats["source_freshness_lag_min"] = freshness
    return stats
