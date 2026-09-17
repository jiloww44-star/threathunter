"""Classified pipeline errors — spec §20 / Part 1.7.

Errors surface classified codes with what happened / what it means / what to
do next — never a fabricated result.
"""
from __future__ import annotations


class PipelineError(Exception):
    def __init__(self, code: str, status: int = 502, detail: str = ""):
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(f"{code}: {detail}")


ERROR_MAP: dict[str, tuple[str, str, str]] = {
    "SOURCE_UNAVAILABLE": (
        "A data source could not be reached",
        "Results may be less complete than usual",
        "Retry shortly; we refresh automatically",
    ),
    "INSUFFICIENT_EVIDENCE": (
        "Not enough reliable evidence was found",
        "No confident conclusion is possible",
        "Add context, rephrase, or try again later",
    ),
    "DOCUMENT_UNREADABLE": (
        "The uploaded document could not be processed",
        "Verification is paused",
        "Upload a clearer photo or a different format",
    ),
    "STT_UNAVAILABLE": (
        "The speech transcription service is unavailable",
        "Voice input cannot be processed right now",
        "Type your request instead — all flows work the same",
    ),
    "RATE_LIMITED": (
        "Too many requests",
        "The service is protecting result quality",
        "Wait a moment and retry",
    ),
    "LLM_UNAVAILABLE": (
        "The AI narrative service is unavailable",
        "Deterministic analysis continues — conclusions are unaffected",
        "Configure OPENROUTER_API_KEY or continue without narratives",
    ),
    "LLM_BUDGET_EXCEEDED": (
        "The spend guard stopped a paid AI call (§2.4 credit budget)",
        "Free-tier slot exhausted for this window",
        "Retry after reset or raise purpose caps in config/budget.yaml",
    ),
    "SOURCE_DEGRADED": (
        "A source's credit budget is exhausted",
        "Evidence shown is from the last successful fetch (staleness visible)",
        "Wait for the budget window to reset or upgrade the source tier",
    ),
    "TREE_NOT_FOUND": (  # v3.0 ops
        "No task tree exists for that id",
        "The Strategy Map cannot be displayed",
        "Run a goal first, or check the id in the Swarm Timeline",
    ),
    "AGENT_NOT_FOUND": (
        "No agent is registered under that id",
        "The governance operation cannot proceed",
        "Register the agent via the SDK endpoint first (§5.2)",
    ),
    "CONSENT_REQUIRED": (  # §5.3 privacy completion
        "Consent is required for this data use",
        "Your preferences were NOT saved — nothing was stored silently",
        "Grant the named purpose in Settings → Privacy, then retry",
    ),
    "INVALID_PREFERENCE": (
        "A preference value is outside its allowed range",
        "The change was not applied",
        "Pick one of the listed allowed values",
    ),
    "INVALID_CONSENT": (
        "The consent record is not valid",
        "Consent was not recorded",
        "Use a declared purpose and state 'granted' or 'withdrawn'",
    ),
    "INCIDENT_NOT_FOUND": (  # v3.2 crisis pathway
        "No active incident matches that id",
        "The resolve action could not be completed",
        "Check the active incident in the Ops Node",
    ),
    "INVALID_SEVERITY": (
        "Incident severity must be SEV1, SEV2 or SEV3",
        "The declaration was not recorded",
        "Pick a declared severity level and retry",
    ),
    "PLAN_NOT_PENDING": (
        "That plan is not waiting for approval",
        "It may already be approved, cancelled or finished",
        "Refresh the Strategy Map to see its current state",
    ),
    "ACTION_DENIED": (  # v4.0 §76 invariant gate
        "The requested action is not authorized",
        "§76: no consequential action without living authorization",
        "Open or renew an investigation whose scope allows this action",
    ),
}
