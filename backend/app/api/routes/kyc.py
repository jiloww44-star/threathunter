"""KYC Verification endpoint — spec Parts 3.4 / 5."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ...api.deps import current_user, get_db
from ...config import SEED_ROOT
from ...core.kyc import verify_identity
from ...models.schemas import KYCResponse, KYCVerifyRequest

router = APIRouter(prefix="/api/v1/kyc", tags=["KYC Verification"])


@router.post("/verify", response_model=KYCResponse)
async def verify(req: KYCVerifyRequest, db=Depends(get_db),
                 user=Depends(current_user)):
    return await verify_identity(req, db)


@router.get("/fixtures")
async def kyc_fixtures(user=Depends(current_user)):
    """Demo profile: sample document extractions from the seed pack (Part 10)
    so the 6-step flow can be exercised without a camera/upload."""
    path = SEED_ROOT / "fixtures" / "kyc_documents.json"
    if not path.exists():
        return {"fixtures": []}
    data = json.loads(path.read_text())
    # §25 — never expose a raw document number; hashes only (already hashed)
    return {"fixtures": data}


@router.get("/queue")
async def review_queue(db=Depends(get_db), user=Depends(current_user)):
    """§27 human-in-the-loop queue (analyst console, Part 18)."""
    return {"queue": db.review_queue()}
