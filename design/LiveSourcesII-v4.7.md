# v4.7 — LIVE SOURCES II · spec-mapping doc

Position: v4.5 proved the governed live-source contract with one source
(crt.sh); v4.7 turns it into the connector-agnostic runner the §80 source
map implies, adds the second registry source (RDAP — *already named in the
platform's own §2 source families*: `identity_intel` and `intel` list
`rdap`), and closes the §67 source-change loop.

## 1. The generalization (why it matters for §80)

`live_sources.py` is now a source map + one governed runner
(`_run_observation`), not a crt.sh script. Every `_SOURCES` entry declares:
connector identity (name/url hint → registry lookup), provenance statement,
OSINT class (§64), reliability/authority stance, fetcher, summarizer,
evidence metadata builder, response view. Adding source N = one dict entry
+ tests; the gate order exists exactly once:

**§76 living-case (`authorize_run`) → §63 scope binding (subject subdomain
cone; IPs/URLs/wildcards rejected) → §80 ACTIVE on-allowlist connector →
classified wire (`_get`: TIMEOUT 503 / UNREACHABLE 503 / THROTTLED 429 /
BAD_RESPONSE 502) → §67/§68 persist.** The v4.5 response contract for
crt.sh is byte-stable through the rewrite (pinned by an explicit parity
test; all 25 v4.5 tests pass unmodified).

## 2. RDAP — the second source, and the honest-404 rule

`POST /api/v1/osint/live/rdap` (RBAC `investigate.run`; subject binding:
domain cases). Fetch: `rdap.org/domain/{domain}` — IANA bootstrap, keyless,
PASSIVE, §64 public-infrastructure-record (technical), PRIMARY/HIGH.

- Extraction is minimal and canonical: registrar (vcard `fn` of the entity
  whose roles include `registrar`), sorted status codes, sorted
  nameservers, normalized `action:date` events. The content hash commits
  to exactly this subset — **registry fluff (handle, ldhName casing) cannot
  flip the change detector** (test-pinned).
- **HTTP 404 is data, not an outage**: an unregistered domain yields a
  stored observation `{registered: false}` with plain-language raw_text
  ("NOT registered in the registry of record"). When the name later IS
  registered, the hash differs and the change detector fires — the classic
  lookalike-domain registration tripwire, built from the honest primitive.
- Parser drift (non-JSON, non-RDAP object) → SOURCE_BAD_RESPONSE,
  UNVERIFIED, never guessed (§1.9).

## 3. §67 source-change detection + §68 reproducibility

`persist_observation` (shared):
- content-hash idempotent (re-observing identical bytes links but never
  duplicates — unchanged from v4.5);
- **supersede-on-change**: new hash ⇒ new row with
  `metadata.supersedes = <previous evidence id>`, and
  `event:ObservationChanged` on the permanent trail; both rows stay in the
  case chain — supersession, never overwrite;
- every row records `parser_version` (live-sources/4.7.0) and
  `source_version` (RDAP `rdapConformance`; crt.sh upstream-of-record) —
  the §68 "tool/parser version" tuple beside query/params/timestamp;
- response carries `changed_from` so the UI can flag CHANGED immediately.

`ObservationChanged` is a platform extension beyond §26's fourteen —
documented here and in TRUST §16 (ReviewDecided/SourceHealthChanged
precedent). KPI context metrics (`intelligence_quality`):
`live_observations`, `observation_changes` — both measured, windowed.

## 4. Ops Node surface

Cases tab: OPEN domain cases gain **📡 Observe CT** and **🛰 Observe RDAP**
buttons. The result renders inline: provenance header, CHANGED chip when
the hash moved, per-source summary line, hash + evidence id + query URL.
Classified failures surface through the global ErrorPanel with their §20
what-to-do (e.g. CONNECTOR_NOT_ACTIVE carries the register→approve
playbook).

## 5. TRUST posture

Blast radius: **MEDIUM** (same envelope as v4.5, now general). New surface:
a second egress host; the change detector is additive (supersede chains);
hash-theft of cross-case identical content reuses rows deliberately
(content-addressed evidence — one content, one row, links per case).
Review level: **D2**, with the canonical-subset hashing and the 404-as-data
rule called out as the load-bearing decisions (line-reviewed + test-pinned).

## 6. Gates

`tests/test_v47_live_sources_ii.py` — 16 tests (fetch parsing, drift,
classified taxonomy, gate matrix, unregistered-as-data, idempotency,
supersede chains, unregistered→registered flip, crtsh regression parity,
canonical-hash stability, KPI context). **331/331 backend green**,
tsc clean, vite build green.
