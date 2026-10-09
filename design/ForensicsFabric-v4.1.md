# v4.1 "FORENSICS & EVIDENCE FABRIC" — spec-to-code mapping

Source of truth: `ThreatHunter360 v4.0 — Intelligence Platform Analysis &
Architecture.md`, §73 roadmap — V1.5 = *website forensics, footprint, dork
builder, source health, investigation graph* — plus two V1 leftovers
(Evidence Locker, Coverage-axis render).

## Adopted V1.5 items

| Spec ref | Requirement | Implementation |
|---|---|---|
| § "Dorking = methodology engine" | Dork builder stored as `{objective, search_engine, syntax, intended_use, risk_level, authorized_scope, source, last_verified}` + explains what/why/expected/boundaries | `backend/app/core/dork_builder.py` — per-dork dict carries the exact storage shape + `why`/`expected_results`/`boundaries`; `POST /api/v1/osint/dorks`; optional `investigation_id` binds the case's §63 scope and is lifecycle-gated (closed-case generation refused, §76) |
| § "Passive-first: PASSIVE → PUBLIC ACTIVE → AUTHORIZED ACTIVE" | Default passive | **Everything generated is `PASSIVE`** — the builder NEVER executes syntax (no live search connector in the demo profile); `execution_note` + `passive_first` strings say so on every response |
| §73 V1.5 forensics | Website/media forensics exposure | `POST /api/v1/osint/forensics/media` → A-04 `sentinel.analyze_media`; §1.9 hold: unrecognizable refs → UNVERIFIED/UNDETERMINED, never "fake"; optional `link_to_investigation` writes the §5 chain link; every call audited |
| §73 V1.5 investigation graph | Evidence chain as graph | `GET /api/v1/investigations/{id}/graph` (`core.investigation.graph`) → same GraphData model as Part 12; removed-but-linked trees render as retention notes (provenance outlives content, §26); renders in `EvidenceGraph.tsx` with new chain node types/colors |
| §73 V1.5 source health | Monitor console | endpoint shipped in v4.0 (`/feed/source-health`); UI pane deferred to the Governance console consolidation |
| § "footprint" | OSINT footprint sweep | HUNTER `identity_intel` branch already runs footprint_scan via PATHFINDER (v3.3); coverage gaps honestly disclosed — no new surface needed |

## V1 leftovers closed

| Spec ref | Requirement | Implementation |
|---|---|---|
| §73 V1 Evidence Locker | browse stored evidence with provenance | `GET /api/v1/evidence/locker?q=&source=&limit=` — every row carries source/authority/fetch-time; "absence = nothing stored, never a verdict (§1.9)"; Ops Node **Locker** pane with search |
| §49–51 | Coverage beside Confidence in the UI | `coverage` chip + `coverage_basis` render in `FactChecker.tsx` result header (type existed since v4.0, now rendered) |

## Ops Node surface changes

- New **Evidence Locker** pane (search + provenance table).
- **Cases tab** gains per-case **⛓ Graph** (evidence-chain expansion) and
  **🔎 Build dorks** (generation-only table with why/boundaries).
- Fact Checker result shows Coverage chip with basis tooltip.

Failure posture (§20) — carried through:
- unknown subject_type / search engine → honest `degraded_note`, baseline
  template only, default engine disclosed;
- closed case + dork-id → 403 §76 (generation done "in a case's name" is
  work under authorization too);
- removed linked artifact → graph node with retention note, never a hole.

## Tests

`backend/tests/test_v41_forensics_fabric.py` — 18 tests: dork storage shape,
generation-only / passive-first assertions, substitution, honest degrades,
route bindings + 403-on-closed, A-04 fixture / unrecognizable refs, chain
graph nodes/edges + retention note + 404, locker provenance/search/clamp.
