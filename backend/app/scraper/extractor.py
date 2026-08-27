"""Content extraction → structured signals — spec Part 3.2.

Order of preference (per spec):
  1. Structured fixture payloads (demo profile — fixtures carry typed fields,
     see Part 10.3: each fixture is crafted to exercise a specific behavior)
  2. JSON-LD / schema.org blocks embedded in HTML
  3. NLP-lite fallback over visible text (production: spaCy pipeline)
"""
from __future__ import annotations

import json
import re

from ..core import nlp_lite
from .models import RawEvidence, Reliability, Signal


def _reliability_value(name: str) -> float:
    try:
        return Reliability[name.upper()].value
    except KeyError:
        return Reliability.UNKNOWN.value


def _base_signal(ev: RawEvidence, claim_text: str) -> Signal:
    meta = ev.metadata
    return Signal(
        entity=None,
        event_type=None,
        location=None,
        time=None,
        claim_text=claim_text.strip()[:500],
        confidence_input=_reliability_value(meta.get("reliability", "UNKNOWN")),
        source_id=ev.source_id,
        independence_group=meta.get("independence_group", ev.source_id),
        reliability=meta.get("reliability", "UNKNOWN"),
        authority=meta.get("authority", "SECONDARY"),
        url=ev.url,
    )


def extract_signals(ev: RawEvidence) -> list[Signal]:
    text = ev.raw_text or ""
    stripped = text.lstrip()

    # 1) Structured fixtures / API payloads (JSON at the top level)
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            return from_structured(data, ev)

    # 2) HTML: prefer JSON-LD blocks when present (spec Part 3.2)
    if "<" in stripped[:200]:
        jsonld_signals = _from_jsonld(ev)
        if jsonld_signals:
            return jsonld_signals
        text = re.sub(r"<script.*?</script>", " ", stripped, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    # 3) NLP-lite fallback over the whole body
    return from_nlp(text, ev)


def from_structured(data, ev: RawEvidence) -> list[Signal]:
    items = data if isinstance(data, list) else [data]
    doc_published = data.get("published_at") if isinstance(data, dict) else None
    signals: list[Signal] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "features" in item and item.get("type") == "FeatureCollection":
            for f in item.get("features", []):
                props = dict(f.get("properties", {}))
                sig = _base_signal(
                    ev, props.get("headline") or props.get("type") or json.dumps(props)[:300]
                )
                sig.event_type = props.get("type")
                sig.location = sig.location or props.get("segment") or props.get("location")
                sig.time = props.get("timestamp") or props.get("event_date")
                sig.entity = props.get("entity")
                sig.metadata = props
                sig.evidence_id = props.get("id") or (
                    f"geo-{props.get('segment','?')}-{props.get('timestamp','?')}")
                signals.append(sig)
            continue

        articles = item.get("articles") or item.get("entries")
        if articles:
            for art in articles:
                signals.append(_article_signal(art, ev, doc_published))
            continue

        if "headline" in item or "body" in item or "text" in item:
            signals.append(_article_signal(item, ev, doc_published))
    return signals


def _article_signal(item: dict, ev: RawEvidence, doc_published: str | None) -> Signal:
    body = item.get("body") or item.get("headline") or item.get("text") or ""
    sig = _base_signal(ev, " ".join(filter(None, [item.get("headline", ""), body])))
    entity = item.get("entity") or (item.get("entities") or [None])[0]
    sig.entity = entity
    sig.time = item.get("event_date") or item.get("published_at") or item.get("timestamp")
    sig.location = item.get("location")
    sig.event_type = item.get("event_type") or nlp_lite.classify_event(
        body + " " + (entity or "")
    )
    if not sig.entity:
        orgs = nlp_lite.extract_orgs(body or item.get("headline", ""))
        sig.entity = orgs[0] if orgs else None
    if not sig.location:
        locs = nlp_lite.extract_locations(body)
        sig.location = locs[0] if locs else None
    if "supports_claim" in item:
        sig.supports_claim = item["supports_claim"][0] if isinstance(
            item["supports_claim"], list) else item["supports_claim"]
    sig.evidence_id = item.get("id")
    sig.designed_to_test = item.get("designed_to_test")
    sig.metadata = dict(item)
    sig.metadata["published_at"] = item.get("published_at") or doc_published
    return sig


def _from_jsonld(ev: RawEvidence) -> list[Signal]:
    signals: list[Signal] = []
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        ev.raw_text, flags=re.S | re.I,
    ):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            sig = _base_signal(
                ev, item.get("headline") or item.get("description") or json.dumps(item)[:300]
            )
            sig.time = item.get("datePublished")
            sig.entity = (item.get("about") or {}).get("name") if isinstance(item.get("about"), dict) else item.get("name")
            loc = item.get("location")
            if isinstance(loc, dict):
                sig.location = loc.get("name")
            sig.event_type = nlp_lite.classify_event(sig.claim_text)
            signals.append(sig)
    return signals


def from_nlp(text: str, ev: RawEvidence) -> list[Signal]:
    elements = nlp_lite.extract_claim_elements(text)
    sig = _base_signal(ev, text[:500])
    sig.entity = (elements["orgs"] or elements["entities"] or [None])[0]
    sig.event_type = elements["event_type"]
    sig.location = (elements["locations"] or [None])[0]
    sig.time = (elements["dates"] or [None])[0]
    return [sig]
