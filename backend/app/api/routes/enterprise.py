"""Enterprise plane routes — v4.4 (§73 Enterprise).

GET  /api/v1/ops/whoami               current identity + role + auth_class
POST /api/v1/ops/retention/apply      admin — retention sweeper (dry_run def.)
GET  /api/v1/ops/siem/export          governance+ — NDJSON audit/event export
POST /api/v1/ops/connectors           admin — register (PENDING approval)
GET  /api/v1/ops/connectors           read — connector registry
POST /api/v1/ops/connectors/{id}/retire  admin — retire

RBAC is enforced here via core.rbac.require_role. API-key callers hold the
role borne by their key; the demo human path is admin-with-disclosure or
the X-TH360-Role demo override — documented, never a production promise.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...api.deps import current_user, get_db
from ...core import connectors, rbac, retention

router = APIRouter(prefix="/api/v1", tags=["Enterprise Plane v4.4"])


@router.get("/ops/whoami")
async def whoami(user=Depends(current_user)):
    """Honest identity: id, role, auth class, and the role's static
    permission floor — the same keys every RBAC denial names."""
    role = user.get("role", "viewer")
    return {"id": user.get("id"), "role": role,
            "auth_class": user.get("auth_class"),
            "org_scope": user.get("org_scope"),
            "permissions_granted": sorted(
                p for p, need in rbac.PERMISSIONS.items()
                if rbac.role_rank(role) >= rbac.role_rank(need)),
            "roles_vocabulary": list(rbac.ROLES),
            "note": ("Demo profile role source: demo human = admin (or "
                     "X-TH360-Role demo override); API keys carry the role "
                     "declared for the key and cannot self-elevate (§25).")}


class RetentionRequest(BaseModel):
    dry_run: bool = True
    policy: dict | None = None


@router.post("/ops/retention/apply")
async def apply_retention(req: RetentionRequest, db=Depends(get_db),
                          user=Depends(current_user)):
    """Retention sweeper — admin role required; dry_run by default (§20)."""
    rbac.require_role(user, "retention.apply")
    actor = user.get("id", "retention-admin")
    return retention.apply_retention(db, policy=req.policy,
                                     dry_run=req.dry_run, actor=actor)


_EVENTS_CLASS = (
    ("event:", "platform_event"),
    ("policy:", "policy_decision"),
    ("safety_event:", "safety"),
    ("consent_", "privacy"),
    ("retention:", "lifecycle"),
    ("connector_", "connector"),
    ("plan_", "plan_review"),
    ("id_audit_", "identity_audit"),
)


def _classify(action: str) -> str:
    for prefix, cat in _EVENTS_CLASS:
        if action.startswith(prefix):
            return cat
    return "governance"


@router.get("/ops/siem/export", response_class=Response)
async def siem_export(since_hours: int = 24, limit: int = 500,
                      db=Depends(get_db), user=Depends(current_user)):
    """SIEM/SOAR feed: NDJSON audit/event export with taxonomy + provenance.
    Set TH360_SIEM_KEY to attach an HMAC signature header (demo of the
    signed-export contract; key management stays with the tenant)."""
    rbac.require_role(user, "siem.export")
    rows = db.audit_trail(limit=max(1, min(limit, 5000)))
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=since_hours)).isoformat()
    rows = [r for r in rows if r.get("created_at", "") >= cutoff] or rows
    lines = []
    for r in rows:
        action = r.get("action", "")
        lines.append(json.dumps({
            "ts": r.get("created_at"), "actor": r.get("actor"),
            "action": action, "decision": r.get("decision"),
            "detail": r.get("detail"),
            "policy_version": r.get("policy_version"),
            "taxonomy_class": _classify(action),
            "source": "threathunter360.audit_trail",
            "export_version": "siem/4.4.0"}))
    payload = "\n".join(lines) + ("\n" if lines else "")
    headers = {"X-Th360-Record-Count": str(len(lines)),
               "X-Th360-Source": "audit_trail (append-only)",
               "X-Th360-Since-Hours": str(since_hours)}
    key = os.getenv("TH360_SIEM_KEY")
    if key:
        sig = hmac.new(key.encode(), payload.encode(),
                       hashlib.sha256).hexdigest()
        headers["X-Th360-Signature"] = f"sha256={sig}"
    return Response(content=payload, media_type="application/x-ndjson",
                    headers=headers)


class ConnectorRegister(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    kind: str
    base_url: str = Field(min_length=8, max_length=300)
    auth_env: str | None = None


@router.post("/ops/connectors")
async def register_connector(req: ConnectorRegister, db=Depends(get_db),
                             user=Depends(current_user)):
    """Admin — register a connector (PENDING_APPROVAL; activation mints an
    approval and flips ACTIVE only from the grant hook)."""
    rbac.require_role(user, "connectors.manage")
    return connectors.register(db, name=req.name, kind=req.kind,
                               base_url=req.base_url, auth_env=req.auth_env,
                               actor=user.get("id", "operator"))


@router.get("/ops/connectors")
async def list_connectors(db=Depends(get_db), user=Depends(current_user)):
    return connectors.list_all(db)


@router.post("/ops/connectors/{connector_id}/retire")
async def retire_connector(connector_id: str, db=Depends(get_db),
                           user=Depends(current_user)):
    rbac.require_role(user, "connectors.manage")
    return connectors.retire(db, connector_id,
                             actor=user.get("id", "operator"))
