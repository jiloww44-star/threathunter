"""Scraper core data models — spec Part 3.

RawEvidence carries provenance (§16-17). Signal is the structured input the
reasoning engine consumes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Reliability(Enum):  # spec Part 3 — source scoring weights
    VERY_HIGH = 0.95
    HIGH = 0.8
    MODERATE = 0.6
    LOW = 0.35
    UNKNOWN = 0.2


class SourceUnavailable(Exception):
    """Classifies as SOURCE_UNAVAILABLE in the pipeline (§20)."""


@dataclass
class RawEvidence:
    source_id: str
    url: str
    fetched_at: str
    content_hash: str
    raw_text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Signal:
    entity: str | None
    event_type: str | None
    location: str | None
    time: str | None  # ISO date/datetime of the event described
    claim_text: str
    confidence_input: float  # from source reliability
    source_id: str
    independence_group: str
    reliability: str = "UNKNOWN"
    authority: str = "SECONDARY"
    supports_claim: bool | None = None
    url: str | None = None
    evidence_id: str | None = None
    designed_to_test: str | None = None   # seed-pack marker (Part 10.3)
    metadata: dict = field(default_factory=dict)
