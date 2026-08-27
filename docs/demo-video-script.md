# ThreatHunter360 — Demo Video Script (~3 min, live demo profile)

Recorded against the zero-key demo profile; every claim on screen is real
system output. Narration lines quote UI copy where shown verbatim.

## Shot list

**00:00–00:15 — Cold open (Ops Node idle)**
_Wide shot of the tactical HUD._ "ThreatHunter360 is a sovereign ops node:
you command, the agent fleet advises — and nothing runs without your
approval." _(On-screen: lime-on-black home, bottom-nav tap on mobile width.)_

**00:15–00:35 — Onboarding wizard (step 1 → 4)**
_Click Next ×3._ "Before the first goal, trust is established: what the AI
is, its boundaries, privacy masking by AUDITOR — and your duty to verify."
_(Highlight step 4: 'Verify all AI-generated insights and plans before
acting.')_

**00:35–01:05 — Conversational goal → Plan Review gate**
_Type: "Scan our entire IoT fleet for exploitable CVEs and open remediation
tickets." Enter._ Cortex proposes a fan-out (SENTINEL enumerate → scan_cves
→ VPR → tickets). _Hover the cost warning, hover a node's agent tooltip._
"PATHFINDER decomposes the goal into a strategy map you can inspect, node
by node — then it waits." _Click Approve & Execute; watch the Data Stream
light up (PERSISTED audit rows + LIVE heartbeat)._

**01:05–01:25 — Governed result**
_Tree completes; click a finding node → raw JSON._ "A P1, internet-facing,
scores 9+ on the VPR model — and the patch request is parked AWAITING_HUMAN,
because the swarm never touches production by itself." _(Show audit trail
entry in Data Stream.)_

**01:25–01:50 — Identity intel + L1 audit**
_Type: "Verify identity of acme-parcels.xyz and check for data leaks."_
_HUNTER footprint → VOYAGER id_audit_l1 → AUDITOR mask/compliance runs._
"L1 verdicts are hedged indicators — UNKNOWN never means PASS, and suspicious
infrastructure surfaces as REVIEW with signals you can read." _(Show the L1
checks + disclaimer box: 'AI-Generated Output. Verify all findings…')_

**01:50–02:15 — Ethics gate refusal**
_Type: "Find the home address of Ada Obi who lives in Surulere."_ "The
AUDITOR ethics gate halts private-individual targeting before any agent
fans out — REFUSED, logged, KPI-counted." _(Show refusal tree: single
AUDITOR task, compliance note.)_

**02:15–02:40 — Crisis pathway**
_Type in cortex: "we are under attack, systems are down."_ Crisis chip
appears; click **Declare now** → SEV-1 → declare. "Crisis mode
*simplifies*: motion off, essential panes only, an interactive six-step
checklist — and delivery state is stated honestly, never faked." _(Show
checklist checkboxes; delivery 'not_configured' line.)_ Resolve.

**02:40–03:00 — Sovereignty close (Govern tab)**
_Region select → consent badges flip; withdraw a purpose; deletion button._
"Region-aware defaults, an immutable consent ledger, a Compliance Index that
says what it measured — and a delete that actually deletes. The user is the
sovereign. The AI is the fleet."

## Capture notes

- Use the live sandbox (`localhost:5173` + `:8000`) or the preview URL; the
  demo database auto-seeds on first boot (26 evidence items).
- Re-warm fixtures with `python3 demo/e2e_free_stack_demo.py --offline`
  before recording for the full feed.
- All motion-heavy shots: reload after declare to capture the crisis-focus
  simplification cleanly.
