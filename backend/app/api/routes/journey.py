"""Journey Advisor endpoint — spec Part 1.6."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...api.deps import current_user, get_db
from ...models.schemas import JourneyRequest, JourneyResponse
from ...core.journey import assess_journey

router = APIRouter(prefix="/api/v1/journey", tags=["Journey Advisor"])


@router.post("/assess", response_model=JourneyResponse)
async def assess(req: JourneyRequest, db=Depends(get_db),
                 user=Depends(current_user)):
    # §14-15: missing-but-material fields → CLARIFICATION_NEEDED with
    # context_retained; never restart the form.
    return await assess_journey(req)
