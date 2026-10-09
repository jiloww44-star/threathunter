"""Custom Connectors — v4.4 Enterprise plane (§73: custom connectors; §80
source map, types A Methodology · B Discovery · C Data APIs · D Research
distribution).

Broker-gated by design: registration is ADMIN-only (RBAC), activation is
an **approval-engine flow** (v4.2): the connector registers PENDING, mints
an ApprovalRequested, and flips ACTIVE only from the grant hook via the
durable effect registry — a connector never executes (and never claims to)
before governance says yes.

Secret discipline (§25): `auth_env` is the NAME of an environment variable
holding the credential — the secret itself is rejected if pasted, never
stored. Active connectors appear in the Source Health Monitor from day one
under `connector:<name>` (§6/§32).
"""
from __future__ import annotations

import uuid

from . import approvals
from .errors import PipelineError

CONNECTOR_KINDS = ("A_methodology", "B_discovery", "C_data_api",
                   "D_research_distribution")


def _valid_secret_ref(auth_env: str | None) -> None:
    if not auth_env:
        return
    if ("sk-" in auth_env or "key" in auth_env.lower() and "=" in auth_env
            or len(auth_env) > 64 or " " in auth_env):
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=("auth_env must be the NAME of an environment variable "
                    "(e.g. SHODAN_API_KEY) — the secret itself must not "
                    "enter this platform (§25)."))


def register(store, *, name: str, kind: str, base_url: str,
             auth_env: str | None, actor: str) -> dict:
    if kind not in CONNECTOR_KINDS:
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=f"kind must be one of {CONNECTOR_KINDS}")
    if not base_url.startswith(("https://", "http://")):
        raise PipelineError("INVALID_CONSENT", status=422,
                            detail="base_url must be an http(s) URL")
    _valid_secret_ref(auth_env)
    connector_id = f"conn-{str(uuid.uuid4())[:10]}"
    req = approvals.request(
        store, kind="connector_activation", subject_ref=connector_id,
        summary=f"activate connector {name} ({kind})", requester=actor,
        context={"base_url": base_url, "kind": kind, "auth_env": auth_env})
    store.connector_create(connector_id, name, kind, base_url, auth_env,
                           actor, approval_id=req["id"])
    row = store.connector_get(connector_id)
    return {**row, "approval": req}


def _activate_effect(store, row: dict) -> None:
    """Durable grant hook: flips the connector ACTIVE and mounts it in the
    Source Health Monitor. Runs ONLY on ApprovalGranted (§27/R-05)."""
    connector_id = row["subject_ref"]
    conn = store.connector_get(connector_id)
    if not conn:
        return
    store.connector_set_status(connector_id, "ACTIVE")
    store.upsert_source_meta(
        {"id": f"connector:{conn['name']}", "reliability": "UNKNOWN",
         "authority": "SECONDARY",
         "independence_group": f"connector:{conn['name']}"},
        ok=True)
    store.notify(kind="GOVERNANCE",
                 title=f"Connector activated: {conn['name']}",
                 body=(f"{connector_id} ({conn['kind']}) went ACTIVE after "
                       f"approval {row['id']}. Health is tracked as "
                       f"'connector:{conn['name']}' in the Source Health "
                       "Monitor."))


def retire(store, connector_id: str, actor: str) -> dict:
    conn = store.connector_get(connector_id)
    if not conn:
        raise PipelineError("TREE_NOT_FOUND", status=404,
                            detail=f"connector {connector_id} not found")
    store.connector_set_status(connector_id, "RETIRED")
    store.audit(actor=actor, action="connector_retired", decision="ALLOW",
                detail=f"{connector_id} ({conn['name']}) retired",
                policy_version=approvals.ENGINE_VERSION)
    return store.connector_get(connector_id)


def list_all(store) -> dict:
    return {"connectors": store.connector_list(),
            "kinds": list(CONNECTOR_KINDS),
            "note": ("Connectors are broker-gated: registration is admin"
                     "-scoped, activation mints an approval and flips ACTIVE"
                     " only on grant. Secrets never stored — only the env-var"
                     " NAME (§25).")}


# durable effect registration (v4.2+): approving by id executes this hook
approvals.register_effect("connector_activation", _activate_effect)
