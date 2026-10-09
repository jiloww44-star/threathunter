"""Compliance Index — blueprint v5.2 §6.C ("Govern Tab: review the Compliance
Index score").

Four transparent components, 25 points each, computed deterministically from
the store (single source of truth — no shadow counters, §20):

1. CONSENT INTEGRITY   — §5.3 hash-chained consent ledger verifies clean.
2. HUMAN GATE          — every executed tree was approved by a human
                         (plan_approved safety events vs executed trees).
3. PII DEFENSE         — identity-intel trees carry an AUDITOR mask step and
                         masking events are recorded on the trail.
4. ETHICS GATE         — refusal machinery works and every completed report
                         carries the AI disclaimer (§6.D).

The index is an operational *indicator*, never a certification — the note on
every component says exactly what it measured and what it did not (§1.9).
"""
from __future__ import annotations


def store_stats(db) -> dict:
    with db._lock:
        status_rows = db._conn.execute(
            "SELECT status, COUNT(*) c FROM ops_trees GROUP BY status"
        ).fetchall()
        statuses = {r["status"]: r["c"] for r in status_rows}
        executed = sum(statuses.get(s, 0) for s in
                       ("RUNNING", "COMPLETE", "DEGRADED", "FAILED", "HALTED",
                        "AWAITING_HUMAN"))
        disclaimed = db._conn.execute(
            "SELECT COUNT(*) c FROM ops_trees WHERE status IN "
            "('COMPLETE','DEGRADED') AND report_json LIKE '%AI-generated%'"
        ).fetchone()["c"]
        complete_like = statuses.get("COMPLETE", 0) + statuses.get("DEGRADED", 0)
        mask_events = db._conn.execute(
            "SELECT COUNT(*) c FROM audit_trail WHERE action LIKE '%mask%'"
        ).fetchone()["c"]
        intel_trees = db._conn.execute(
            "SELECT COUNT(DISTINCT tree_id) c FROM ops_tasks WHERE agent IN "
            "('HUNTER') OR function='id_audit_l1'").fetchone()["c"]
        intel_masked = db._conn.execute(
            "SELECT COUNT(DISTINCT tree_id) c FROM ops_tasks WHERE "
            "function='mask_pii' AND tree_id IN (SELECT tree_id FROM "
            "ops_tasks WHERE agent='HUNTER' OR function='id_audit_l1')"
        ).fetchone()["c"]
    return {"statuses": statuses, "executed": executed,
            "complete_like": complete_like, "disclaimed": disclaimed,
            "mask_events": mask_events, "intel_trees": intel_trees,
            "intel_masked": intel_masked,
            "safety": db.safety_event_counts()}


def compute_index(db) -> dict:
    st = store_stats(db)
    comps: list[dict] = []

    # 1 — Consent integrity (§5.3)
    from .privacy import verify_chain  # deferred import (cycle-safe)
    chain = verify_chain(db)
    if chain["chain_intact"] and chain["entries"] > 0:
        s1, n1 = 25, f"{chain['entries']} ledger entries; hash chain verified."
    elif chain["chain_intact"]:
        s1, n1 = 15, "Ledger empty — no consent decisions recorded yet."
    else:
        s1, n1 = 0, f"CHAIN BROKEN at entry {chain.get('broken_at')} — investigate."
    comps.append({"key": "consent_integrity", "label": "Consent integrity",
                  "spec": "§5.3", "score": s1, "max": 25, "note": n1})

    # 2 — Human gate (§6 "AI never acts without a human-approved plan")
    approved = st["safety"].get("plan_approved", 0)
    if st["executed"] == 0:
        s2, n2 = 25, "Nothing executed yet — no unapproved runs possible."
    else:
        ratio = min(1.0, approved / max(1, st["executed"]))
        s2 = round(25 * ratio)
        n2 = (f"{approved} approval event(s) across {st['executed']} executed "
              f"tree(s). Approval precedes execution by design (PROPOSED → "
              f"approve → run).")
    comps.append({"key": "human_gate", "label": "Human gate",
                  "spec": "v5.2 §2/§7", "score": s2, "max": 25, "note": n2})

    # 3 — PII defense (masking at the source)
    if st["intel_trees"] == 0:
        s3, n3 = 20, ("No identity-intel trees yet — masking coverage "
                      "untested on real fan-outs.")
    else:
        ratio = st["intel_masked"] / st["intel_trees"]
        s3 = round(25 * ratio)
        n3 = (f"{st['intel_masked']}/{st['intel_trees']} identity-intel "
              f"tree(s) include an AUDITOR mask step; {st['mask_events']} "
              f"masking event(s) on the trail.")
    comps.append({"key": "pii_defense", "label": "PII defense",
                  "spec": "v5.2 §2/§6", "score": s3, "max": 25, "note": n3})

    # 4 — Ethics gate + disclaimer coverage (§6.D)
    flags = st["safety"].get("ethics_flag", 0)
    refused = st["statuses"].get("REFUSED", 0)
    if st["complete_like"] == 0:
        disc_ratio = 1.0
    else:
        disc_ratio = st["disclaimed"] / st["complete_like"]
    s4 = round(15 * disc_ratio)
    n4 = (f"{st['disclaimed']}/{st['complete_like']} completed report(s) "
          f"carry the AI disclaimer. ")
    if flags or refused:
        s4 += 10
        n4 += (f"Ethics gate exercised: {flags} flag(s), {refused} refused "
               f"tree(s).")
    else:
        n4 += "Ethics gate not yet exercised on this dataset."
    comps.append({"key": "ethics_gate", "label": "Ethics gate & disclaimers",
                  "spec": "v5.2 §6.D", "score": s4, "max": 25, "note": n4})

    total = sum(c["score"] for c in comps)
    grade = ("A" if total >= 90 else "B" if total >= 75 else
             "C" if total >= 60 else "REVIEW")
    return {"index": total, "grade": grade, "components": comps,
            "indicator_notice": ("Operational indicator computed from local "
                                 "records — it is not an audit certification "
                                 "and says nothing about data quality (§1.9)."),
            "tree_statuses": st["statuses"]}
