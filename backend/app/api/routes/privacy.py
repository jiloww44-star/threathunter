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
    region = privacy.get_region(db, user_id)
    return {"user_id": user_id,
            "region": region,
            "region_notice": privacy.REGION_NOTICE,
            "purposes": {p: privacy.current_state(db, user_id, p)
                         for p in privacy.PURPOSES},
            "effective": {p: privacy.effective_consent(db, user_id, p)
                          for p in privacy.PURPOSES},
            "ledger": db.consent_ledger(user_id=user_id, limit=50)}


class RegionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    region: str


@router.get("/privacy/regions")
def list_regions():
    """v3.4 — declared regions + their default modes (red-team #9)."""
    return {"regions": {k: {"label": v["label"], "mode": v["mode"],
                            "defaults": v["defaults"]}
                        for k, v in privacy.REGIONS.items()},
            "notice": privacy.REGION_NOTICE}


@router.put("/privacy/region")
def set_user_region(req: RegionRequest, db=Depends(get_db)):
    """v3.4 — set the user's region (scopes consent DEFAULTS only; explicit
    ledger decisions always win, biometrics stay opt-in everywhere)."""
    try:
        return privacy.set_region(db, req.user_id, req.region)
    except ValueError as e:
        raise PipelineError("INVALID_CONSENT", status=400, detail=str(e))


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


@router.delete("/data/user/{user_id}")
def delete_my_data(user_id: str, db=Depends(get_db)):
    """v3.2 "Manage Data" exit ramp (review blocker E + risk #9, red-team
    #12): erase the user's personal data with a clear, honest scope note.
    Consent ledger stays intact by design — it IS the audit proof of
    consent choices, holds only pseudonymous ids, and its retention is the
    declared §5.3 policy; everything else about the user goes."""
    counts = db.delete_user_artifacts(user_id)
    db.audit(actor=user_id, action="safety_event:user_data_deleted",
             decision="ALLOW",
             detail=f"personal data deleted for {user_id}: {counts}",
             policy_version="sovereign-policy/3.0.0")
    return {"user_id": user_id, "deleted": True, **counts,
            "scope": ["preferences", "watchlist_state", "journey_watches"],
            "retained": [
                "consent_ledger entries (§5.3 audit proof, pseudonymous)",
                "system notifications (no personal content)",
            ],
            "cortex_note": ("Purge any live chat context separately: POST "
                            "/api/v1/cortex/session/{id}/purge.")}


@router.put("/prefs/{user_id}")
def save_prefs(user_id: str, req: PrefsRequest, db=Depends(get_db)):
    """§3.4 + §5.3 — consent-gated write (CONSENT_REQUIRED when not granted)."""
    return personalization.save(
        db, user_id, watchlists=req.watchlists,
        journey_priority=req.journey_priority,
        notify_tolerance=req.notify_tolerance,
        output_format=req.output_format)


class IdAuditRequest(BaseModel):
    identity: str = Field(min_length=3, max_length=254)
    identifier_type: str = "auto"      # auto | email | domain | phone
    domain: str = ""
    phone: str = ""
    consent_granted: bool = True


@router.post("/privacy/id-audit")
def id_audit(req: IdAuditRequest, db=Depends(get_db)):
    """Blueprint v5.2 §5 — `/id_audit_l1`: L1 carrier/domain integrity audit.
    Read-only; results are hedged indicators, never verdicts on persons."""
    from ...swarm.agents import voyager
    result = voyager.id_audit_l1(
        identity=req.identity, identifier_type=req.identifier_type,
        domain=req.domain, phone=req.phone,
        consent_granted=req.consent_granted)
    db.audit("AUDITOR", "id_audit_l1", "LOGGED",
             f"L1 audit {req.identifier_type} on {req.identity[:40]} → "
             f"{result['verdict']}",
             policy_version="sovereign-policy/3.3.0")
    return result


@router.get("/privacy/compliance-index")
def compliance_index(db=Depends(get_db)):
    """Blueprint v5.2 §6.C — the Govern tab's Compliance Index."""
    from ...core import compliance
    return compliance.compute_index(db)
