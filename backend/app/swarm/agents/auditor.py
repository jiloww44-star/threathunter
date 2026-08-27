"""AUDITOR agent — spec A-06, §5.2, v2 C-07.

Compliance & ethics enforcement running as a non-blocking parallel overlay on
every task tree:
- zero-trust PII masking (all outbound text passes through mask_pii)
- AML/PEP/sanctions screening (seeded feed; L3 of adaptive KYC, C-06)
- ethical gating: authorize_action() decides ALLOW / REQUIRE_HUMAN / DENY
  for every action with external effects (R-05: humans in the loop)
- immutable audit trail: every decision persisted (never silent, §20)
"""
from __future__ import annotations

import re

from ...core.kyc import sanctions_screening
from ...store.db import EvidenceStore
from ..registry import POLICY_VERSION

# ---------------------------------------------------------- action policy --
# External-effect/irreversible actions never execute autonomously in v3.0;
# they require a human (§27, R-05). Read-only analysis is allowed.
_POLICY: dict[str, str] = {
    "apply_patch": "REQUIRE_HUMAN",          # SENTINEL remediation execution
    "block_domain": "REQUIRE_HUMAN",         # HUNTER defensive action
    "isolate_host": "REQUIRE_HUMAN",
    "send_external_notification": "REQUIRE_HUMAN",
    "override_kyc_decision": "REQUIRE_HUMAN",
    "promote_custom_agent": "REQUIRE_HUMAN",  # §5.2 SDK admission
    "purge_evidence": "DENY",                 # retentionhandled by §25 jobs only
    "read_evidence": "ALLOW",
    "open_ticket": "ALLOW",
    "enroll_journey_watch": "ALLOW",
}

_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    # 14-19 digits = card lengths; shorter digit runs classify as phone/id
    (re.compile(r"\b(?:\d[ -]?){14,19}\b"), "[payment-card]"),
    (re.compile(r"\+?\d[\d\s().-]{7,}\d"), "[phone]"),
    (re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"), "[id-number]"),
]


def mask_pii(text: str) -> dict:
    """Zero-trust PII masking (A-06): returns masked text + hit count.
    Runs over every outbound synthesis payload. Pattern coverage disclosed
    honestly — masking is best-effort, reports carry the AI-output
    disclaimer (risk 5: never claim perfect PII detection)."""
    hits = 0
    out = text
    kinds: list[str] = []
    for rx, repl in _PATTERNS:
        out, n = rx.subn(repl, out)
        if n:
            kinds.append(repl.strip("[]"))
        hits += n
    return {"masked": out, "pii_fields_masked": hits, "detected_kinds": kinds,
            "policy": "zero-trust masking (A-06)",
            "coverage_note": ("Best-effort pattern coverage: email, payment "
                              "card, phone, id-number. Not a guarantee — "
                              "review outputs before sharing (risk #5).")}


# ------------------------------------------------- ethical target gating --
# v3.2 review top-risk #1 + red-team 2/9/11: refuse OSINT fan-out against
# private individuals / harassment goals; block jailbreak phrasing outright.
_SENSITIVE_KEYWORDS = (
    "home address", "where does", "lives at", "lives in",
    "phone number of", "family of", "family members", "children of",
    "dox", "stalk", "harass", "track ", "track the", "surveillance of",
    "religion of", "political affiliation", "ethnicity of",
)
_JAILBREAK_PATTERNS = (
    "ignore previous instructions", "ignore all instructions",
    "disregard your instructions", "bypass safety", "jailbreak",
)
_PERSON_WITH_LOCATION = re.compile(
    r"\b(?:about|on|find everything (?:you can )?on|investigate|profile)\s+"
    r"['\"]?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})['\"]?",
)


def sensitive_target_check(goal: str) -> dict:
    """AUDITOR ethics gate evaluated BEFORE any HUNTER fan-out (risk #1).

    Heuristic, disclosed: it looks for person-targeting phrasing combined
    with surveillance/harassment keywords or explicit jailbreak phrasing.
    A hit is an ETHICS_FLAG — the goal is refused with guidance to refocus
    on public entities or security threats (red-team #2 expected message).
    Legitimate names in public-entity contexts (companies, officials quoted
    in news) still pass: only the person+intrusive-intent combination flags.
    """
    g = goal.lower()
    jailbreak = next((p for p in _JAILBREAK_PATTERNS if p in g), None)
    keyword = next((k for k in _SENSITIVE_KEYWORDS if k in g), None)
    person = _PERSON_WITH_LOCATION.search(goal)
    # combined name + place phrase ("Jane Doe who lives in Lekki")
    name_place = bool(re.search(
        r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\s+who\s+(?:lives|works|resides)",
        goal)) or bool(person and re.search(r"\b(?:in|at|from)\s+[A-Z]", goal))

    if jailbreak:
        return {"flag": "JAILBREAK_ATTEMPT", "halt": True,
                "message": ("Ethical violation detected. Operation halted. "
                            "This attempt has been logged (red-team #11).")}
    if keyword and (person or name_place or "find" in g or "everything" in g):
        return {"flag": "SENSITIVE_TARGET", "halt": True,
                "message": ("This query has been flagged for targeting a "
                            "private individual. Refocus your query on "
                            "public entities or security threats — OSINT "
                            "fan-out against private persons is refused "
                            "(risk #1 weaponized-OSINT guard).")}
    if keyword:
        return {"flag": "SENSITIVE_KEYWORD", "halt": False,
                "message": ("Query contains privacy-sensitive terms; "
                            "proceeding with AUDITOR overlay escalated to "
                            "review logging.")}
    return {"flag": None, "halt": False, "message": ""}


