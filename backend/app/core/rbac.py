"""RBAC — v4.4 Enterprise plane (§73 Enterprise: SSO/RBAC).

Closed role set with a deterministic permission matrix (§54). SSO itself
is documented-only in the demo profile (no IdP in the sandbox) — the RBAC
core is real: role resolution happens in api/deps.current_user and every
governance surface enforces via require_role(). The demo-user path carries
a role override header for *demonstrating* the matrix; API-key callers can
never self-elevate (their role comes from the key map).

Roles (least→most privilege):  viewer < analyst < governance < admin
"""
from __future__ import annotations

from .errors import PipelineError

ROLES = ("viewer", "analyst", "governance", "admin")
_ROLE_RANK = {r: i for i, r in enumerate(ROLES)}

# permission → minimum role. Derived from the §73 plane wording:
# viewers read; analysts investigate; governance approves & sweeps;
# admins manage agents/connectors/exports.
PERMISSIONS: dict[str, str] = {
    "read": "viewer",
    "investigate.run": "analyst",          # goals, plans, cases, dorks
    "factcheck.assess": "analyst",
    "approvals.decide": "governance",
    "assurance.sweep": "governance",
    "siem.export": "governance",
    "retention.apply": "admin",
    "agents.register": "analyst",
    "agents.promote": "admin",
    "connectors.manage": "admin",
    "inventory.read": "governance",
}


def role_rank(role: str) -> int:
    return _ROLE_RANK.get(role, -1)


def resolve_role(*, is_demo_path: bool, api_key_role: str | None = None,
                 header_role: str | None = None) -> str:
    """§20-explicit resolution: API keys take their DECLARED role and may not
    override; the demo human path defaults to admin-with-disclosure or the
    header role (demo-only self-override, plainly documented)."""
    if not is_demo_path:
        return api_key_role if api_key_role in ROLES else "viewer"
    if header_role in ROLES:
        return header_role
    return "admin"  # demo profile: full-access human, declared everywhere


def permits(user: dict, permission: str) -> bool:
    needed = PERMISSIONS.get(permission)
    if needed is None:
        return True  # unmapped permission = open (read-level default)
    return role_rank(user.get("role", "viewer")) >= role_rank(needed)


def require_role(user: dict, permission: str) -> None:
    """403 with the classified shape when the role is below the required
    floor — the denial says what happened / what it means / what to do."""
    if permits(user, permission):
        return
    needed = PERMISSIONS[permission]
    raise PipelineError(
        "ACTION_DENIED", status=403,
        detail=(f"role '{user.get('role', 'viewer')}' cannot '{permission}' "
                f"(requires ≥ '{needed}'). Enterprise plane RBAC; request "
                "elevation from your tenant admin (§73)."))
