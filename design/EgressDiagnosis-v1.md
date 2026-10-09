# Root-Cause Diagnosis v1 — Live-Source Egress Failures (Engine: Evidence → Hypotheses → Tests → Conclusions)

**Engine applied:** Root-Cause / Controlled-Fault-Isolation framework (pasted spec: 12 sections + coding/debugging module), executed with tools, one change → one observation, against the platform's #1 open evidence gap.
**Date:** 2026-10-08 · **Platform:** v4.8.0 · **Environment:** E2B sandbox (this session)

## 1. Problem model

- **GOAL:** are live-source failures (`crt.sh`, `rdap.org` → `SOURCE_UNREACHABLE`) an **application defect** or an **environmental constraint**? Identify the exact failing layer.
- **OBSERVED (pre-test):** `ConnectError('TLS/SSL connection has been closed (EOF)')` in classified fetch errors; sandbox doc lists an egress allowlist (`github.com`, npm/pypi registries only).
- **Layer model:** OS → network egress → DNS → TCP → TLS → HTTP client → application classification → data.

## 2. Hypothesis set (pre-registered)

| # | Hypothesis | Initial confidence | Discriminating test |
|---|---|---|---|
| H1 | Sandbox egress allowlist, SNI-keyed TLS kill; app healthy | Medium | SNI-switch on an allowlisted destination IP; unlisted control host |
| H2 | Target-side block of datacenter IPs (crt.sh/rdap) | Low | `example.com` control; independent egress (platform `fetch_page`) |
| H3 | Client/runtime defect (httpx/TLS) in our fetch path | Low | httpx → allowlisted host must succeed |
| H4 | DNS poisoning/failure for unlisted hosts | Low | getaddrinfo comparison |

## 3. Tests and observations (one variable at a time)