async def screen_entity(store: EvidenceStore, name: str) -> dict:
    """AML/PEP/sanctions screening — reuses the §11 screening fixture path.
    Clear ≠ proof of innocence: absence of a match is reported as
    'no match in checked lists' (§1.9)."""
    matches = sanctions_screening(store, name)
    return {
        "entity": name,
        "list_matches": matches,
        "screening_state": ("MATCH_FOUND" if matches
                            else "NO_MATCH_IN_CHECKED_LISTS"),
        "trust_label": "EVIDENCE",
    }


def authorize_action(store: EvidenceStore, actor: str, action: str,
                     detail: str = "") -> dict:
    """Ethical gating (A-06). Decision is appended to the immutable audit
    trail regardless of outcome; call sites must respect `decision`."""
    decision = _POLICY.get(action, "REQUIRE_HUMAN")  # unknown → safe default
    store.audit(actor=actor, action=action, decision=decision,
                detail=detail or f"authorize_action({action})",
                policy_version=POLICY_VERSION)
    return {
        "action": action, "decision": decision, "actor": actor,
        "policy_version": POLICY_VERSION,
        "note": {
            "ALLOW": "Action may proceed.",
            "REQUIRE_HUMAN": ("Action queued for human approval — it has "
                              "external effects (§27). Nothing executed."),
            "DENY": "Action refused by sovereign policy.",
        }[decision],
    }


def validate_custom_agent(store: EvidenceStore, name: str,
                          functions: list[str]) -> dict:
    """§5.2 gate: an SDK agent is admitted ONLY via this validation.
    Approval here means SHADOW admission, not execution rights."""
    import re as _re
    issues: list[str] = []
    if not _re.fullmatch(r"[A-Za-z0-9_\-]{3,40}", name or ""):
        issues.append("name must be 3–40 chars of [A-Za-z0-9_-]")
    if not functions:
        issues.append("at least one declared api_function is required (A-14)")
    forbidden = [f for f in functions
                 if f in _POLICY and _POLICY[f] != "ALLOW"]
    if forbidden:
        issues.append(
            "custom agents cannot declare external-effect functions "
            f"(§5.2): {', '.join(forbidden)}")
    verdict = "REJECTED" if issues else "ADMIT_SHADOW"
    store.audit(actor="SDK", action="validate_custom_agent",
                decision="DENY" if issues else "REQUIRE_HUMAN",
                detail=(f"name={name} functions={functions} issues={issues} "
                        f"→ {verdict}"), policy_version=POLICY_VERSION)
    return {"verdict": verdict, "issues": issues,
            "note": ("Admitted to SHADOW mode: runs read-only alongside "
                     "native agents until a human promotes it (§5.2)."
                     if not issues else
                     "Admission refused; issues must be fixed first.")}


def compliance_overlay(store: EvidenceStore, *, tree_goal: str,
                       subjects: list[str]) -> dict:
    """v2 C-07: non-blocking parallel compliance overlay for every tree.
    Masks PII in the goal, screens named subjects, and returns disclosures —
    it never blocks task execution, and its findings are attached to the
    UnifiedReport contradictions/notices slots (§20 transparency)."""
    masked_goal = mask_pii(tree_goal)
    screenings = []
    for s in subjects[:5]:
        if not s or len(s) < 4:
            continue
        # screening is evidence, never an accusation (§12: anomaly ≠ fraud)
        hit = sanctions_screening(store, s)
        screenings.append({"subject": s,
                           "state": "MATCH_FOUND" if hit
                                    else "NO_MATCH_IN_CHECKED_LISTS",
                           "match_count": len(hit)})
    notes = []
    if masked_goal["pii_fields_masked"]:
        notes.append(f"{masked_goal['pii_fields_masked']} PII field(s) masked "
                     "in the goal before agent fan-out (A-06).")
    flagged = [s for s in screenings if s["state"] == "MATCH_FOUND"]
    if flagged:
        notes.append("Screening matches surfaced for: "
                     + ", ".join(s["subject"] for s in flagged)
                     + " — matches are signals for human review, not verdicts.")
    return {"masked_goal": masked_goal["masked"], "screenings": screenings,
            "notices": notes,
            "policy_version": POLICY_VERSION,
            "trust_label": "EVIDENCE"}
