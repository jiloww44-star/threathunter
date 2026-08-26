"""Fact Check endpoint — spec Part 1.4.

POST /api/v1/factcheck        → full inductive pipeline, persists for feed
GET  /api/v1/factcheck/{id}   → earlier result
POST /api/v1/factcheck/{id}/reassess → §1.10 continuous re-testing against
                                       newly ingested evidence
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ...api.deps import current_user, get_db
from ...models.schemas import FactCheckRequest, FactCheckResponse
from ...core.reasoning_engine import ReasoningEngine

router = APIRouter(prefix="/api/v1/factcheck", tags=["Fact Checker"])


@router.post("", response_model=FactCheckResponse)
async def check_fact(req: FactCheckRequest,
                     db=Depends(get_db), user=Depends(current_user)):
    claim = req.claim.strip()
    if not claim:
        raise HTTPException(status_code=422, detail="Claim cannot be empty")
    engine = ReasoningEngine(db)
    # Persist inline in demo profile (keeps Recent Checks immediate);
    # production runs persist via BackgroundTasks/Celery (Part 4).
    return await engine.run_full_pipeline(claim, user=user.get("id", "demo"))


@router.get("/{check_id}", response_model=FactCheckResponse)
async def get_check(check_id: str, db=Depends(get_db),
                    user=Depends(current_user)):
    row = db.get_check(check_id)
    if not row or row["module"] != "factcheck":
        raise HTTPException(status_code=404, detail="Check not found")
    import json
    data = json.loads(row["response_json"])
    data["check_id"] = check_id
    data["graph_url"] = f"/api/v1/graph/case/{check_id}"
    return data


@router.post("/{check_id}/reassess", response_model=FactCheckResponse)
async def reassess(check_id: str, db=Depends(get_db),
                   user=Depends(current_user)):
    """§1.10 — new evidence automatically triggers re-testing and confidence
    updates. Demo scenario 5 exercises this end-to-end."""
    engine = ReasoningEngine(db)
    result = await engine.reassess_case(check_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return result
