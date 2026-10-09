"""Voice interaction endpoints — spec Part 11 (§18).

Design decision (spec 11.1): voice is an input/output *adapter* over the same
API — no separate voice logic. Production STT/TTS providers (Whisper etc.)
plug in behind STTService/TTSService; demo profile uses the browser's Web
Speech API for STT and returns a spoken-summary text for client-side TTS
(speechSynthesis), so the feature degrades gracefully everywhere (§20).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...api.deps import current_user

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])


@router.post("/spoken-summary")
async def spoken_summary(payload: dict, user=Depends(current_user)):
    """Response text optimized for listening (spec 11.3): verdict → confidence
    → one-sentence answer → contradiction note → recommended action."""
    result = payload.get("result") or {}
    verdict = str(result.get("verdict") or result.get("decision") or "UNKNOWN")
    confidence = str(result.get("confidence") or "unknown")
    parts = [
        f"{verdict.replace('_', ' ').title()}. Confidence: {confidence.lower()}.",
        result.get("answer", ""),
    ]
    contradictions = result.get("contradictions") or []
    if contradictions:
        parts.append(f"Note: {len(contradictions)} contradiction(s) found.")
    if result.get("recommended_action"):
        parts.append(f"Recommended action: {result['recommended_action']}")
    return {"spoken_text": " ".join(p for p in parts if p),
            "mode": "client-tts",   # browser speechSynthesis in demo profile
            "detail": "Server-side TTS streams audio in the production profile "
                      "(Part 11.2)."}
