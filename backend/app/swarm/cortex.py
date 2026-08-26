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


async def chat(store: EvidenceStore, session_id: str, message: str
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
