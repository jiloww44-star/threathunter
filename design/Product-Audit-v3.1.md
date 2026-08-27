# Design Audit & Product Brainstorm — v3.1 tranche
*Inputs: live audit of the shipped v3.0 build + the SOVEREIGN FUSION master
spec's open items (§3.4, §5.3, §5.4, §8 P3/P4). Produced 2026-08-27.*

## 1. Design audit — what the current build does well

| Area | Finding | Evidence |
|---|---|---|
| Response consistency | Every module returns the §19/§6 spine; one progressive-disclosure result card everywhere | `models/schemas.py`, `result-card` CSS |
| Design tokens | v2 tokens: dark/light `color-scheme`, fluid type, kicker/SMU type scale, 44px touch floor, elevation shadows | `styles/tokens.css` |
| Honest degradation visible | Staleness markers, `data_mode` markers, review-lane chips, classified error panels (§20) | all views, `shared.tsx ErrorPanel` |
| Motion & a11y | `prefers-reduced-motion` honored in 2 blocks; breakpoints 720/920px | `app.css` |
| Ops Node | Conversation traces to task trees; strategy map/timeline/alerts/feed/KPIs in one pane | `OpsNode.tsx` |

## 2. Gaps found (spec-traceable)

1. **§3.4 Personalization — not actually built.** Claimed under P3 ("personalization
   layer") but absent: no saved entity watchlists (v1 §22), no default journey
   priority, no default alert threshold, no output-format preference.
   TRUST.md §5.5 promised "shapes presentation, never conclusions" with no
   enforcing mechanism.
2. **§5.3 Privacy — consent was a dead checkbox.** The KYC "I consent" button
   recorded nothing; no consent ledger existed. Retention (§25) existed, but
   the spec demands an *immutable, auditable consent ledger*.
3. **§5.4 Low-bandwidth mode — absent.** JourneyMap always loaded map tiles;
   no `saveData`/2G detection. Spec explicitly requires "text-first Strategy
   Map + verdict summaries".
4. **No Settings surface** — preferences had nowhere to live, and privacy
   controls were undiscoverable.

## 3. Brainstorm — candidates considered

| Idea | Spec anchor | Decision | Why |
|---|---|---|---|
| A. Personalization layer | §3.4, P3 exit | **BUILD** | completes P3 honestly; high user value |
| B. Consent ledger (hash-chained) + consent-gated data uses | §5.3, P4 | **BUILD** | privacy completion; auditable |
| C. Low-bandwidth degraded mode | §5.4 | **BUILD** | a11y parity; Lagos-relevant (metered mobile) |
| D. D3 rolling calibration from override labels | TRUST.md D3 | next tranche | needs 4-week pilot override data first |
| E. Hyperscale certification | P4 | production phase | benchmarking infra, not demo code |
| F. Demo video script | spec §9 offer | docs phase | narrative deliverable, not platform |

Selected tranche: **A + B + C** — one coherent "trust & access" story:
personalization exists but only with consent, consent is provable, and the
platform stays fully usable on a 2G phone.

## 4. Shipped (this tranche)

### Backend
- `store` — `user_preferences` + `consent_ledger` tables (append-only consent
  has no UPDATE/DELETE path; migration-safe `CREATE IF NOT EXISTS`).
- `core/privacy.py` — `record()` hash-chain append (each entry commits to its
  predecessor), `current_state()`, `verify_chain()` one-call tamper check,
  closed purpose set (`kyc_biometrics | personalization | journey_history |
  analytics`). Every event also lands on the AUDITOR trail.
- `core/personalization.py` — watchlists/journey_priority/notify_tolerance/
  output_format with **consent-gated writes** (§20-classified
  `CONSENT_REQUIRED`, nothing stored silently); `reassess_watchlists()`
  drift alerts (WATCHLIST_ALERT) wired into the §1.10 loop.
- **Enforcement test**: identical journey/claim analyses run under opposing
  preference profiles → verdict/risk output byte-identical. "Personalization
  shapes presentation, not conclusions" is now CI-enforced.
- Watch enrolment defaults `tolerance` from the user's preference —
  disclosed as `tolerance_source` in the response; scores unchanged.

### Frontend
- New **Settings view** (`#/settings`): demo-user identity, consent grant/
  withdraw per purpose with live hash-chain integrity badge, personalization
  controls (priority/tolerance/format/watchlist editor), access modes.
- **§5.4 low-bandwidth mode**: auto (`Save-Data` / 2G `effectiveType`) +
  manual override; `data-bandwidth` attribute gates animations/shadows;
  JourneyMap renders a text-first risk strip with identical information and
  a disclosure line ("Map tiles skipped — low-bandwidth mode §5.4").
- **KYC consent is real**: "I consent — run verification" now writes the
  grant to the §5.3 ledger before biometrics run (best-effort in demo;
  ledger outage never blocks verification — §20).

### Tests
`tests/test_privacy_personalization.py` — 10 tests: chain integrity, tamper
detection, withdrawal semantics (new entry, history kept), purpose closed-set
rejection, consent gate on prefs, invalid-value refusal, watchlist drift
alerts + no-repeat-noise, and the presentation-never-conclusions invariants.
Suite: **106 passed**.

## 5. Deferred (with reason)
- **D3 calibration** — requires analyst override labels; lands after the
  4-week pilot (TRUST.md §4) produces real ones.
- **Hyperscale cert** — production benchmarking phase.
- **CouchDB sovereignty sync** — infrastructure track; demo profile stays
  single-node by design (spec Part 10 zero-dependency contract).
