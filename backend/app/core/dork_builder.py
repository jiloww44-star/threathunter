"""OSINT Dork Builder — v4.0 §:
"Dorking = methodology engine, stored as {objective, search_engine, syntax,
intended_use, risk_level, authorized_scope, source, last_verified}; dork
builder explains what/why/expected results/boundaries."

This module BUILDS syntax deterministically (§54) and NEVER executes it —
there is no live search-engine connector in the demo profile, so no dork
can masquerade as an observation (§20). Every generated dork carries the
passive-first classification (PASSIVE → PUBLIC ACTIVE → AUTHORIZED ACTIVE)
plus its why/expected-results/boundaries text.

Templates are methodology knowledge (external §80 source map: public OSINT
cheat sheets), marked `source="template-library"`, `last_verified` stamped
at build time — operators re-verify operators against live engine grammars
before relying on them operationally.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Passive-first design (§ passive-first): PASSIVE = querying public index
# metadata only; nothing here grades above PASSIVE without an authorization
# trail — the AUTHORIZED_ACTIVE tier is reserved for gated connectors.
RISK_LEVELS = ("PASSIVE", "PUBLIC_ACTIVE", "AUTHORIZED_ACTIVE")

_ENGINES = {
    "google": {
        "site": "site:{}", "filetype": "filetype:{}",
        "intitle": 'intitle:"{}"', "inurl": "inurl:{}",
        "quoted": '"{}"', "minus": "-{}",
    },
    "bing": {
        "site": "site:{}", "filetype": "filetype:{}",
        "intitle": 'intitle:"{}"', "inurl": "inurl:{}",
        "quoted": '"{}"', "minus": "-{}",
    },
    "duckduckgo": {
        "site": "site:{}", "filetype": "filetype:{}",
        "quoted": '"{}"', "minus": "-{}",
    },
}

# objective templates per subject_type — (name, syntax_template, why,
# expected, boundaries). Deterministic: same inputs → same dorks.
_TEMPLATES: dict[str, list[dict]] = {
    "domain": [
        {"name": "subdomain_surface",
         "syntax": "site:{subject} -www",
         "why": "Enumerate indexed subdomains to map the passive attack "
                "surface.",
         "expected": "Indexed subdomains (dev/staging/orphaned hosts often "
                     "surface here).",
         "boundaries": "No crawling or probing — search-engine index data "
                       "only (PASSIVE)."},
        {"name": "exposed_documents",
         "syntax": "site:{subject} filetype:pdf OR filetype:xls OR "
                   "filetype:doc",
         "why": "Find publicly indexed documents that may leak metadata or "
                "internal structure.",
         "expected": "Publicly indexed office documents on the domain.",
         "boundaries": "Open only what the index exposes publicly; do not "
                       "bypass access controls (§74: never)."},
        {"name": "login_portals",
         "syntax": 'site:{subject} inurl:login OR inurl:admin OR '
                   'intitle:"sign in"',
         "why": "Identify advertised authentication surfaces for the "
                "exposure register.",
         "expected": "Indexed login/admin-adjacent pages.",
         "boundaries": "Listing ≠ testing. Authentication attempts are "
                       "AUTHORIZED_ACTIVE and gated separately (§35)."},
    ],
    "organization": [
        {"name": "email_format_leak",
         "syntax": '"{subject}" filetype:pdf OR filetype:docx',
         "why": "Public documents often reveal official email/phone formats "
                "for the org.",
         "expected": "Documents containing contact patterns.",
         "boundaries": "Collect format evidence only — no person-targeted "
                       "enumeration (§76: authority scoping)."},
        {"name": "mention_watch",
         "syntax": '"{subject}" -site:{canonical}',
         "why": "Surface third-party references to the org excluding its "
                "own site.",
         "expected": "News, forums, government/regulator mentions.",
         "boundaries": "Third-party content is OBSERVATION, not truth — "
                       "feed it through the reasoning engine (§5)."},
    ],
    "person": [
        {"name": "public_footprint",
         "syntax": '"{subject}"',
         "why": "Baseline public-index footprint of the identifier.",
         "expected": "Pages mentioning the exact identifier.",
         "boundaries": "Person-subject dorking REQUIRES an authority basis "
                       "(organization-owned investigation of an employee "
                       "needs HR/legal mandate). No doxxing, no private-data "
                       "aggregation (§76, NDPA 2023)."},
    ],
    "url": [
        {"name": "url_reputation_mentions",
         "syntax": '"{subject}" -site:{host}',
         "why": "Who references this URL elsewhere? Reputation signal "
                "before visiting.",
         "expected": "Third-party mentions of the URL.",
         "boundaries": "PASSIVE index search only; visiting the URL is a "
                       "separate, scoped decision."},
    ],
    "claim": [
        {"name": "claim_verbatim",
         "syntax": '"{subject}"',
         "why": "Detect copy chains — identical phrasing across sources "
                "signals syndication, not corroboration (§1.6).",
         "expected": "Sources quoting the claim verbatim.",
         "boundaries": "Index matches feed the independence analysis; they "
                       "are not verdicts."},
    ],
    "ip": [
        {"name": "ip_index_mentions",
         "syntax": '"{subject}"',
         "why": "Find public mentions of the IP (blocklist pages, abuse "
                "forums) without touching the host.",
         "expected": "Index pages referencing the IP.",
         "boundaries": "No scanning, no banner grabbing — those are "
                       "PUBLIC_ACTIVE/AUTHORIZED_ACTIVE connectors (§35)."},
    ],
}

_LOCATION_REF = {"name": "location_context",
                 "syntax": '"{subject}" incident OR safety OR advisory',
                 "why": "Public index context for a location/corridor.",
                 "expected": "News/advisory mentions of the location.",
                 "boundaries": "PASSIVE index search only."}
_TEMPLATES["location"] = [_LOCATION_REF]
_TEMPLATES["agent"] = [_LOCATION_REF]  # baseline mention search


def build_dorks(objective: str, subject: str, subject_type: str = "domain",
                authorized_scope: str = "open public tier",
                search_engine: str = "google") -> dict:
    """Build the dork set for a subject — generation only, never execution.

    Returns the spec storage shape per dork plus the why/expected/boundaries
    explanation. Unknown subject_types degrade to the 'claim' baseline with
    an honest note rather than fabricating expertise (§20).
    """
    engine = search_engine if search_engine in _ENGINES else "google"
    grammar_note = (None if search_engine in _ENGINES else
                    f"engine '{search_engine}' has no declared grammar here —"
                    " defaulted to 'google' (§20: disclosed, not silent).")
    templates = _TEMPLATES.get(subject_type) or _TEMPLATES["claim"]
    degraded = subject_type not in _TEMPLATES
    now = datetime.now(timezone.utc).isoformat()

    dorks = []
    for t in templates:
        dorks.append({
            "name": t["name"],
            "objective": objective,
            "search_engine": engine,
            "syntax": t["syntax"].format(subject=subject.strip(),
                                         host=subject.strip().
                                         split("/")[0],
                                         canonical=subject.strip()),
            "intended_use": objective,
            "risk_level": "PASSIVE",
            "authorized_scope": authorized_scope,
            "source": "template-library",
            "last_verified": now,
            "why": t["why"],
            "expected_results": t["expected"],
            "boundaries": t["boundaries"],
        })

    return {
        "subject": subject.strip(),
        "subject_type": subject_type,
        "dorks": dorks,
        "count": len(dorks),
        "generated_at": now,
        "degraded_note": ("Unknown subject_type — using the baseline "
                          "verbatim-mention template only."
                          if degraded else grammar_note),
        "execution_note": ("Dorks are GENERATED, never executed by this "
                           "platform in the demo profile — run them inside "
                           "your authorized scope using a licensed search "
                           "engine access path (§35/§76)."),
        "passive_first": ("Passive-first ordering (PASSIVE → PUBLIC ACTIVE →"
                          " AUTHORIZED ACTIVE): everything generated here is"
                          " PASSIVE index-query syntax only."),
    }
