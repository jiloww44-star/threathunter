"""Retention Policies — v4.4 Enterprise plane (§73: retention/policies).

Windows are DECLARED, per-class, and deterministic (§54). Two classes are
PERMANENT by invariant and the sweeper cannot touch them:
  audit_trail     — append-only plane (.delete_* methods don't exist by
                    design for it)
  consent_ledger  — §5.3 tamper-evident chain; deleting an entry would
                    break verification and posture would go CRITICAL by
                    construction (v4.3 tests).

`apply_retention` runs dry-run by default (§20: never destructive without
an explicit apply), is admin-gated at the route, and reports per-class
counts with the policy that produced them — auditable by definition.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

DEFAULT_POLICY = {
    "notifications_days": 90,
    "assurance_runs_days": 180,
    "terminal_trees_days": 30,      # COMPLETE/CANCELLED/REFUSED only
    "permanent_classes": ["audit_trail", "consent_ledger",
                          "evidence (provenance-first store)",
                          "investigation_links (§5 chain)"],
}
POLICY_VERSION = "retention/4.4.0"


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def apply_retention(store, *, policy: dict | None = None,
                    dry_run: bool = True, actor: str = "retention-admin"
                    ) -> dict:
    p = {**DEFAULT_POLICY, **(policy or {})}
    notif_cut = _cutoff(p["notifications_days"])
    asr_cut = _cutoff(p["assurance_runs_days"])
    tree_cut = _cutoff(p["terminal_trees_days"])

    # measure without deleting for dry runs
    notifs = count_notifications_older = _count(
        store, "SELECT COUNT(*) FROM notifications WHERE created_at < ?",
        (notif_cut,))
    runs = _count(store,
                  "SELECT COUNT(*) FROM assurance_runs WHERE started_at < ?",
                  (asr_cut,))
    old_tree_ids = store.old_trees(tree_cut)

    report = {
        "dry_run": dry_run,
        "policy": {k: v for k, v in p.items() if k.endswith("_days")},
        "permanent_classes": p["permanent_classes"],
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": POLICY_VERSION,
        "classes": {
            "notifications_older_than_cutoff": {"count": notifs,
                                                "action": "deleted"
                                                if not dry_run
                                                else "would_delete"},
            "assurance_runs_older_than_cutoff": {"count": runs,
                                                 "action": "deleted"
                                                 if not dry_run else
                                                 "would_delete"},
            "terminal_trees_older_than_cutoff": {"count": len(old_tree_ids),
                                                 "action": "deleted"
                                                 if not dry_run else
                                                 "would_delete"},
        },
        "note": ("audit_trail and consent_ledger are PERMANENT by design —"
                 " the sweeper has no code path to them, and consent-chain"
                 " deletion would self-evidence a CRITICAL posture."), }

    if not dry_run:
        report["classes"]["notifications_older_than_cutoff"]["count"] = (
            store.delete_notifications_older_than(notif_cut))
        report["classes"]["assurance_runs_older_than_cutoff"]["count"] = (
            store.delete_assurance_older_than(asr_cut))
        deleted_trees = 0
        for tid in old_tree_ids:
            store.delete_tree(tid)
            deleted_trees += 1
        report["classes"]["terminal_trees_older_than_cutoff"]["count"] = (
            deleted_trees)

    store.audit(actor=actor,
                action="retention:applied" if not dry_run
                       else "retention:dry_run",
                decision="ALLOW",
                detail=(f"notifications={notifs} assurance_runs={runs} "
                        f"trees={len(old_tree_ids)} dry_run={dry_run}"),
                policy_version=POLICY_VERSION)
    return report


def _count(store, sql: str, args: tuple) -> int:
    with store._lock:
        return store._conn.execute(sql, args).fetchone()[0]
