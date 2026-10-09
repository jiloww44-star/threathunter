"""Copy-chain detection (independence analysis) — spec Part 3.3 (§1.6).

A group of near-identical claims from the same independence_group counts as
ONE effective source, not five. Pure-python 64-bit Simhash (production swaps
in the `simhash` package — same interface).
"""
from __future__ import annotations

import hashlib
import re

from .models import Signal


def simhash64(text: str) -> int:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    bits = [0] * 64
    for tok in tokens:
        h = int.from_bytes(hashlib.blake2s(tok.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            bits[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, b in enumerate(bits):
        if b > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def detect_copy_chains(signals: list[Signal], threshold: int = 6) -> list[list[Signal]]:
    """Group near-identical claims; each returned group = one effective
    independent source. Within a group, members are copy-chain siblings."""
    groups: list[list[Signal]] = []
    hashes = [simhash64(s.claim_text) for s in signals]
    for s, h in zip(signals, hashes):
        placed = False
        for g in groups:
            g0 = g[0]
            same_group = s.independence_group == g0.independence_group
            close = hamming(h, simhash64(g0.claim_text)) <= threshold
            # Identical/similar text even across groups is still a copy chain
            # (syndication); same-group rule below governs independence.
            if close and same_group:
                g.append(s)
                placed = True
                break
        if not placed:
            groups.append([s])
    return groups


def mark_duplicate_copies(groups: list[list[Signal]]) -> dict[str, bool]:
    """Flag which evidence ids are non-primary members of a copy chain."""
    flags: dict[str, bool] = {}
    for g in groups:
        for i, s in enumerate(g):
            if s.evidence_id:
                flags[s.evidence_id] = i > 0
    return flags


def content_similarity(a: str, b: str, threshold: int = 6) -> bool:
    return hamming(simhash64(a), simhash64(b)) <= threshold
