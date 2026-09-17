"""Live source onboarding — v4.5 Production Pilot Readiness.

The first REAL data source enters the platform here, and it enters the way
§80 + §73 Enterprise say data sources must: **through the custom-connector
registry** (v4.4), never through a back door.

crt.sh (Certificate Transparency logs) is the pilot source by design:
  * PASSIVE collection only (§64: "public infrastructure record (technical)"
    — the lowest-sensitivity OSINT class),
  * keyless, so no §25 credential handling is exercised falsely,
  * deterministic content-hash → idempotent, chain-verifiable evidence.

Every row it stores carries the full provenance set (query, source, params,
timestamp, result hash, connector id — §68 reproducibility), and every
execution walks the same governance path as any consequential action:
living-case gate (§76) → scope binding (§63) → connector ACTIVE and
on-allowlist (§80) → SourceQueried/ObservationReceived events (§26) →
source-health telemetry (§6/§32). A failure anywhere is CLASSIFIED
(§20: what happened / what it means / what to do), never swallowed.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import httpx

from . import investigation
from .errors import PipelineError

LIVE_SOURCES_VERSION = "live-sources/4.5.0"
CRTSH_BASE_URL = "https://crt.sh"
MAX_STORED_NAMES = 100
_TIMEOUT = httpx.Timeout(12.0, connect=6.0)
_UA = {"User-Agent": "threathunter360-pilot/4.5 (+passive CT observation)"}

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}$")


# ------------------------------------------------------------------ helpers --
def normalize_domain(raw: str) -> str:
    """Strict DNS normalization — scheme/path/wildcards/port stripped, IDNA
    left as punycode. Anything that is not a plain registrable-style name is
    rejected: the query string is *scope*, and scope is a §63 object.
    IP literals are valid *subjects* but not domain scope (CT logs index
    names, not addresses)."""
    d = (raw or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].split(":")[0]
    d = d.lstrip("*.").rstrip(".")
    import ipaddress
    try:
        ipaddress.ip_address(d)
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=(f"'{d}' is an IP literal — Certificate Transparency "
                    "logs index DNS names, not addresses. Domain scope "
                    "requires a DNS name (§63)."))
    except ValueError:
        pass  # not an IP — continue with domain validation
    if not _DOMAIN_RE.match(d):
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=(f"'{raw}' is not a plain DNS name after normalization "
                    f"('{d}'). Scope objects must be exact, verifiable "
                    "domains — URLs, wildcards and ports are not scope (§63)."))
    return d


def _degraded(code: str, status: int, happened: str, means: str,
              todo: str) -> PipelineError:
    return PipelineError(
        code, status=status,
        detail=json.dumps({"what_happened": happened,
                           "what_it_means": means,
                           "what_to_do": todo}))


# -------------------------------------------------------------- live fetch ---
def _http_get(url: str) -> httpx.Response:
    return httpx.get(url, timeout=_TIMEOUT, headers=_UA, follow_redirects=True)


def fetch_crtsh_subdomains(domain: str, *, http_get=None) -> dict:
    """PASSIVE Certificate Transparency read for `*.domain` via crt.sh.

    `http_get` is injectable for tests — the governance flow around the fetch
    is what this module exists to prove; the wire call itself is one line.
    """
    get = http_get or _http_get
    url = f"{CRTSH_BASE_URL}/?q=%25.{domain}&output=json"
    try:
        resp = get(url)
    except httpx.TimeoutException as exc:
        raise _degraded("SOURCE_TIMEOUT", 503,
                        f"crt.sh did not answer within {_TIMEOUT.connect}s/"
                        f"{_TIMEOUT.read}s ({type(exc).__name__}).",
                        "the CT source is slow or down; no observation was "
                        "made and none is claimed",
                        "retry later; staleness is tracked in the Source "
                        "Health Monitor") from exc
    except httpx.HTTPError as exc:
        raise _degraded("SOURCE_UNREACHABLE", 503,
                        f"network error reaching crt.sh: {exc!r}",
                        "no observation was made",
                        "check egress policy; the platform never fabricates "
                        "a response (§20)") from exc
    if resp.status_code == 429:
        raise _degraded("SOURCE_THROTTLED", 429,
                        "crt.sh rate-limited the query (HTTP 429).",
                        "fair-use ceiling hit; no observation was made",
                        "back off and retry; repeated 429s flip the connector "
                        "RED in source health")
    if resp.status_code != 200:
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        f"crt.sh answered HTTP {resp.status_code}.",
                        "upstream fault; no observation was made",
                        "retry later or check crt.sh status")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        "crt.sh returned a 200 with non-JSON body.",
                        "parser/source drift — treated as UNVERIFIED (§1.9), "
                        "not guessed",
                        "capture the body and review the parser before "
                        "trusting downstream checks") from exc
    if not isinstance(payload, list):
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        f"unexpected crt.sh payload type {type(payload).__name__}.",
                        "shape drift — UNVERIFIED",
                        "review parser; do not auto-trust")
    names: set[str] = set()
    for row in payload:
        for piece in str(row.get("name_value", "")).split("\n"):
            n = piece.strip().lower()
            if n and " " not in n and "@" not in n:
                names.add(n)
    ordered = sorted(names)
    return {"names": ordered[:MAX_STORED_NAMES],
            "observed_total": len(ordered),
            "truncated": len(ordered) > MAX_STORED_NAMES,
            "query_url": url}


# ------------------------------------------------------------ governed flow --
def _active_crtsh_connector(store) -> dict | None:
    for c in store.connector_list():
        if c["status"] != "ACTIVE":
            continue
        if c["name"].lower() == "crtsh" or "crt.sh" in c["base_url"]:
            return c
    return None


def run_crtsh_observation(store, *, investigation_id: str, domain: str,
                          actor: str) -> dict:
    """Execute one governed, evidenced, PASSIVE observation.

    Gate order is deliberate and each failure is classified:
      1. §76 lifecycle — authorize_run() (policy engine, exact error parity
         with every other consequential run: closed/expired case ⇒ 403).
      2. §63 scope binding — the queried domain must be the case subject or
         in its subdomain cone.
      3. §80 connector — an ACTIVE crt.sh connector must exist and be inside
         the case's allowed_sources when a list is declared.
    """
    inv = store.inv_get(investigation_id)
    if not inv:
        raise PipelineError("INV_NOT_FOUND", status=404,
                            detail=f"investigation {investigation_id} does "
                                   "not exist.")
    inv = investigation.authorize_run(store, investigation_id, branches=[],
                                      user_id=actor)

    d = normalize_domain(domain)
    subject = ""
    try:
        subject = normalize_domain(inv.get("subject") or "")
    except PipelineError:
        subject = ""
    if inv.get("subject_type") != "domain" or not (
            subject and (d == subject or d.endswith("." + subject))):
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=(f"scope violation (§63): investigation "
                    f"{investigation_id} is authorized for "
                    f"'{inv.get('subject_type')}:{inv.get('subject')}', not "
                    f"for domain '{d}'. Bind the query to the case's "
                    "authorized subject — no out-of-scope observation."))

    conn = _active_crtsh_connector(store)
    if not conn:
        raise PipelineError(
            "CONNECTOR_NOT_ACTIVE", status=409,
            detail=json.dumps({
                "what_happened": "no ACTIVE crt.sh connector is registered.",
                "what_it_means": ("live sources enter ONLY through the §80 "
                                  "connector registry (admin register → "
                                  "governance approval → ACTIVE). The pilot "
                                  "runbook seeds it in two calls."),
                "what_to_do": ("POST /api/v1/enterprise/connectors "
                               "{name: crtsh, kind: C_data_api, base_url: "
                               "https://crt.sh} as admin, then approve the "
                               "minted approval as governance.")}))
    allowed = inv.get("allowed_sources") or []
    if allowed and conn["name"] not in allowed and "crt.sh" not in allowed:
        raise PipelineError(
            "ACTION_DENIED", status=403,
            detail=(f"connector '{conn['name']}' is not in this case's "
                    f"allowed_sources {allowed} (R-DENY-SOURCES). Widen the "
                    "case policy or register a case-scoped connector."))

    health_id = f"connector:{conn['name']}"
    store.audit(actor=actor, action="event:SourceQueried",
                decision="ALLOW",
                detail=f"crt.sh CT query for *.{d} on {investigation_id} "
                       f"via {conn['id']}",
                policy_version=LIVE_SOURCES_VERSION)
    t0 = datetime.now(timezone.utc)
    try:
        result = fetch_crtsh_subdomains(d)
    except PipelineError as exc:
        store.upsert_source_meta(
            {"id": health_id, "reliability": "UNKNOWN",
             "authority": "SECONDARY",
             "independence_group": health_id}, ok=False,
            error=f"{exc.code}: {str(exc.detail)[:160]}")
        # §6/§32 honesty: a connector whose live fetch is failing is NOT
        # "ACTIVE-healthy" — write the auto scorecard so the monitor and
        # the v4.3 assurance sweep both see DEGRADED with the cause.
        store.update_source_health(
            health_id, 0.5,
            f"live fetch failed {exc.code} at "
            f"{datetime.now(timezone.utc).isoformat()[:19]}Z — "
            "see audit event:SourceQueried (DENY)")
        store.audit(actor=actor, action="event:SourceQueried",
                    decision="DENY",
                    detail=f"crt.sh fetch failed classified {exc.code}: "
                           f"{str(exc.detail)[:200]}",
                    policy_version=LIVE_SOURCES_VERSION)
        raise

    names_blob = "\n".join(result["names"])
    result_hash = hashlib.sha256(names_blob.encode()).hexdigest()
    fetched_at = t0.isoformat()
    from ..scraper.models import RawEvidence  # local: avoid scraper import cycle
    raw = RawEvidence(
        source_id=health_id,
        url=result["query_url"],
        fetched_at=fetched_at,
        content_hash=result_hash,
        raw_text=(f"PASSIVE CT observation for *.{d}: "
                  f"{result['observed_total']} unique name(s).\n"
                  + "\n".join(result["names"][:10])),
        metadata={
            "collection": "PASSIVE — Certificate Transparency logs (crt.sh)",
            "osint_class": "§64 public infrastructure record (technical)",
            "query_domain": d,
            "investigation_id": investigation_id,
            "connector_id": conn["id"],
            "observed_total": result["observed_total"],
            "truncated": result["truncated"],
            "names": result["names"],
            "result_hash": result_hash,
            "reliability": "HIGH",       # CT logs: append-only, signed
            "authority": "PRIMARY",      # the log itself is the record
            "independence_group": health_id,
            "pii_note": ("infrastructure identifiers only; no personal data "
                         "collected (§61)"),
        })
    existing = store.evidence_id_by_hash(health_id, result_hash)
    if existing:
        evidence_id, new_row = existing, False
    else:
        store.insert_evidence(raw, [])
        evidence_id = store.evidence_id_by_hash(health_id, result_hash)
        new_row = evidence_id is not None

    linked = False
    if evidence_id:
        have = {(l["kind"], l["ref_id"])
                for l in store.inv_links_for(investigation_id)}
        if ("evidence", evidence_id) not in have:
            import uuid as _uuid
            store.inv_link(f"lnk-{str(_uuid.uuid4())[:10]}",
                           investigation_id, "evidence", evidence_id)
            linked = True

    store.upsert_source_meta(
        {"id": health_id, "reliability": "HIGH", "authority": "PRIMARY",
         "independence_group": health_id}, ok=True)
    store.update_source_health(
        health_id, 1.0,
        f"last live observation OK ({result['observed_total']} names) at "
        f"{fetched_at[:19]}Z")
    store.audit(
        actor=actor, action="event:ObservationReceived", decision="ALLOW",
        detail=(f"{result['observed_total']} CT name(s) for *.{d}; "
                f"new_evidence={new_row} hash={result_hash[:16]}… "
                f"evidence={evidence_id}"),
        policy_version=LIVE_SOURCES_VERSION)

    return {
        "investigation_id": investigation_id,
        "domain": d,
        "connector": {"id": conn["id"], "name": conn["name"],
                      "kind": conn["kind"]},
        "observed_total": result["observed_total"],
        "names": result["names"],
        "truncated": result["truncated"],
        "new_evidence": new_row,
        "newly_linked": linked,
        "evidence_id": evidence_id,
        "result_hash": result_hash,
        "osint_class": "§64 public infrastructure record (technical) — PASSIVE",
        "provenance": {"source": "crt.sh (Certificate Transparency)",
                       "query_url": result["query_url"],
                       "fetched_at": fetched_at,
                       "reproducibility": ("§68: re-run the same query_url; "
                                           "the platform's stored row is "
                                           "committed by content hash")},
        "degraded": None,
    }
