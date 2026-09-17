"""Investigation Core API — v4.0 §2/§26/§63.

POST /api/v1/investigations            create (carries the §63 authorization)
GET  /api/v1/investigations            list (per user when user_id given)
GET  /api/v1/investigations/{id}       detail + §5 evidence-chain links
POST /api/v1/investigations/{id}/link  link an artifact (tree/evidence/watch)
POST /api/v1/investigations/{id}/close close — §26 InvestigationClosed event

Every mutation emits a §26 event onto the append-only audit trail. Runs
bound to an investigation are gated by core.investigation.authorize_run
(§35: LLM proposes, policy disposes; §76: no action without authorization).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...api.deps import get_db
from ...core import investigation

router = APIRouter(prefix="/api/v1/investigations", tags=["Investigation Core v4"])


class InvestigationCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=500)
    subject_type: str
    subject: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=3, max_length=300)
    authority: str = "public_research"
    scope: str = Field(default="", max_length=300)
    allowed_sources: list[str] | None = None   # []/null = open public tier
    expires_days: int = 30
    user_id: str = "demo"


class LinkRequest(BaseModel):
    kind: str          # ops_tree | evidence | watch | finding | verification_case
    ref_id: str
    user_id: str = "operator"


class CloseRequest(BaseModel):
    reason: str = Field(default="", max_length=300)
    user_id: str = "operator"


@router.post("")
async def create_investigation(req: InvestigationCreate, db=Depends(get_db)):
    """§2+§63 — open an investigation with its authorization object."""
    return investigation.create(
        db, objective=req.objective, subject_type=req.subject_type,
        subject=req.subject, purpose=req.purpose, authority=req.authority,
        scope=req.scope, allowed_sources=req.allowed_sources,
        expires_days=req.expires_days, user_id=req.user_id)


@router.get("")
async def list_investigations(user_id: str | None = None, limit: int = 50,
                              db=Depends(get_db)):
    return {"investigations": db.inv_list(user_id=user_id, limit=limit)}


@router.get("/{inv_id}")
async def get_investigation(inv_id: str, db=Depends(get_db)):
    return investigation.get(db, inv_id)


@router.post("/{inv_id}/link")
async def link_artifact(inv_id: str, req: LinkRequest, db=Depends(get_db)):
    """§5 evidence chain — attach an artifact to this investigation."""
    return investigation.link(db, inv_id, req.kind, req.ref_id,
                              actor=req.user_id)


@router.post("/{inv_id}/close")
async def close_investigation(inv_id: str, req: CloseRequest,
                              db=Depends(get_db)):
    """§26 — InvestigationClosed; further bound runs will be refused (§76)."""
    return investigation.close(db, inv_id, actor=req.user_id,
                               reason=req.reason)
