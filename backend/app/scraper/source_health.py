"""Source health scoring — §Willison Bottleneck Map, U1 redesign (spec §1.10).

The broken assumption: a human curator vets sources at human pace while the
pipeline consumes at machine pace — so stale, contradicting, or merely
echoing sources accumulate silently. The redesign (TRUST.md §Source health):
a daily **auto-computed scorecard** per source —

    freshness compliance   does last_success_at meet freshness_sla_hours?
    contradiction rate     share of this source's signals involved in
                           cross-source contradictions (§1.8 machinery)
    copy-chain participation   share of this source's evidence that is a
                           near-duplicate inside its independence group
                           (a source that echoes others is NOT independent, §1.6)

    health = 0.45·fresh_ok + 0.30·(1 - contra_rate) + 0.25·(1 - copy_rate)

Below DEMOTE_THRESHOLD — **or against the freshness SLA at all** (an SLA is
a hard gate, not a soft weight, §1.10) — the source is auto-demoted
(PRIMARY → SECONDARY, with the audit trail written to sources_meta) and a
curator review item is enqueued — the human reviews ONLY demotions and
recoveries, not steady state. Recovery above RECOVER_THRESHOLD (fresh AND
healthy) restores authority automatically (same curator notification).
Never silent either way (§20).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..core.contradictions import detect_contradictions
from .dedupe import hamming, simhash64

log = logging.getLogger("th360.source_health")

DEFAULT_SLA_HOURS = 48          # when a registry entry sets no SLA
DEMOTE_THRESHOLD = 0.45         # below → PRIMARY auto-demoted
RECOVER_THRESHOLD = 0.65        # above → demotion auto-recovered
W_FRESH, W_CONTRA, W_COPY = 0.45, 0.30, 0.25


@dataclass
class SourceHealth:
    source_id: str
    fresh_ok: bool
    freshness_lag_hours: float | None
    contradiction_rate: float
    copy_rate: float
    health: float
    action: str = "none"            # none | demoted | recovered
    note: str = ""

    def as_dict(self) -> dict:
        return {**self.__dict__}


def _evidence_groups(store) -> tuple[list[dict], dict[str, list[dict]]]:
    evidence = store.all_evidence()
    by_group: dict[str, list[dict]] = {}
    for ev in evidence:
        by_group.setdefault(ev["independence_group"], []).append(ev)
    return evidence, by_group


def _copy_flags(by_group: dict[str, list[dict]],
                threshold: int = 12) -> dict[str, bool]:
    """Mirrors statistics()' copy-chain ratio (Part 4.4), per evidence item:
    inside one independence group, items near-identical to an earlier item
    are copies (the earlier item is the chain's origin)."""
    flags: dict[str, bool] = {}
    for g in by_group.values():
        seen: list[int] = []
        for e in g:
            h = simhash64(e.get("excerpt") or "")
            flags[e["id"]] = any(hamming(h, s) <= threshold for s in seen)
            if not flags[e["id"]]:
                seen.append(h)
    return flags


def score_sources(store, *, sla_hours: dict[str, float] | None = None,
                  now_ts: float | None = None,
                  demote_threshold: float = DEMOTE_THRESHOLD,
                  recover_threshold: float = RECOVER_THRESHOLD,
                  enqueue=None) -> list[SourceHealth]:
    """Compute the daily scorecard and auto-demote/recover sources.

    `sla_hours`: per-source freshness SLA (registry `freshness_sla_hours`).
    `enqueue`: review-queue sink for curator notification (defaults to
    store.enqueue_review with module='curation').
    """
    import time
    from datetime import datetime, timezone

    enqueue = enqueue or store.enqueue_review
    now = now_ts if now_ts is not None else time.time()
    sla_hours = sla_hours or {}

    evidence, by_group = _evidence_groups(store)
    copy_flags = _copy_flags(by_group)
    by_source: dict[str, list[dict]] = {}
    for ev in evidence:
        by_source.setdefault(ev["source_id"], []).append(ev)

    # contradiction participation: all ordered cross-source contradictions
    signals = store.all_signals()
    contras = detect_contradictions(signals)
    involved: dict[str, int] = {}
    ev_src = {e["id"]: e["source_id"] for e in evidence}
    for c in contras:
        for eid in (c.evidence_a_id, c.evidence_b_id):
            sid = ev_src.get(eid)
            if sid:
                involved[sid] = involved.get(sid, 0) + 1

    out: list[SourceHealth] = []
    metas = {m["source_id"]: m for m in store.all_source_meta()}
    for sid, items in sorted(by_source.items()):
        meta = metas.get(sid, {})
        last = meta.get("last_success_at")
        lag_hours = None
        fresh_ok = False
        if last:
            try:
                dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                lag_hours = max(0.0, (now - dt.timestamp()) / 3600)
                fresh_ok = lag_hours <= sla_hours.get(sid, DEFAULT_SLA_HOURS)
            except Exception:
                fresh_ok = False
        n = len(items)
        contra_rate = involved.get(sid, 0) / n if n else 0.0
        copy_rate = sum(1 for e in items if copy_flags.get(e["id"])) / n \
            if n else 0.0
        health = round(W_FRESH * (1.0 if fresh_ok else 0.0)
                       + W_CONTRA * (1 - min(contra_rate, 1.0))
                       + W_COPY * (1 - copy_rate), 3)

        prev_note = meta.get("health_note") or ""
        was_demoted = "auto-demoted" in prev_note
        action, note = "none", prev_note
        demote_reason = None
        if not fresh_ok and meta.get("authority") == "PRIMARY":
            demote_reason = ("freshness SLA breach (lag "
                             f"{f'{lag_hours:.0f}h' if lag_hours is not None else 'never fetched'}"
                             f" > {sla_hours.get(sid, DEFAULT_SLA_HOURS):.0f}h)")
        elif health < demote_threshold:
            demote_reason = f"health {health:.2f} < {demote_threshold}"
        if (meta.get("authority") == "PRIMARY" and not was_demoted
                and demote_reason):
            action = "demoted"
            note = (f"auto-demoted PRIMARY→SECONDARY ({demote_reason}); "
                    f"scorecard: fresh_ok={fresh_ok}, "
                    f"contradiction_rate={contra_rate:.0%}, "
                    f"copy_rate={copy_rate:.0%}")
            log.warning("source %s %s", sid, note)
        elif was_demoted and fresh_ok and health >= recover_threshold:
            action = "recovered"
            note = (f"auto-recovered to PRIMARY (health {health:.2f} ≥ "
                    f"{recover_threshold}, SLA met) — curator to confirm")
            log.info("source %s %s", sid, note)

        authority = meta.get("authority", "SECONDARY")
        if action == "demoted":
            authority = "SECONDARY"
        elif action == "recovered":
            authority = "PRIMARY"
        store.update_source_health(sid, health, note, authority=authority)
        if action != "none":
            enqueue(module="curation", case_ref=sid, reason=note,
                    risk="LOW" if action == "demoted" else "MODERATE",
                    priority=15, tier="CURATOR_REVIEW")
        out.append(SourceHealth(
            source_id=sid, fresh_ok=fresh_ok,
            freshness_lag_hours=(round(lag_hours, 1)
                                 if lag_hours is not None else None),
            contradiction_rate=round(contra_rate, 3),
            copy_rate=round(copy_rate, 3), health=health,
            action=action, note=note))
    return out
