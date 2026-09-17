"""OSINT Console — v4.0 §73 V1.5 (dork builder · forensics) + V1 Evidence Locker.

POST /api/v1/osint/dorks            methodology dork builder (generation only)
POST /api/v1/osint/forensics/media  SENTINEL A-04 media forensics
POST /api/v1/osint/live/crtsh       v4.5 first REAL source — PASSIVE CT
                                    observation through the §80 registry
GET  /api/v1/evidence/locker        search the evidence store with provenance

Honest-degradation contract (§20): the dork builder NEVER executes syntax
against a search engine; forensics without a recognizable demo fixture
degrades to UNVERIFIED (§1.9: unverifiable ≠ fake); the Locker serves only
what is actually stored.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...api.deps import current_user, get_db
from ...core import dork_builder, investigation, live_sources, rbac
from ...swarm.agents import sentinel
from ...swarm import registry

router = APIRouter(prefix="/api/v1", tags=["OSINT Console v4.1"])


class DorkRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=300)
    subject: str = Field(min_length=1, max_length=300)
    subject_type: str = "domain"
    search_engine: str = "google"
    investigation_id: str | None = None  # §63 scope binding (optional)


@router.post("/osint/dorks")
async def build_dorks(req: DorkRequest, db=Depends(get_db)):
    """Spec: `{objective, search_engine, syntax, intended_use, risk_level,
    authorized_scope, source, last_verified}` per dork + what/why/expected/
    boundaries explanation."""
    scope = "open public tier"
    if req.investigation_id:
        # generation consumes no external family — lifecycle gate only
        # (exists, OPEN, unexpired): §76 applies to work done in a case's name.
        inv = investigation.authorize_run(db, req.investigation_id,
                                          branches=[],
                                          user_id="osint-console")
        scope = inv["scope"] or "open public tier"
    out = dork_builder.build_dorks(req.objective, req.subject,
                                   req.subject_type,
                                   authorized_scope=scope,
                                   search_engine=req.search_engine)
    db.audit(actor="osint-console", action="dork_set_generated",
             decision="ALLOW",
             detail=f"{out['count']} dork(s) for {req.subject_type}:"
                    f"{req.subject[:80]} engine={out['dorks'][0]['search_engine'] if out['count'] else req.search_engine}"
                    + (f" inv={req.investigation_id}"
                       if req.investigation_id else ""),
             policy_version=registry.POLICY_VERSION)
    out["investigation_id"] = req.investigation_id
    return out


class MediaForensicsRequest(BaseModel):
    media_ref: str | None = None
    link_to_investigation: str | None = None


@router.post("/osint/forensics/media")
async def media_forensics(req: MediaForensicsRequest, db=Depends(get_db)):
    """A-04 SENTINEL forensic sub-agent, exposed directly for the V1.5
    console. Degrades to UNVERIFIED without a recognizable fixture (§1.9)."""
    result = sentinel.analyze_media(req.media_ref)
    db.audit(actor="osint-console", action="media_forensics",
             decision="ALLOW",
             detail=f"media_ref={str(req.media_ref)[:60]} → "
                    f"{result['assessment']} ({result['confidence']})",
             policy_version=registry.POLICY_VERSION)
    if req.link_to_investigation and req.media_ref:
        investigation.link(db, req.link_to_investigation, "evidence",
                           f"media:{req.media_ref}", actor="osint-console")
    return result


@router.get("/evidence/locker")
async def evidence_locker(q: str | None = None, source: str | None = None,
                          limit: int = 50, db=Depends(get_db)):
    """§73 V1 Evidence Locker — browse the store with provenance first
    (source, authority, fetched/published times on every row)."""
    rows = db.all_evidence()
    if source:
        rows = [r for r in rows
                if source.lower() in (r.get("source_id") or "").lower()]
    if q:
        needle = q.lower()
        rows = [r for r in rows
                if needle in (r.get("title") or "").lower()
                or needle in (r.get("excerpt") or "").lower()
                or needle in (r.get("url") or "").lower()]
    rows.sort(key=lambda r: r.get("fetched_at") or "", reverse=True)
    limit = max(1, min(limit, 200))
    items = [{
        "id": r["id"], "source_id": r["source_id"], "url": r.get("url"),
        "title": r.get("title"), "excerpt": (r.get("excerpt") or "")[:240],
        "reliability": r.get("reliability"),
        "authority": r.get("authority"),
        "independence_group": r.get("independence_group"),
        "published_at": r.get("published_at"),
        "fetched_at": r.get("fetched_at"),
        "content_hash": (r.get("content_hash") or "")[:12],
    } for r in rows[:limit]]
    return {"items": items, "count": len(items),
            "total_stored": len(db.all_evidence()),
            "note": ("Provenance-first locker: every row carries source, "
                     "authority and fetch time (§17). Absence here = "
                     "nothing stored, never a verdict (§1.9).")}


class CrtshObservationRequest(BaseModel):
    investigation_id: str = Field(min_length=4, max_length=80)
    domain: str = Field(min_length=4, max_length=253)


@router.post("/osint/live/crtsh")
async def crtsh_observation(req: CrtshObservationRequest, db=Depends(get_db),
                            user=Depends(current_user)):
    """v4.5 pilot — the first REAL source: PASSIVE Certificate Transparency
    via crt.sh, executed through the §80 connector registry.

    Gate order (each failure classified, §20): §76 living-case → §63 scope
    binding (domain must be the case subject or in its cone) → ACTIVE
    on-allowlist connector → fetch → provenance-stamped evidence row,
    linked into the case, with SourceQueried/ObservationReceived events."""
    rbac.require_role(user, "investigate.run")
    return live_sources.run_crtsh_observation(
        db, investigation_id=req.investigation_id, domain=req.domain,
        actor=user.get("id", "demo"))
