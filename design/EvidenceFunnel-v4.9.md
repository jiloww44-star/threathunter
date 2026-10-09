# v4.9 EVIDENCE FUNNEL — the pipeline into the §72 north-star (mapping doc)

**Origin (documented openly, NOT a spec addition):** `design/ContextualSystems-v1.md`
hypothesis H3 — the framework's own status-request…uncertainty loop applied to the
platform: operators would keep asking *"is it working?"* because §72's
denominators were invisible until a case closed. v4.9 makes the whole
pipeline measurable and visible. §72's definition **did not change**.

## What shipped

| Piece | Where | Notes |
|---|---|---|
| Funnel engine | `backend/app/core/funnel.py` (`funnel-engine/4.9.0`) | cumulative-set stages, honest conversions, cohort lens |
| Route | `GET /api/v1/ops/funnel` (`?window_hours=` for cohort) | RBAC `read` (viewer+), same as §71 surfaces |
| UI | `FunnelPanel` in OpsNode KPI pane, above §71 families | stage cards with basis tooltips, honest conversion chips |
| Version | root banner → `4.9.0 EVIDENCE FUNNEL` | |
| Tests | `backend/tests/test_v49_funnel.py` — 10 tests | suite 347 → **357** |

## Stages (cumulative-set filters over `investigations`)

| Stage | Query basis (§20 measured-or-said) | Design decision |
|---|---|---|
| `opened` | investigations created | — |
| `observed` | ≥1 `event:SourceQueried` audit row naming the case (`INSTR(detail, i.id)`) | **Denied attempts count** — an attempt is operator behavior; v4.8 made failure visible by putting the case id on DENY rows. Legacy rows without the id are pinned NOT to count (honest regression test). |
| `linked` | ≥1 `investigation_links` row `kind='evidence'` | seed evidence counts — a link is a link |
| `closed` | `status='CLOSED'` | — |
| `completed` | **the EXACT §72 north-star query** | query-consistency, not re-definition |

## Conversions (honest denominators)

`attempt_rate = observed/opened`, `link_rate = linked/opened`,
`close_rate = closed/opened`, and the headline
`evidence_backed_completion = completed/closed`. Empty denominator ⇒
`UNAVAILABLE` with basis *"rate undefined, not zero"* — never a fabricated
`0.0` (§20). When the denominator exists, `0.0` is shown truthfully.

## Consistency invariant

All-time lens only: `funnel.completed` is recomputed with the north-star's
own query and compared against `kpis._north_star()` in every response;
the payload carries `north_star_consistency{.., match}` and the UI shows
✓/✗. **A mismatch is a defect, not a nuance** — and it is test-pinned.
Cohort lens omits the claim (the north-star is all-time).

## Live verification (2026-10-09, fresh seed instance, post-wipe)

1. **t0 empty:** all stages 0, all conversions UNAVAILABLE, consistency ✓ (0≡0).
2. **t1 full loop:** case opened → 409 `CONNECTOR_NOT_ACTIVE` (gate before
   wire — no fake attempt row) → evidence linked → closed ⇒
   opened=1, observed=0, linked=1, closed=1, **completed=1**,
   headline ratio 1.0, **§72 north-star flipped 0 → 1**, consistency ✓.
3. **t2 closed-case attempt:** 403 `ACTION_DENIED` — §76 holder, funnel unmoved.
4. **t2 connector path:** register (PENDING) → `/ops/approvals/{id}/approve` →
   ACTIVE — §26 chain exercised live.
5. **t3 open-case attempt:** 503 `SOURCE_UNREACHABLE` (the root-caused
   sandbox SNI wall, `design/EgressDiagnosis-v1.md`) — DENY row carries the
   case id ⇒ **observed=1, attempt_rate=0.5 over 2 opened**.
6. **Cohort lens:** `?window_hours=24` ⇒ cohort label, same counts for a
   same-day case, consistency claim correctly omitted.

Every failure mode hit during the run was one the platform *designed* to
say out loud. Nothing fabricated, nothing hidden.

## Test coverage (10)

empty-store honesty (stages 0, conversions UNAVAILABLE, 0≡0 consistency) ·
opened-only (0.0 rates defined when denominator exists; headline still
UNAVAILABLE) · denied-attempt counted · **legacy no-id attempt NOT counted**
(regression pin) · link→close pipeline · closed-without-evidence not
completed · mixed-state funnel≡north-star (wrong-kind link excluded,
open-linked case excluded) · cohort filtering + lens label + consistency
omission · route shape + every stage carries a basis · cohort route param.

## TRUST addendum ↔ TRUST.md §18 (blast radius / review)

- **Blast radius: LOW.** Read-only aggregation over existing tables
  (`investigations`, `audit_trail`, `investigation_links`); the only
  write-path is the response. `kpi_sql` SELECT-only chokepoint unchanged.
- **Failure mode honesty:** any SQL error would surface as a classified
  PipelineError (§20); the UI renders absence with the same sentence as the
  §71 plane.
- **Risk of misuse (the real one):** a funnel can tempt theater ("make the
  bars green"). Mitigations baked in: completed ≡ north-star consistency
  check; basis strings on every stage; `observed` counts *attempts*, not
  success, with that fact printed in the notes.
- **Review level: D1** (governance-visible plane; no human-decision effects).
