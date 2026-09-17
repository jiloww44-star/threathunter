"""Live source onboarding — v4.5/v4.7.

v4.5 proved the contract with one source (crt.sh). v4.7 turns it into what
it was always meant to be: **a connector-agnostic governed observation
runner** — every live source enters ONLY through the §80 registry, walks the
same gate order (§76 living-case → §63 scope binding → ACTIVE on-allowlist
connector → fetch), stores provenance-stamped content-hash-idempotent
evidence, and leaves §26 events for both outcomes.

v4.7 also closes the §67 source-change loop: re-observing yields the same
hash ⇒ no new row (idempotent); a DIFFERENT hash ⇒ a new row that
supersedes the previous one (`supersedes` in metadata) plus
`event:ObservationChanged` on the trail — change is a first-class,
auditable fact, never an in-place overwrite (parser + source versions are
recorded on every row per §68).

Sources live today (both keyless, both PASSIVE §64 technical infra):
  * crt.sh  — Certificate Transparency name inventory for *.domain
  * RDAP    — registry-of-record state for the domain itself (registrar,
              status codes, nameservers, registration/expiration events).
              A 404 is NOT an error: unregistered is an honest observation,
              and registration later flips the change detector.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import httpx

from . import investigation
from .errors import PipelineError

LIVE_SOURCES_VERSION = "live-sources/4.7.0"
MAX_STORED_NAMES = 100
_TIMEOUT = httpx.Timeout(12.0, connect=6.0)
_UA = {"User-Agent": "threathunter360-pilot/4.7 (+passive observation)"}

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}$")


def normalize_domain(raw: str) -> str:
    """Strict DNS normalization — scheme/path/wildcards/port stripped, IDNA
    left as punycode. IP literals are valid *subjects* but not domain scope
    (CT logs and RDAP-domain index names, not addresses)."""
    d = (raw or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].split(":")[0]
    d = d.lstrip("*.").rstrip(".")
    import ipaddress
    try:
        ipaddress.ip_address(d)
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=(f"'{d}' is an IP literal — CT logs and RDAP-domain "
                    "endpoints index DNS names, not addresses. Domain scope "
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


# ---------------------------------------------------------------- the wire --
def _http_get(url: str) -> httpx.Response:
    return httpx.get(url, timeout=_TIMEOUT, headers=_UA,
                     follow_redirects=True)


def _get(url: str, source_label: str, http_get) -> httpx.Response:
    """Shared wire discipline: identical classified taxonomy for every
    live source (§20 — what happened / what it means / what to do)."""
    try:
        resp = http_get(url)
    except httpx.TimeoutException as exc:
        raise _degraded("SOURCE_TIMEOUT", 503,
                        f"{source_label} did not answer in time "
                        f"({type(exc).__name__}).",
                        "no observation was made and none is claimed",
                        "retry later; staleness is tracked in the Source "
                        "Health Monitor") from exc
    except httpx.HTTPError as exc:
        raise _degraded("SOURCE_UNREACHABLE", 503,
                        f"network error reaching {source_label}: {exc!r}",
                        "no observation was made",
                        "check egress policy; the platform never fabricates "
                        "a response (§20)") from exc
    if resp.status_code == 429:
        raise _degraded("SOURCE_THROTTLED", 429,
                        f"{source_label} rate-limited the query (HTTP 429).",
                        "fair-use ceiling hit; no observation was made",
                        "back off and retry; repeated 429s hold the "
                        "connector DEGRADED")
    if resp.status_code == 404 and source_label == "rdap.org":
        return resp   # 404 IS data for RDAP: the domain is unregistered
    if resp.status_code != 200:
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        f"{source_label} answered HTTP {resp.status_code}.",
                        "upstream fault; no observation was made",
                        "retry later or check the source status page")
    return resp


# --------------------------------------------------------------- fetchers --
def fetch_crtsh_subdomains(domain: str, *, http_get=None) -> dict:
    """PASSIVE CT-log read for `*.domain` via crt.sh."""
    get = http_get or _http_get
    url = f"https://crt.sh/?q=%25.{domain}&output=json"
    resp = _get(url, "crt.sh", get)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        "crt.sh returned a 200 with non-JSON body.",
                        "parser/source drift — treated as UNVERIFIED (§1.9)",
                        "capture the body and review the parser") from exc
    if not isinstance(payload, list):
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        f"unexpected crt.sh payload type "
                        f"{type(payload).__name__}.",
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
            "query_url": url,
            "result_payload": ordered}


def fetch_rdap_domain(domain: str, *, http_get=None) -> dict:
    """PASSIVE registry-of-record read via rdap.org bootstrap (IANA)."""
    get = http_get or _http_get
    url = f"https://rdap.org/domain/{domain}"
    resp = _get(url, "rdap.org", get)
    if resp.status_code == 404:
        # Unregistered is an observation, not an outage — and its hash is
        # stable until the day the name IS registered (change detector).
        canonical = {"registered": False}
        return {"registered": False, "registrar": None, "status": [],
                "nameservers": [], "events": [], "canonical": canonical,
                "query_url": url, "result_payload": canonical}
    try:
        payload = resp.json()
    except ValueError as exc:
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        "rdap.org returned a 200 with non-JSON body.",
                        "parser/source drift — UNVERIFIED (§1.9)",
                        "capture the body and review the parser") from exc
    if not isinstance(payload, dict) or "objectClassName" not in payload:
        raise _degraded("SOURCE_BAD_RESPONSE", 502,
                        "rdap.org payload is not an RDAP object.",
                        "shape drift — UNVERIFIED",
                        "review parser; do not auto-trust")
    registrar = None
    for ent in payload.get("entities") or []:
        roles = ent.get("roles") or []
        if "registrar" not in roles:
            continue
        vcard = ent.get("vcardArray") or []
        props = vcard[1] if len(vcard) > 1 else []
        for prop in props:
            if prop and prop[0] == "fn":
                registrar = prop[3]
                break
        if registrar:
            break
    status = sorted(str(s) for s in (payload.get("status") or []))
    nameservers = sorted(
        str(ns.get("ldhName", "")).lower()
        for ns in (payload.get("nameservers") or []) if ns.get("ldhName"))
    events = sorted({
        f"{e.get('eventAction')}:{e.get('eventDate', '')[:10]}"
        for e in (payload.get("events") or []) if e.get("eventAction")})
    canonical = {"registered": True, "registrar": registrar or "",
                 "status": status, "nameservers": nameservers,
                 "events": events}
    return {"registered": True, "registrar": registrar, "status": status,
            "nameservers": nameservers, "events": events,
            "canonical": canonical, "query_url": url,
            "result_payload": canonical,
            "source_version": " ".join(
                str(c) for c in (payload.get("rdapConformance") or [])[:2])
            or "rdap.org bootstrap"}


# ----------------------------------------------------- governed plumbing --
def _active_connector(store, *, name: str, url_hint: str) -> dict | None:
    for c in store.connector_list():
        if c["status"] != "ACTIVE":
            continue
        if c["name"].lower() == name or url_hint in c["base_url"]:
            return c
    return None


def _bind_scope(inv: dict, domain: str) -> str:
    """§63 — the queried domain must be the case subject or inside its
    subdomain cone; normalized the same way on both sides."""
    d = normalize_domain(domain)
    try:
        subject = normalize_domain(inv.get("subject") or "")
    except PipelineError:
        subject = ""
    if inv.get("subject_type") != "domain" or not (
            subject and (d == subject or d.endswith("." + subject))):
        raise PipelineError(
            "INVALID_CONSENT", status=422,
            detail=(f"scope violation (§63): investigation {inv['id']} is "
                    f"authorized for '{inv.get('subject_type')}:"
                    f"{inv.get('subject')}', not for domain '{d}'. Bind the "
                    "query to the case's authorized subject — no "
                    "out-of-scope observation."))
    return d


def persist_observation(store, *, inv: dict, conn: dict, domain: str,
                        fetch_result: dict, actor: str,
                        collection: str, osint_class: str,
                        reliability: str, authority: str,
                        summary_line: str,
                        extra_metadata: dict | None = None) -> dict:
    """§67/§68 spine shared by every live source:
    content-hash idempotency, supersede-on-change + ObservationChanged,
    parser/source versions on the row, health scorecard, §26 events."""
    health_id = f"connector:{conn['name']}"
    result_hash = hashlib.sha256(
        json.dumps(fetch_result["result_payload"], sort_keys=True
                   ).encode()).hexdigest()
    fetched_at = datetime.now(timezone.utc).isoformat()
    prev = store.latest_live_evidence(health_id, inv["id"], domain)
    changed_from = None
    if prev and prev["content_hash"] != result_hash:
        changed_from = prev["id"]   # §67: the source CHANGED — say so loudly

    from ..scraper.models import RawEvidence  # local: avoid import cycle
    metadata = {
        "collection": collection,
        "osint_class": osint_class,
        "query_domain": domain,
        "investigation_id": inv["id"],
        "connector_id": conn["id"],
        "result_hash": result_hash,
        "parser_version": LIVE_SOURCES_VERSION,
        "source_version": fetch_result.get("source_version",
                                           "upstream-of-record"),
        "reliability": reliability,
        "authority": authority,
        "independence_group": health_id,
        "pii_note": ("infrastructure identifiers only; no personal data "
                     "collected (§61)"),
        **(extra_metadata or {}),
    }
    if changed_from:
        metadata["supersedes"] = changed_from

    existing = store.evidence_id_by_hash(health_id, result_hash)
    if existing and not changed_from:
        evidence_id, new_row = existing, False
    else:
        raw = RawEvidence(
            source_id=health_id,
            url=fetch_result["query_url"],
            fetched_at=fetched_at,
            content_hash=result_hash,
            raw_text=summary_line,
            metadata=metadata)
        store.insert_evidence(raw, [])
        evidence_id = store.evidence_id_by_hash(health_id, result_hash)
        new_row = evidence_id is not None and evidence_id != existing

    linked = False
    if evidence_id:
        have = {(l["kind"], l["ref_id"])
                for l in store.inv_links_for(inv["id"])}
        if ("evidence", evidence_id) not in have:
            import uuid as _uuid
            store.inv_link(f"lnk-{str(_uuid.uuid4())[:10]}",
                           inv["id"], "evidence", evidence_id)
            linked = True

    store.upsert_source_meta(
        {"id": health_id, "reliability": reliability,
         "authority": authority, "independence_group": health_id}, ok=True)
    store.update_source_health(
        health_id, 1.0,
        f"last live observation OK at {fetched_at[:19]}Z"
        + (" — CHANGED since previous observation" if changed_from else ""))
    if changed_from:
        store.audit(actor=actor, action="event:ObservationChanged",
                    decision="ALLOW",
                    detail=(f"{conn['name']} observation for {domain} on "
                            f"{inv['id']} CHANGED: {prev['id'][:8]}… → "
                            f"{(evidence_id or '?')[:8]}… "
                            f"(hash {result_hash[:12]})"),
                    policy_version=LIVE_SOURCES_VERSION)
    store.audit(actor=actor, action="event:ObservationReceived",
                decision="ALLOW",
                detail=(f"{conn['name']} observed {domain} for {inv['id']}; "
                        f"new_evidence={new_row} changed={bool(changed_from)} "
                        f"hash={result_hash[:16]}… evidence={evidence_id}"),
                policy_version=LIVE_SOURCES_VERSION)
    return {"evidence_id": evidence_id, "new_evidence": new_row,
            "newly_linked": linked, "changed_from": changed_from,
            "result_hash": result_hash}


def _run_observation(store, *, source_key: str, investigation_id: str,
                     domain: str, actor: str) -> dict:
    """The one governed path every live source walks. Gate order is
    deliberate and each failure is classified (§20):
    §76 living-case → §63 scope cone → §80 ACTIVE on-allowlist connector →
    fetch (classified wire) → §67/§68 persist."""
    spec = _SOURCES[source_key]
    inv = store.inv_get(investigation_id)
    if not inv:
        raise PipelineError("INV_NOT_FOUND", status=404,
                            detail=f"investigation {investigation_id} does "
                                   "not exist.")
    inv = investigation.authorize_run(store, investigation_id, branches=[],
                                      user_id=actor)
    d = _bind_scope(inv, domain)

    conn = _active_connector(store, name=spec["connector_name"],
                             url_hint=spec["url_hint"])
    if not conn:
        raise PipelineError(
            "CONNECTOR_NOT_ACTIVE", status=409,
            detail=json.dumps({
                "what_happened": (f"no ACTIVE {spec['connector_name']} "
                                  "connector is registered."),
                "what_it_means": ("live sources enter ONLY through the §80 "
                                  "connector registry (admin register → "
                                  "governance approval → ACTIVE). The pilot "
                                  "runbook seeds it in two calls."),
                "what_to_do": (f"POST /api/v1/enterprise/connectors "
                               f"{{name: {spec['connector_name']}, kind: "
                               f"C_data_api, base_url: {spec['base_url']}}} "
                               "as admin, then approve the minted approval "
                               "as governance.")}))
    allowed = inv.get("allowed_sources") or []
    if (allowed and conn["name"] not in allowed
            and spec["connector_name"] not in allowed):
        raise PipelineError(
            "ACTION_DENIED", status=403,
            detail=(f"connector '{conn['name']}' is not in this case's "
                    f"allowed_sources {allowed} (R-DENY-SOURCES). Widen the "
                    "case policy or register a case-scoped connector."))

    health_id = f"connector:{conn['name']}"
    store.audit(actor=actor, action="event:SourceQueried",
                decision="ALLOW",
                detail=(f"{spec['connector_name']} PASSIVE query for {d} on "
                        f"{investigation_id} via {conn['id']}"),
                policy_version=LIVE_SOURCES_VERSION)
    try:
        result = spec["fetch"](d)
    except PipelineError as exc:
        store.upsert_source_meta(
            {"id": health_id, "reliability": "UNKNOWN",
             "authority": "SECONDARY", "independence_group": health_id},
            ok=False, error=f"{exc.code}: {str(exc.detail)[:160]}")
        store.update_source_health(
            health_id, 0.5,
            f"live fetch failed {exc.code} at "
            f"{datetime.now(timezone.utc).isoformat()[:19]}Z — see audit "
            "event:SourceQueried (DENY)")
        store.audit(actor=actor, action="event:SourceQueried",
                    decision="DENY",
                    detail=f"{spec['connector_name']} fetch failed "
                           f"classified {exc.code}: {str(exc.detail)[:200]}",
                    policy_version=LIVE_SOURCES_VERSION)
        raise
    out = persist_observation(
        store, inv=inv, conn=conn, domain=d, fetch_result=result,
        actor=actor, collection=spec["collection"],
        osint_class=spec["osint_class"], reliability=spec["reliability"],
        authority=spec["authority"],
        summary_line=spec["summarize"](d, result),
        extra_metadata=spec["extra_metadata"](result))
    return {"investigation_id": inv["id"], "domain": d,
            "connector": {"id": conn["id"], "name": conn["name"],
                          "kind": conn["kind"]},
            "osint_class": spec["osint_class"],
            "provenance": {
                "source": spec["provenance_name"],
                "query_url": result["query_url"],
                "fetched_at": store.get_evidence(out["evidence_id"])["fetched_at"]
                              if out["evidence_id"] else None,
                "reproducibility": ("§68: re-run the same query_url; the "
                                    "stored row is committed by content "
                                    "hash — a different hash is an "
                                    "ObservationChanged event (§67)")},
            "degraded": None,
            **out, **spec["view"](result)}


# ------------------------------------------------------------- source map --
def _crtsh_summary(domain: str, r: dict) -> str:
    return (f"PASSIVE CT observation for *.{domain}: "
            f"{r['observed_total']} unique name(s).\n"
            + "\n".join(r["names"][:10]))


def _rdap_summary(domain: str, r: dict) -> str:
    if not r["registered"]:
        return (f"PASSIVE RDAP observation: {domain} is NOT registered in "
                "the registry of record (HTTP 404 is data, not an outage).")
    return (f"PASSIVE RDAP observation: {domain} — registrar "
            f"{r['registrar'] or 'unparsed'}, status "
            f"{', '.join(r['status'][:3]) or 'none listed'}, "
            f"{len(r['nameservers'])} nameserver(s).")


_SOURCES = {
    "crtsh": {
        "connector_name": "crtsh", "url_hint": "crt.sh",
        "base_url": "https://crt.sh",
        "collection": "PASSIVE — Certificate Transparency logs (crt.sh)",
        "osint_class": "§64 public infrastructure record (technical) — PASSIVE",
        "reliability": "HIGH",       # append-only, signed
        "authority": "PRIMARY",      # the log itself is the record
        "provenance_name": "crt.sh (Certificate Transparency)",
        "fetch": fetch_crtsh_subdomains,
        "summarize": _crtsh_summary,
        "extra_metadata": lambda r: {"observed_total": r["observed_total"],
                                     "truncated": r["truncated"],
                                     "names": r["names"]},
        "view": lambda r: {"observed_total": r["observed_total"],
                           "names": r["names"], "truncated": r["truncated"]},
    },
    "rdap": {
        "connector_name": "rdap", "url_hint": "rdap",
        "base_url": "https://rdap.org",
        "collection": "PASSIVE — RDAP registry of record (IANA bootstrap)",
        "osint_class": "§64 public infrastructure record (technical) — PASSIVE",
        "reliability": "HIGH",       # the registry's own answer
        "authority": "PRIMARY",
        "provenance_name": "rdap.org (IANA RDAP bootstrap)",
        "fetch": fetch_rdap_domain,
        "summarize": _rdap_summary,
        "extra_metadata": lambda r: {"registered": r["registered"],
                                     "registrar": r["registrar"],
                                     "status": r["status"],
                                     "nameservers": r["nameservers"],
                                     "events": r["events"]},
        "view": lambda r: {"registered": r["registered"],
                           "registrar": r["registrar"],
                           "status": r["status"],
                           "nameservers": r["nameservers"],
                           "events": r["events"]},
    },
}


# ------------------------------------------------------------ public API --
def run_crtsh_observation(store, *, investigation_id: str, domain: str,
                          actor: str) -> dict:
    """PASSIVE CT name inventory for a domain case — governed path above."""
    return _run_observation(store, source_key="crtsh",
                            investigation_id=investigation_id,
                            domain=domain, actor=actor)


def run_rdap_observation(store, *, investigation_id: str, domain: str,
                         actor: str) -> dict:
    """PASSIVE registry-of-record read for a domain case — governed path."""
    return _run_observation(store, source_key="rdap",
                            investigation_id=investigation_id,
                            domain=domain, actor=actor)
