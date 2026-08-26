"""ThreatHunter360 v3.0 SOVEREIGN FUSION — governed agent swarm package.

Spec: "ThreatHunter360 v3.0 — SOVEREIGN FUSION Upgrade Specification.md"
- PATHFINDER orchestration mesh (A-02, §3.3) ......... pathfinder.py
- Conversational Cortex (§3.1) ...................... cortex.py
- Agent roster + function governance (A-14) ......... registry.py
- Agents: VOYAGER (§5.1), SENTINEL (A-03/A-04),
  HUNTER (A-05), AUDITOR (A-06) ..................... agents/
- Evidence & Trust Layer (§3.2, §1.10) .............. core/trust_layer.py

Every agent output follows the canonical spine (spec §6):
ANSWER → CONFIDENCE → KEY EVIDENCE → CONTRADICTIONS → INTERPRETATION
→ RECOMMENDED ACTION → SOURCES
"""
