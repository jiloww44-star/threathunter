"""Conversational Cortex — spec §3.1 (restores the v1 soul at v2 scale).

A dialogue layer ON TOP of PATHFINDER RGD, not instead of it:
- natural conversation or one-shot goals, same engine underneath
- context object persists across turns (origin, destination, journey_context)
  — no form restarts (v1 §14)
- minimal clarifying questions (§14–15): the Cortex asks only what materially
  changes the analysis; everything else is auto-decomposed by RGD
- conversation → TaskTreeJSON in real time; the reply carries the tree_id so
  the Ops Node Strategy Map updates live
- progress narration synced to the task tree (§21): each reply includes the
  agents' live activity lines
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ..store.db import EvidenceStore
from . import pathfinder
from .agents import voyager

_TTL_S = 3600  # conversational context lifetime (documented, §25 minimization)
_SESSIONS: dict[str, dict] = {}

_GREETING = ("I'm the ThreatHunter360 cortex — I can check a claim, advise "
             "on a journey, screen an entity, or run a security sweep. "
             "Just tell me what you need in your own words.")


def _session(session_id: str) -> dict:
    now = time.time()
    # TTL sweep — context expires, nothing retained longer than needed (§25)
    stale = [k for k, v in _SESSIONS.items() if now - v["_touched"] > _TTL_S]
    for k in stale:
        _SESSIONS.pop(k, None)
    s = _SESSIONS.setdefault(session_id, {
        "origin": None, "destination": None, "departure_hint": None,
        "claim": None, "intent": None, "pending": None, "last_tree_id": None,
        "journey_context": "inactive", "_touched": now})
    s["_touched"] = now
    return s


def _departure_from_hint(hint: str | None) -> datetime | None:
    now = datetime.now(timezone.utc)
    if hint == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=8, minute=0, second=0,
                                                 microsecond=0)
    if hint == "tonight":
        d = now.replace(hour=21, minute=0, second=0, microsecond=0)
        return d if d > now else d + timedelta(days=1)
    if hint == "today":
        return now + timedelta(hours=1)
    return None


def _narration(report: dict, store: EvidenceStore, tree_id: str) -> list[str]:
    """§21 — meaningful progress lines derived from REAL task outcomes."""
    lines = []
    for t in store.tasks_for_tree(tree_id):
        if t["status"] == "PENDING":
            continue
        state = {"COMPLETE": "done", "DEGRADED": "degraded",
                 "FAILED": "failed", "BLOCKED": "blocked",
                 "AWAITING_HUMAN": "awaiting human"}.get(t["status"],
                                                         t["status"].lower())
        lines.append(f"{t['agent']} · {t['title']} — {state}")
    return lines


def _reply_text(report: dict) -> str:
    conf = report.get("confidence", "UNDETERMINED").replace("_", " ")
    act = report.get("recommended_action", "")
    return (f"{report.get('answer', '').strip()}\n\n"
            f"Confidence: {conf}. {act}".strip())


async def _chat_inner(store: EvidenceStore, session_id: str, message: str
                      ) -> dict:
    s = _session(session_id)
    text = (message or "").strip()
    lower = text.lower()

    # ------------------------------------------------ answer to a pending Q
    if s.get("pending"):
        intent = s["pending"]
        s["pending"] = None
        if intent == "journey_route":
            guess = text if " to " in lower else f"from {text}"
            ctx = voyager.parse_route_context(guess)
            s["origin"] = ctx.get("origin") or s["origin"]
            s["destination"] = ctx.get("destination") or s["destination"]
        elif intent == "journey_time":
            if "tomorrow" in lower:
                s["departure_hint"] = "tomorrow"
            elif "tonight" in lower or "night" in lower:
                s["departure_hint"] = "tonight"
            elif "now" in lower or "today" in lower or "hour" in lower:
                s["departure_hint"] = "today"
        elif intent == "claim_text":
            s["claim"] = text

    # --------------------------------------------------------- fresh intent
    else:
        if lower in ("hi", "hello", "hey", "help", "start"):
            return {"text": _GREETING, "question": None,
                    "context": _public(s), "tree_id": None, "progress": []}
        intents = pathfinder.classify_goal(text)
        s["intent"] = intents[0] if intents else None
        if "journey" in intents:
            s["journey_context"] = "active"
            ctx = voyager.parse_route_context(text)
            s["origin"] = ctx.get("origin") or s["origin"]
            s["destination"] = ctx.get("destination") or s["destination"]
            s["departure_hint"] = (ctx.get("departure_hint")
                                   or s["departure_hint"])
        if "claim" in intents and len(text) >= 20:
            s["claim"] = text

    # ----------------------------------- minimal clarifying questions (§15)
    if s.get("intent") == "journey":
        if not s.get("origin") or not s.get("destination"):
            s["pending"] = "journey_route"
            return {"text": "Happy to advise on the journey. Where are you "
                            "leaving from, and where are you headed?",
                    "question": "route", "context": _public(s),
                    "tree_id": None, "progress": []}
        if not s.get("departure_hint"):
            # day vs night materially changes the security profile (demo
            # scenario 3) — this one question matters; nothing else is asked.
            s["pending"] = "journey_time"
            return {"text": f"Route noted: {s['origin']} → "
                            f"{s['destination']}. Roughly when do you plan "
                            f"to leave — today, tonight, or tomorrow?",
                    "question": "departure", "context": _public(s),
                    "tree_id": None, "progress": []}
        goal = (f"Journey from {s['origin']} to {s['destination']} "
                f"{s['departure_hint']}")
        context = {"origin": s["origin"], "destination": s["destination"],
                   "departure_time": _departure_from_hint(s["departure_hint"])}
    elif s.get("intent") == "claim" and s.get("claim"):
        if len(s["claim"]) < 12:
            s["pending"] = "claim_text"
            return {"text": "What exactly is the claim you'd like me to "
                            "check? Paste it in one sentence.",
                    "question": "claim", "context": _public(s),
                    "tree_id": None, "progress": []}
        goal = s["claim"]
        context = {"claim": s["claim"]}
    else:
        # one-shot goals — RGD decomposes with zero questions (v2 C-02)
        goal = text
        context = {}

    # --------------------------------------------- hand off to PATHFINDER
    report = await pathfinder.run_goal(goal, store, context=context)
    s["last_tree_id"] = report["tree_id"]
    progress = _narration(report, store, report["tree_id"])
    return {
        "text": _reply_text(report),
        "question": None,
        "context": _public(s),
        "tree_id": report["tree_id"],
        "confidence": report.get("confidence"),
        "report": report,
        "progress": progress,
        "speakable": True,   # §18 voice path: /api/v1/voice/spoken-summary
    }


def _public(s: dict) -> dict:
    """Context snapshot for the UI (no internal keys, §25 minimization)."""
    return {k: v for k, v in s.items()
            if k in ("origin", "destination", "departure_hint", "intent",
                     "journey_context", "last_tree_id")}


def purge_session(session_id: str) -> int:
    """v3.2 Manage-Data exit ramp: delete conversational context NOW instead
    of waiting for the 1h TTL (§25 minimization on demand)."""
    s = _SESSIONS.pop(session_id, None)
    return len([k for k in (s or {}) if s.get(k)])


# ---------------------------------------------------------------------------
# v3.4 — crisis-signal detection (red-team review #3: crisis pathways must be
# real, not cosmetic — and the cortex must RECOGNISE crisis language instead
# of calmly continuing a routine conversation).
# ---------------------------------------------------------------------------

# Live, first-person emergency language. Deliberately conservative: intel
# vocabulary like "breach report" or "data leak check" is NOT here.
_CRISIS_PHRASES = (
    "we are under attack", "we're under attack", "under active attack",
    "we've been breached", "we have been breached", "we've been hacked",
    "we have been hacked", "just got breached", "ransomware hit",
    "hit by ransomware", "ransomware on our", "intrusion in progress",
    "attack in progress", "ongoing attack", "data is being exfiltrated",
    "being exfiltrated", "active incident right now", "security emergency",
    "emergency right now", "this is an emergency", "we are offline",
    "systems are down", "help us now", "need help immediately",
    "compromised right now", "as we speak",
)

# Scenario/tabletop phrasing suppresses the signal — a drill must not page
# the on-call (false crisis security cuts both ways, review risk 3).
_CRISIS_SUPPRESS = ("what if", "hypothetical", "hypothetically", "scenario",
                    "imagine", "tabletop", "drill", "exercise", "training",
                    "for a story", "in a movie")


def detect_crisis(text: str) -> str | None:
    """Return the matched crisis phrase, or None. Pure function — the wrapper
    decides what to do with it."""
    lower = (text or "").lower()
    if any(k in lower for k in _CRISIS_SUPPRESS):
        return None
    for p in _CRISIS_PHRASES:
        if p in lower:
            return p
    return None


_CRISIS_NOTICE = (
    "⚠ This sounds like a LIVE incident. If you are in crisis: use the "
    "Crisis Override (Declare Incident) — it notifies on-call honestly, "
    "locks down the workspace and opens the response checklist. I'll keep "
    "assisting below, but declared incidents take priority over chat.")


async def chat(store: EvidenceStore, session_id: str, message: str
               ) -> dict:
    """Crisis-aware wrapper around the dialogue engine: normal conversation
    keeps flowing, but crisis language (1) prepends an honest notice, (2)
    returns a `crisis` action hint so the UI can surface the real pathway,
    and (3) feeds the safety learning loop ONCE per session."""
    s = _session(session_id)
    phrase = detect_crisis(message)
    resp = await _chat_inner(store, session_id, message)
    if phrase:
        resp["text"] = f"{_CRISIS_NOTICE}\n\n{resp['text']}"
        resp["crisis"] = {"phrase": phrase, "action": "declare_incident"}
        if not s.get("_crisis_logged"):
            from . import safety
            safety.log_event(store, "crisis_signal_detected",
                             actor=session_id,
                             detail=f"crisis phrase '{phrase}' in cortex chat")
            s["_crisis_logged"] = s["_touched"]
    return resp
