"""Shared dependencies — spec Parts 1.4 & 13.2.

Demo profile: a single demo tenant. Production profile (Part 13): API keys
(sk-...) resolve to TenantContext with org scoping + rate limits; every
repository query is hard-scoped by org_id.
"""
from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException

from ..store.db import EvidenceStore, get_store

# Part 13.6 demo enterprise key (documented in README/.env.example)
DEMO_API_KEY = "sk_demo_threathunter360"


def get_db() -> EvidenceStore:
    return get_store()


async def current_user(x_api_key: str | None = Header(default=None),
                       authorization: str | None = Header(default=None),
                       x_th360_role: str | None = Header(default=None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    token = token or x_api_key
    if token is None:
        # v4.4 RBAC — demo human path: full admin within the demo profile,
        # or the (demo-only) role override header for exercising the matrix.
        from ..core.rbac import resolve_role
        return {"id": "demo-user", "plan": "demo", "scopes": {"*"},
                "role": resolve_role(is_demo_path=True,
                                     header_role=x_th360_role),
                "auth_class": "demo"}
    if token == DEMO_API_KEY:
        from ..core.rbac import resolve_role
        return {"id": "svc-acme-fraud-team", "plan": "enterprise",
                "scopes": {"factcheck:read", "journey:assess", "kyc:verify"},
                "org_scope": "acme-corp/fraud-team",
                # enterprise demo key holds the governance role — may decide
                # approvals and export SIEM, may NOT manage connectors/agents
                "role": resolve_role(is_demo_path=False,
                                     api_key_role="governance"),
                "auth_class": "api_key"}
    # unknown keys → 401 rather than silent acceptance (§25 least privilege)
    raise HTTPException(status_code=401,
                        detail="Invalid API key. Use the documented demo key "
                               "or register for enterprise access (Part 13).")


def api_key_hash(key: str) -> str:  # Part 13.1 — never store raw keys
    return hashlib.sha256(key.encode()).hexdigest()
