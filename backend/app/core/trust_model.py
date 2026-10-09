"""Trust model — spec §26 / Part 1 (trust_model.py).

FACT: directly observed, provenanced data points.
EVIDENCE: source excerpts with reliability + independence metadata.
INFERENCE: every generated interpretation — always labeled, never posed as fact.
"""
from __future__ import annotations

from ..models.schemas import TrustLabel


def label_inference(text: str) -> str:
    return f"INFERENCE: {text}"


def label_fact(statement: str, source_id: str) -> str:
    return f"FACT ({source_id}): {statement}"


TRUST_LABELS = TrustLabel
