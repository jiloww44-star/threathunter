# v4.8 — CHRONOLOGY & REPRODUCIBILITY · spec-mapping doc

This tranche closes the last unbuilt block of §66-72.

Spec text: *"Investigation Canvas (interactive evidence graph) · immutable
investigation chronology (§67) · source-change detection (response,
retrieved_at, content hash, parser version, source version) ·
reproducibility (query, source, params, timestamp, tool/parser version,
authorization, result hash → 'Re-run investigation')."*

| Spec block | Built where | Status before v4.8 |
|---|---|---|
| Investigation Canvas | v4.1 EvidenceGraph + chain node types | done |
| source-change detection | v4.7 persist_observation (hash/supersede/parser+source versions) | done |
| immutable chronology (§67) | **v4.8 `core/chronology.py`** | **this tranche** |
| reproducibility + "Re-run" (§68) | **v4.8 `live_sources.rerun_observation`** | **this tranche** |

## 1. §67 immutable chronology — derived, digest-committed, never a second history

Design decision (mutually exclusive options): (a) a chronology TABLE — a
second history that could diverge and would itself need to be trusted;
(b) **derive on read** from the permanent append-only audit trail
(PERMANENT retention invariant since v4.4), the column-scoped link table,
and the case row — assembled deterministically and committed by a
recomputed SHA-256 digest. v4.8 is (b): one history exists; the chronology
is a faithful read of it; tampering with a trail row changes the digest,
which makes edits visible to any auditor (test-pinned with a direct SQL
tamper).

Honest scoping (§20, stated in every response's `derivation`): trail rows
are matched by the case id in their detail text (the v4.0+ §26 events all
carry it); case-opened is synthesized from the case row because
`InvestigationCreated` predates the id-bearing convention; nothing is
inferred beyond string equality — early cases' chronologies may be thinner,
never padded.

Endpoint: `GET /api/v1/investigations/{id}/chronology` — ordered, kinded
(LIFECYCLE / AUTHORIZATION / OBSERVATION / GOVERNANCE / ALERT / LINK /
TRAIL), actor+decision+policy_version per event, digest + version header.
Cases tab gains a 🕰 Chronology expansion rendering exactly this.

## 2. §68 "Re-run investigation" — replay from stored provenance

The v4.5/4.7 observation rows were deliberately written to hold the full
§68 replay tuple: query / source / params / timestamp / parser+source
version / authorization (case id, re-validated at replay) / result hash.
Replay is therefore **built, not bolted on**:

`POST /api/v1/osint/live/rerun {evidence_id}` →
- 404 EVIDENCE_NOT_FOUND if the row is gone;
- 422 REPLAY_NOT_AVAILABLE if the row wasn't produced by a governed live
  observation (§68 is honest: the replayable tuple is recorded *at ingest*
  — seed/imported evidence says so instead of pretending);
- 409 CONNECTOR_NOT_ACTIVE if the producing connector was retired (replays
  run through the §80 registry too);
- otherwise the **full governed path re-executes** (§76 living-case → §63
  cone → allowlist → classified fetch → persist) and the response says
  `outcome: UNCHANGED` (same hash — idempotent no-op, zero new rows, no
  change event) or `outcome: CHANGED` (new row, `supersedes`,
  ObservationChanged) — the §67 detector *is* the comparator;
- every replay mints `event:ObservationRerun` (platform extension,
  documented in TRUST §17 with the v4.3/v4.6 precedent).

## 3. §76 on replays

A replay is a consequential action taken in a case's name: a CLOSED or
expired case replays **nothing** (403 with the authorization meaning —
test-pinned alongside the honest seed-evidence 422). This is the exact
invariant wording made executable: no consequential action without *living*
authorization — not even a replay of something once authorized.

## 4. TRUST posture

Blast radius: **LOW-MEDIUM**, review **D1/D2** (the digest tamper test and
the closed-case replay guard are the load-bearing proofs; no new write
classes — replays reuse the v4.5/4.7 paths byte-for-byte).

## 5. Gates

`tests/test_v48_chronology_repro.py` — 13 tests (stable digest, ordering,
kinds, digest-moves-with-history, **tamper visibility**, 404, derivation
honesty, UNCHANGED no-op replay, CHANGED supersession, closed-case 403,
seed-evidence 422 with the honest detail, missing 404, retired-connector
409, RBAC 403, source-down replay writes nothing). **344/344 backend
green**, tsc/vite clean.