| Test | Result | Hypothesis update |
|---|---|---|
| T0 proxy env vars | none set | removes proxy-contamination as separate cause |
| T1 DNS `getaddrinfo` ×5 hosts | all resolve correctly (incl. unlisted) | **H4 eliminated** |
| T2 curl matrix | `github.com`/`pypi.org` → 200; **every** unlisted host (crt.sh, rdap.org, example.com, basemaps.cartocdn.com) → `SSL_connect: SSL_ERROR_SYSCALL` in ≤0.1 s | uniform kill ⇒ **H2 eliminated** (not target-specific); H1 strengthens |
| T2b independent corroboration (platform `fetch_page` → crt.sh) | crt.sh nginx answers (502 on that query — its own transient backend state; **TCP+TLS fine**) | target alive and serving the world; **H2 doubly eliminated**; 502 logged as incidental signal, not causal |
| T3 raw TCP connect ×3 | CONNECTED to all, listed and unlisted | L3 open; kill is at/after TLS ClientHello |
| **T4 SNI-switch (decisive)** | `github.com`-IP:443 with **SNI=crt.sh** → handshake killed (Cipher NONE) although destination IP is allowlisted; same IP with SNI=github.com proceeds | **H1 CONFIRMED**: filter keys on **SNI hostname**, not destination IP |
| T5 httpx → github.com | `CERTIFICATE_VERIFY_FAILED` (**surprise** — curl succeeded) | H3 eliminated for the crt.sh/rdap symptom (EOF precedes verification, every client identical); surfaces NEW line of inquiry: Python CA store |
| T5b httpx → example.com | EOF identical to curl/openssl | client-independent; **H3 eliminated** |
| T6 certificate issuer (openssl) | github.com leaf: **`O = E2B, CN = E2B Proxy CA`**, subject rewritten `CN = github.com` | **CONFIRMED (direct evidence)**: full TLS interception + re-signing by the sandbox for allowed SNIs |
| T7 httpx with system store | `verify=/etc/ssl/certs/ca-certificates.crt` → **200**; `SSL_CERT_FILE` unset | middlebox CA is in the system store (curl's path) but not in Python's bundled certifi — contributing factor pinned |

**Post-T4 reassessment (§7):** H1 promoted to CONFIRMED at the TLS layer; H2/H3/H4 eliminated with direct evidence. New hypothesis H5 ("Python certifi lacks the interception CA → Python fails even where SNI is allowed") generated from T5's surprise and confirmed by T6+T7.

## 4. Root cause vs symptoms (§8)

- **SYMPTOM:** `POST /osint/live/*` → 503 `SOURCE_UNREACHABLE` for crt.sh/rdap.
- **TRIGGER:** TLS handshake killed (EOF / `SSL_ERROR_SYSCALL`) immediately after ClientHello.
- **ROOT CAUSE — CONFIRMED:** **environment-layer**: the sandbox egress middlebox performs **SNI-keyed allowlisting with TLS interception** — unlisted SNIs are closed at handshake; listed SNIs are re-signed by `E2B Proxy CA`. No application code is involved in the failure.
- **CONTRIBUTING FACTOR — CONFIRMED:** Python's bundled certifi lacks the interception CA (`SSL_CERT_FILE` unset) → Python apps fail verification even to *allowed* hosts. Relevant beyond this sandbox: any pilot tenant with enterprise TLS-inspection egress hits the same class of issue.
- **INCIDENTAL SIGNALS (explicitly not causal):** crt.sh's transient 502 via external fetch; uvicorn restart warnings; the 422/409 classifications hit while setting up verification (all correct behavior).

## 5. What was ruled out, and why (§11-D)

- Application/client defect — every client (curl, openssl s_client, httpx) fails identically to unlisted SNIs; allowed hosts work with the right CA bundle.
- Target-side blocking — `example.com` (neutral, unlisted) fails identically; crt.sh demonstrably serves the wider internet.
- DNS — resolves correctly for all hosts.
- TCP filtering — connections complete at L3.
- IP-keyed filtering — SNI switch on an allowlisted IP fails when SNI is unlisted.

## 6. Verification before declaring success (§9)

- **EXPECTED:** the original failing operation still fails (environment unchanged) — but classified honestly, with the v4.8 DENY row visible on the case chronology.
- **ACTUAL (live, this session):** fresh case `252732bb-e56` (authority `organization_owned`, full §76 flow) → connector registered through the §26 approval chain (`conn-a47ad408-3` PENDING → approved → ACTIVE) → `POST /osint/live/rdap` → **HTTP 503 `SOURCE_UNREACHABLE`** with actionable next_step → chronology digest flips, DENY OBSERVATION row carries the case id. Setup friction hit additional honest gates (422 INVALID_CONSENT for a bad authority value; 409 CONNECTOR_NOT_ACTIVE pre-approval) — every layer did its job.
- **VERDICT: Confirmed.** The platform behaves exactly as designed under the constraint; the "failure" was never in the platform.

## 7. Remaining uncertainty (§10)

- **UNKNOWN:** whether crt.sh/rdap perform as sources in an unrestricted tenant network (never yet reachable from here) — first order of business in the E1 pilot.
- **POSSIBLE:** sandbox allowlist expands on request — outside our control; not assumed.
- **LIKELY:** enterprise MITM egress will be more common than not in target tenants (banks/SOCs) — hence the shipped fix below.

## 8. Exact action taken (§11-F) + verification (§11-G)

**F — shipped in this commit:**
1. `TH360_HTTP_CA_BUNDLE` support in `core/live_sources.py` (`_ca_bundle()`; env unset ⇒ behavior byte-identical).
2. Two regression tests (`TestWireDisciplineConfig`): env honored; default verify unchanged. **Suite 345 → 347, all green.**
3. `.env.example` documented hint; `PILOT.md` boundary row updated with egress reality.

**G — verification:** T7 proved the diagnosis (system-bundle verify → 200 to an allowed, intercepted host); the new tests prove the fix honors the path and defaults; the §6 run proves app-layer correctness end-to-end.

## 9. Consequences for the roadmap

- **E1 pilot rule #1: run where the sandbox isn't.** Pick the tenant network first; verify SNI egress to the pilot's connector list on day 0; ship the tenant CA bundle path if inspection is present.
- Mobile tiles (`basemaps.cartocdn.com`) are in the same blocked class from sandboxes — affects only sandbox demos, not devices (devices use their own network).
- Platform posture validated: honest classification turned an environmental wall into actionable operator guidance instead of a fabricated result. The engine's verdict: **no platform fix is warranted for the root cause; one configuration capability was warranted for the contributing factor, and it shipped.**
