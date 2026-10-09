"""NLP extraction — spec Parts 3.2 / 3 (NLP extraction models).

Production model stack (spec Part 3.1): spaCy en_core_web_trf for NER,
dateparser for dates, sentence-transformers for embeddings, BART zero-shot
for event typing. Those models plug in behind the same interfaces via the
production Docker profile.

This module provides the **demo-profile adapters** (spec Part 10 design
principle: run end-to-end today with zero external dependencies):
  * deterministic feature-hash embeddings (384-d) with cosine similarity
  * regex/gazetteer NER (proper-noun spans, org suffixes, location gazetteer)
  * keyword zero-shot event typing over the spec's EVENT_LABELS
  * ISO + "14 August 2026" style date parsing

Everything is pure-python, deterministic and offline — which also makes the
reasoning engine unit-testable (spec Part 8: tests are trust-critical assets).
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone

# Spec Part 3.2 — the event-type label set the zero-shot classifier targets.
EVENT_LABELS = [
    "sanction",
    "security incident",
    "natural disaster",
    "regulatory action",
    "criminal activity",
    "infrastructure outage",
]

_EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sanction": ("sanction", "sanctioned", "blacklist", "embargo", "asset freeze"),
    "security incident": ("attack", "breach", "intrusion", "shooting", "bomb", "kidnap",
                          "robbery", "armed", "terror"),
    "natural disaster": ("flood", "earthquake", "hurricane", "storm", "wildfire",
                         "landslide", "cyclone"),
    "regulatory action": ("regulator", "regulatory", "license", "licence", "fined",
                          "suspended", "revoked", "compliance order", "gazette"),
    "criminal activity": ("arrest", "fraud", "theft", "scam", "money laundering",
                          "indicted", "charged"),
    "infrastructure outage": ("outage", "blackout", "shutdown", "power cut",
                              "network down", "grid failure"),
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "is",
    "was", "were", "are", "be", "been", "by", "with", "from", "as", "that",
    "this", "it", "its", "his", "her", "their", "our", "your", "my", "we",
    "they", "he", "she", "you", "i", "not", "no", "but", "if", "then", "than",
    "so", "such", "has", "have", "had", "will", "would", "can", "could", "may",
    "might", "shall", "should", "do", "does", "did", "who", "whom", "whose",
    "which", "what", "when", "where", "why", "how", "said", "says", "say",
    "according", "report", "reports", "reported", "following", "after",
    "followinga", "last", "next", "week", "weeks", "month", "year", "today",
    "yesterday", "officially", "official", "officials", "confirmed", "confirms",
    "confirm", "new", "over", "per", "into", "out", "up", "down", "about",
}

_ORG_SUFFIXES = (
    "company", "corp", "corporation", "ltd", "limited", "llc", "inc",
    "holdings", "bank", "group", "plc", "gmbh", "sa", "enterprises",
)

_COMMON_LOCATIONS = [
    "lagos", "ibadan", "ikeja", "abuja", "kano", "london", "new york",
    "nairobi", "accra", "johannesburg", "dubai", "singapore",
]

_EMBED_DIMS = 384


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def _h(token: str) -> int:
    return int.from_bytes(hashlib.blake2s(token.encode(), digest_size=4).digest(), "big")


def embed(text: str) -> list[float]:
    """Deterministic feature-hash embedding (demo profile).

    Swappable: in production, `sentence-transformers/all-MiniLM-L6-v2` (or the
    Part 19 multilingual variant) replaces this behind the same signature.
    """
    vec = [0.0] * _EMBED_DIMS
    toks = _tokens(text)
    grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    for tok in grams:
        hv = _h(tok)
        idx = hv % _EMBED_DIMS
        sign = 1.0 if (hv >> 31) & 1 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def extract_claim_elements(text: str) -> dict:
    """§1.1 Observation — entities / dates / locations / event type."""
    return {
        "entities": extract_entities(text),
        "dates": extract_dates(text),
        "locations": extract_locations(text),
        "orgs": extract_orgs(text),
        "event_type": classify_event(text),
    }


def extract_orgs(text: str) -> list[str]:
    orgs: list[str] = []
    for m in re.finditer(
        r"\b((?:[A-Z][\w&'-]*\s+){0,3}(?:Company|Corp(?:oration)?|Ltd|Limited|"
        r"LLC|Inc|Holdings|Bank|Group|Plc|Enterprises|GmbH|SA)\b"
        r"(?:\s+[A-Z][\w&'-]*){0,2})",
        text,
    ):
        orgs.append(m.group(1).strip())
    for m in re.finditer(r"\b(Company\s+[A-Z](?:[\w-]*))\b(?:\s+(Holdings|Ltd|Group|Enterprises))?", text):
        full = m.group(0).strip()
        if full not in orgs:
            orgs.append(full)
    # de-dup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for o in orgs:
        key = re.sub(r"\s+", " ", o).strip()
        if key.lower() not in seen:
            seen.add(key.lower())
            out.append(key)
    return out


def extract_entities(text: str) -> list[str]:
    spans = extract_orgs(text)
    for m in re.finditer(r"\b([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){0,2})\b", text):
        span = m.group(1)
        # articles glued to a proper noun by capitalization are not part of
        # the entity ("The Governor" → "Governor")
        span = re.sub(r"^(?:The|A|An)\s+", "", span)
        if not span:
            continue
        first = span.lower()
        if first in _STOPWORDS or first in _COMMON_LOCATIONS:
            continue
        if any(span.lower() in o.lower() or o.lower() in span.lower() for o in spans):
            continue
        spans.append(span)
    seen: set[str] = set()
    out: list[str] = []
    for s in spans:
        if s.lower() not in seen and len(s) > 1:
            seen.add(s.lower())
            out.append(s)
    return out[:8]


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def extract_dates(text: str) -> list[str]:
    """Return ISO date strings found in text (production: dateparser)."""
    dates: list[str] = []
    for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
        dates.append(m.group(0))
    for m in re.finditer(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b", text
    ):
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            dates.append(f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}")
    for m in re.finditer(r"\b([A-Za-z]+)\s+(20\d{2})\b", text):
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            dates.append(f"{m.group(2)}-{mon:02d}-01")
    seen: set[str] = set()
    out: list[str] = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def extract_locations(text: str) -> list[str]:
    low = text.lower()
    found = [loc.title() for loc in _COMMON_LOCATIONS if loc in low]
    out: list[str] = []
    seen: set[str] = set()
    for loc in found:
        if loc.lower() not in seen:
            seen.add(loc.lower())
            out.append(loc)
    return out


def classify_event(text: str) -> str | None:
    """Keyword zero-shot over the spec's EVENT_LABELS (production: BART MNLI)."""
    low = text.lower()
    best: tuple[int, str | None] = (0, None)
    for label, keywords in _EVENT_KEYWORDS.items():
        hits = sum(1 for k in keywords if k in low)
        if hits > best[0]:
            best = (hits, label)
    return best[1]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# Office titles and the institutions that speak through them — a claim about
