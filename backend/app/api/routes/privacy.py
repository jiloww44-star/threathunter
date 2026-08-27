"""Privacy & Personalization API — v3.0 spec §5.3 (consent ledger) + §3.4
(personalization within evidence bounds).

Consent is immutable and hash-chained; preferences never touch scoring —
see core/personalization.py for the load-bearing rule.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...api.deps import get_db
from ...core import personalization, privacy
from ...core.errors import PipelineError

router = APIRouter(prefix="/api/v1", tags=["Privacy & Personalization"])


class ConsentRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    purpose: str
    state: str  # granted | withdrawn
    detail: str = ""


class PrefsRequest(BaseModel):
    watchlists: list[str] | None = None
    journey_priority: str | None = None
    notify_tolerance: str | None = None
    output_format: str | None = None


@router.post("/privacy/consent")
def grant_or_withdraw(req: ConsentRequest, db=Depends(get_db)):
    """§5.3 — record a consent event (hash-chained, append-only)."""
    try:
        return privacy.record(db, user_id=req.user_id, purpose=req.purpose,
                              state=req.state, detail=req.detail)
    except ValueError as e:
        raise PipelineError("INVALID_CONSENT", status=400, detail=str(e))


@router.get("/privacy/consent/{user_id}")
def consent_state(user_id: str, db=Depends(get_db)):
    return {"user_id": user_id,
            "purposes": {p: privacy.current_state(db, user_id, p)
                         for p in privacy.PURPOSES},
            "ledger": db.consent_ledger(user_id=user_id, limit=50)}


@router.get("/privacy/ledger")
def audit_ledger(db=Depends(get_db)):
    """Auditor view: full ledger + one-call chain verification (§5.3)."""
    return {"verification": privacy.verify_chain(db),
            "entries": db.consent_ledger(limit=200),
            "purposes": list(privacy.PURPOSES)}


@router.get("/prefs/{user_id}")
def get_prefs(user_id: str, db=Depends(get_db)):
    """§3.4 — effective preferences (defaults when unset/unconsented)."""
    return personalization.get(db, user_id)


@router.put("/prefs/{user_id}")
def save_prefs(user_id: str, req: PrefsRequest, db=Depends(get_db)):
    """§3.4 + §5.3 — consent-gated write (CONSENT_REQUIRED when not granted)."""
    return personalization.save(
        db, user_id, watchlists=req.watchlists,
        journey_priority=req.journey_priority,
        notify_tolerance=req.notify_tolerance,
        output_format=req.output_format)
