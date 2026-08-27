"""HUNTER agent — spec A-05.

OSINT footprint reconstruction over the shared Evidence & Trust Layer.
Live dorking / carrier / breach lookups are NOT available in the demo
profile — they return SOURCE_UNAVAILABLE gaps instead of fabricated data
(§20; Part 10 zero-dependency contract).
"""
from __future__ import annotations

from ...core import nlp_lite
from ...core.contradictions import detect_contradictions
from ...store.db import EvidenceStore


def footprint_scan(store: EvidenceStore, entity: str,
                   limit: int = 50) -> dict:
    """Graph-based footprint reconstruction (A-05): all indexed signals for
    an entity, related entities/locations, grouped by independence group so
    copy-chains never inflate the footprint (§1.6)."""
    hits = store.search_signals(entity, limit=limit)
    by_group: dict[str, int] = {}
    related: dict[str, int] = {}
    locations: dict[str, int] = {}
    for h in hits:
        by_group[h.get("independence_group") or "unknown"] = \
            by_group.get(h.get("independence_group") or "unknown", 0) + 1
        for loc in (h.get("locations") or []):
            locations[loc] = locations.get(loc, 0) + 1
        for ent in nlp_lite.extract_entities(h.get("claim_text") or ""):
            if ent.lower() != entity.lower() and len(ent) > 3:
                related[ent] = related.get(ent, 0) + 1
    gaps = ["live dorking sweep", "carrier lookup", "breach corpus check"]
    return {
        "entity": entity,
        "signals_indexed": len(hits),
        "independent_sources": len(by_group),
        "independence_breakdown": by_group,
        "related_entities": sorted(related, key=related.get,
                                   reverse=True)[:10],
        "locations": sorted(locations, key=locations.get, reverse=True)[:10],
        "coverage_gaps": gaps,
        "gap_note": ("External audits unavailable in the demo profile "
                     "(§20 SOURCE_UNAVAILABLE) — footprint is built from the "
                     "indexed evidence graph only; gaps are disclosed, never "
                     "filled with guesses."),
        "trust_label": "EVIDENCE",
    }


def actor_analysis(store: EvidenceStore, entity: str) -> dict:
    """Cluster an entity's signals by independence group and surface
    contradictions via the Trust Layer monitor (global §1.8 scope)."""
    hits = store.search_signals(entity, limit=60)
    contras = detect_contradictions(hits)
    return {
        "entity": entity,
        "signal_count": len(hits),
        "contradictions": [{
            "description": c.description, "severity": c.severity.value,
        } for c in contras],
        "assessment_note": ("INFERENCE: clusters describe what indexed "
                            "sources say about this entity — tendencies, not "
                            "verdicts (§26)."),
        "trust_label": "INFERENCE",
    }


def external_audit(entity: str) -> dict:
    """Domain/carrier/breach audit — demo profile has no live external
    provider (A-05). Honest degradation per §20."""
    return {
        "entity": entity,
        "classified_error": "SOURCE_UNAVAILABLE",
        "note": ("Live external audits (domain, carrier, breach corpora) "
                 "require the Fusion Core providers, which are not configured "
                 "in the demo profile. Result intentionally empty — no "
                 "fabricated findings (§20)."),
        "findings": [],
    }