# "the Governor" co-refers to records filed under "... Government". Used ONLY
# on the claim→record retrieval path (allow_title_alias=True); doc↔doc
# contradiction pairing keeps strict matching so two different governments
# never pair (e.g. "Lagos State Government" ≠ "Osun State Government").
_TITLE_TO_INSTITUTION = {
    "governor": "government",
    "governorship": "government",
    "president": "presidency",
    "presidency": "president",
    "minister": "ministry",
    "prime minister": "government",
    "mayor": "council",
}


def _with_title_aliases(tokens: set[str]) -> set[str]:
    out = set(tokens)
    joined = " ".join(sorted(tokens))
    for title, inst in _TITLE_TO_INSTITUTION.items():
        if title in tokens or title in joined:
            out.add(inst)
    return out


def same_entity(a: str | None, b: str | None, threshold: float = 0.85,
                allow_title_alias: bool = False) -> bool:
    """Fuzzy entity match ≥ threshold (spec Part 3.3 `same_entity`)."""
    if not a or not b:
        return False
    ta = set(_tokens(a))
    tb = set(_tokens(b))
    if not ta or not tb:
        return False
    jacc = len(ta & tb) / len(ta | tb)
    if jacc >= threshold:
        return True
    # containment handles "Company X" vs "Company X Holdings"
    la, lb = a.lower(), b.lower()
    if la in lb or lb in la:
        return True
    if allow_title_alias:
        # retrieval-only: office-title co-reference ("governor" ↔
        # "... government"); fires on EXPANDED tokens only, never on bare
        # originals, so institutions do not cross-match each other.
        for t in _with_title_aliases(ta) - ta:
            if len(t) > 3 and t in lb:
                return True
        for t in _with_title_aliases(tb) - tb:
            if len(t) > 3 and t in la:
                return True
    return False
