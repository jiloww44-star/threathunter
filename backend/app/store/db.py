"""Evidence correlation & store — spec Part 4 + §1 (graph store layer).

Production profile: PostgreSQL + pgvector (Part 4 schema) and Neo4j for the
evidence graph (Part 12.1). Demo profile: SQLite implementing the *same
repository contract* — same tables, same semantics, vector search via stored
embeddings + cosine (the pgvector HNSW query is the production equivalent).

Every row keeps provenance per §16-17: source, timestamps, reliability,
authority, independence group.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from ..config import settings
from ..core import nlp_lite
from ..scraper.models import RawEvidence, Reliability, Signal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    url TEXT,
    fetched_at TEXT,
    published_at TEXT,
    reliability TEXT,
    reliability_score REAL,
    authority TEXT,              -- PRIMARY | SECONDARY
    independence_group TEXT,
    content_hash TEXT,
    title TEXT,
    excerpt TEXT,
    raw_ref TEXT,                -- pointer to encrypted blob store (§25)
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    evidence_id TEXT REFERENCES evidence(id),
    entity TEXT,
    event_type TEXT,
    location TEXT,
    event_time TEXT,
    claim_text TEXT,
    claim_embedding TEXT,        -- JSON vector; pgvector VECTOR(n) in prod
    supports_claim INTEGER,      -- 1/0/NULL
    reliability_score REAL,
    extracted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_entity ON signals(entity);

CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    case_id TEXT,
    statement TEXT,
    supporting INTEGER DEFAULT 0,
    contradicting INTEGER DEFAULT 0,
    score REAL DEFAULT 0,
    confidence TEXT,
    status TEXT DEFAULT 'ACTIVE',   -- ACTIVE | SUPERSEDED (§1.10)
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS checks (
    id TEXT PRIMARY KEY,
    module TEXT,                    -- factcheck | journey | kyc
    subject TEXT,
    outcome TEXT,
    confidence TEXT,
    response_json TEXT,
    model_versions TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS sources_meta (
    source_id TEXT PRIMARY KEY,
    reliability TEXT,
    authority TEXT,
    independence_group TEXT,
    last_success_at TEXT,
    last_error TEXT,
    freshness_lag_min REAL DEFAULT 0,
    health_score REAL,                        -- §Willison U1 auto scorecard
    health_note TEXT,
    health_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (   -- §27 human-in-the-loop queue
    id TEXT PRIMARY KEY,
    module TEXT,
    case_ref TEXT,
    reason TEXT,
    risk TEXT,
    priority INTEGER DEFAULT 0,
    tier TEXT,                              -- Part 18 D1 routing lane
    status TEXT DEFAULT 'OPEN',
    created_at TEXT,
    sla_deadline TEXT
);

CREATE TABLE IF NOT EXISTS budget_tx (      -- LLM/Firecrawl spend ledger
    id TEXT PRIMARY KEY,
    purpose TEXT,
    model_id TEXT,
    est_nano INTEGER DEFAULT 0,
    actual_nano INTEGER,
    mode TEXT,
    case_id TEXT,                             -- §2.1 case-attributed audit
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_budget_tx_purpose ON budget_tx(purpose, created_at);
"""

# v3.0 SOVEREIGN FUSION schema (spec §2 architecture / §8 P1-P3) — PATHFINDER
# task trees, Trust Layer notifications (§1.10), AUDITOR trail (A-06),
# custom-agent SDK registry (§5.2), VOYAGER journey watches (§5.1).
_V3_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_trees (              -- TaskTreeJSON (A-02)
    tree_id TEXT PRIMARY KEY,
    goal TEXT,
    status TEXT,          -- RUNNING | COMPLETE | DEGRADED | FAILED | AWAITING_HUMAN
    dispatch_plan TEXT,   -- JSON DispatchPlan
    report_json TEXT,     -- UnifiedReport (canonical spine, spec §6)
    peer_id TEXT,         -- orchestrator peer owning execution (§3.3)
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS ops_tasks (
    task_id TEXT PRIMARY KEY,
    tree_id TEXT REFERENCES ops_trees(tree_id),
    parent_id TEXT,                                 -- RGD decomposition edge
    agent TEXT,           -- SENTINEL | HUNTER | AUDITOR | VOYAGER | custom
    function TEXT,        -- MUST be inside the agent allowlist (A-14)
    title TEXT,
    status TEXT,          -- PENDING | RUNNING | COMPLETE | DEGRADED |
                          -- FAILED | BLOCKED | AWAITING_HUMAN
    classified_error TEXT,                          -- §20 error class
    result_json TEXT,
    started_at TEXT,
    ended_at TEXT,
    position INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_tree ON ops_tasks(tree_id);

CREATE TABLE IF NOT EXISTS notifications (   -- §1.10 verdict-change alerts
    id TEXT PRIMARY KEY,
    kind TEXT,            -- VERDICT_CHANGE | RISK_ELEVATION | RISK_RESOLUTION | GOVERNANCE
    title TEXT,
    body TEXT,
    ref TEXT,             -- check_id | watch_id | tree_id
    created_at TEXT,
    acknowledged INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_trail (          -- A-06 AUDITOR ledger
    id TEXT PRIMARY KEY,
    actor TEXT,           -- agent or user making the request
    action TEXT,          -- governed action attempted
    decision TEXT,        -- ALLOW | DENY | REQUIRE_HUMAN
    detail TEXT,
    policy_version TEXT,  -- sovereign policy version (§5.2)
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS custom_agents (        -- A-13 / §5.2 SDK registry
    agent_id TEXT PRIMARY KEY,
    name TEXT,
    functions_json TEXT,  -- declared api_functions allowlist (A-14)
    status TEXT,          -- SHADOW | ACTIVE | REJECTED
    shadow_tree_count INTEGER DEFAULT 0,
    drift_notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS journey_watches (   -- VOYAGER monitor_active_journey
    watch_id TEXT PRIMARY KEY,
    origin TEXT,
    destination TEXT,
    departure_time TEXT,
    priority TEXT DEFAULT 'balanced',
    baseline_risk TEXT,
    current_risk TEXT,
    status TEXT DEFAULT 'MONITORING',  -- MONITORING | ELEVATED | CLOSED
    tolerance TEXT DEFAULT 'MODERATE', -- §3.4 notification threshold (presentation only)
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_preferences (   -- §3.4 personalization layer
    user_id TEXT PRIMARY KEY,
    watchlists_json TEXT DEFAULT '[]',   -- saved entity watchlists (v1 §22)
    journey_priority TEXT DEFAULT 'balanced',     -- presentation default only
    notify_tolerance TEXT DEFAULT 'MODERATE',     -- alert threshold default
    output_format TEXT DEFAULT 'novice',          -- novice | analyst (§19)
    region TEXT DEFAULT 'GLOBAL',                 -- v3.4 consent defaults scope
    watchlist_state_json TEXT DEFAULT '{}',       -- entity -> signal count seen
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS consent_ledger (     -- §5.3 immutable consent log
    id TEXT PRIMARY KEY,
    user_id TEXT,
    purpose TEXT,           -- kyc_biometrics | personalization | journey_history | analytics
    state TEXT,             -- granted | withdrawn
    detail TEXT,
    prev_hash TEXT,         -- hash chain: tamper-evidence (immutable, auditable)
    entry_hash TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_consent_user ON consent_ledger(user_id, purpose);

-- v3.2 Safety-by-design (UX review blockers E/G)
CREATE TABLE IF NOT EXISTS investigations (      -- v4.0 §2 primary object
    id TEXT PRIMARY KEY,
    objective TEXT,
    subject_type TEXT,                    -- person|organization|domain|ip|url|location|claim|agent
    subject TEXT,
    purpose TEXT,                         -- §63 why this investigation exists
    authority TEXT,                       -- organization_owned|client_authorized|public_research|unchecked
    scope TEXT,                           -- bounded scope statement (§63)
    allowed_sources_json TEXT DEFAULT '[]',  -- connector allowlist; [] = open public tier
    expires_at TEXT,                      -- authorization expiry (§63) — hard gate
    status TEXT DEFAULT 'OPEN',           -- OPEN | CLOSED
    user_id TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS investigation_links ( -- §5 evidence chain linkage
    id TEXT PRIMARY KEY,
    investigation_id TEXT,
    kind TEXT,       -- ops_tree | evidence | watch | finding | verification_case
    ref_id TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (          -- v4.2 §26 approval engine
    id TEXT PRIMARY KEY,
    kind TEXT,         -- e.g. promote_custom_agent, patch_apply
    subject_ref TEXT,  -- what the approval governs (agent id, cve id, ...)
    summary TEXT,
    requester TEXT,
    status TEXT DEFAULT 'PENDING',   -- PENDING | APPROVED | REJECTED
    decided_by TEXT,
    decided_at TEXT,
    context_json TEXT DEFAULT '{}',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS assurance_runs (     -- v4.3 continuous assurance
    id TEXT PRIMARY KEY,
    actor TEXT,
    posture TEXT,        -- OK | ATTENTION | CRITICAL
    summary_json TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS connectors (         -- v4.4 custom connectors (§80)
    id TEXT PRIMARY KEY,
    name TEXT,
    kind TEXT,           -- A_methodology | B_discovery | C_data_api | D_research_distribution
    base_url TEXT,
    auth_env TEXT,       -- env var NAME holding the key (never the secret)
    status TEXT DEFAULT 'PENDING_APPROVAL',  -- PENDING_APPROVAL | ACTIVE | RETIRED
    registered_by TEXT,
    approval_id TEXT,
    created_at TEXT,
    retired_at TEXT
);

CREATE TABLE IF NOT EXISTS declared_incidents (  -- functional crisis pathway
    incident_id TEXT PRIMARY KEY,
    severity TEXT,          -- SEV1 | SEV2 | SEV3
    summary TEXT,
    declared_by TEXT,
    status TEXT DEFAULT 'ACTIVE',   -- ACTIVE | RESOLVED
    delivery_json TEXT,     -- webhook delivery outcome (honest §20)
    created_at TEXT,
    resolved_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceStore:
    """Thread-safe SQLite repository (async-compatible via short ops)."""

    def __init__(self, path: str | None = None):
        self.path = path or settings.DATABASE_PATH
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.executescript(_V3_SCHEMA)   # v3.0 SOVEREIGN FUSION
            self._migrate()
            self._conn.commit()

    def _migrate(self):
        """Additive migrations (idempotent) for live demo databases."""
        cols = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(budget_tx)")}
        if "case_id" not in cols:
            # §2.1 — case-attributed spend audit (e2e demo Stage 4)
            self._conn.execute(
                "ALTER TABLE budget_tx ADD COLUMN case_id TEXT")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_budget_tx_case "
                "ON budget_tx(case_id)")
        rq = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(review_queue)")}
        if "tier" not in rq:
            # Part 18 D1 — tiered review routing (TRUST.md §Tiered review)
            self._conn.execute(
                "ALTER TABLE review_queue ADD COLUMN tier TEXT")
        sm = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(sources_meta)")}
        if "health_score" not in sm:
            # §Willison U1 — automated source health scoring
            self._conn.execute(
                "ALTER TABLE sources_meta ADD COLUMN health_score REAL")
            self._conn.execute(
                "ALTER TABLE sources_meta ADD COLUMN health_note TEXT")
            self._conn.execute(
                "ALTER TABLE sources_meta ADD COLUMN health_checked_at TEXT")
        ot = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(ops_trees)")}
        if "halt_requested" not in ot:
            # v3.2 blocker E — user-controlled halt flag on running trees
            self._conn.execute(
                "ALTER TABLE ops_trees ADD COLUMN halt_requested "
                "INTEGER DEFAULT 0")
        jw = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(journey_watches)")}
        if "user_id" not in jw:
            # v3.2 — watches are personal data (deletable per user)
            self._conn.execute(
                "ALTER TABLE journey_watches ADD COLUMN user_id TEXT")
        up = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(user_preferences)")}
        if "region" not in up:
            # v3.4 — region-aware consent defaults (red-team review #9)
            self._conn.execute(
                "ALTER TABLE user_preferences ADD COLUMN region "
                "TEXT DEFAULT 'GLOBAL'")
        # ---------------- v4.6 measurement closure (§71 write-paths) --------
        rq = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(review_queue)")}
        if "decision" not in rq:
            # §27 review queue was read-only until v4.6 — humans could not
            # record CONFIRMED/CORRECTED, so analyst-correction KPIs were
            # honestly UNAVAILABLE. These columns ARE the correction ledger.
            self._conn.execute(
                "ALTER TABLE review_queue ADD COLUMN decision TEXT")
            self._conn.execute(
                "ALTER TABLE review_queue ADD COLUMN decided_by TEXT")
            self._conn.execute(
                "ALTER TABLE review_queue ADD COLUMN decided_at TEXT")
            self._conn.execute(
                "ALTER TABLE review_queue ADD COLUMN prior_outcome TEXT")
            self._conn.execute(
                "ALTER TABLE review_queue ADD COLUMN corrected_outcome TEXT")
        ck = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(checks)")}
        if "latency_ms" not in ck:
            # §71 fact-checker latency — measured pipeline wall-clock, ms.
            self._conn.execute(
                "ALTER TABLE checks ADD COLUMN latency_ms REAL")
        jw2 = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(journey_watches)")}
        if "reroute_pending" not in jw2:
            # reroute recommendation lifecycle: ELEVATION beyond tolerance
            # mints a pending recommendation; the operator ACCEPTs or
            # DECLINEs it — that ratio is §71 reroute acceptance.
            self._conn.execute(
                "ALTER TABLE journey_watches ADD COLUMN reroute_pending "
                "INTEGER DEFAULT 0")
            self._conn.execute(
                "ALTER TABLE journey_watches ADD COLUMN reroute_outcome TEXT")
            self._conn.execute(
                "ALTER TABLE journey_watches ADD COLUMN reroute_decided_at "
                "TEXT")
        nt = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(notifications)")}
        if "adjudication" not in nt:
            # §71 false-alarm rate needs alert outcomes: TRUE_POSITIVE or
            # FALSE_POSITIVE, adjudicated once, auditably.
            self._conn.execute(
                "ALTER TABLE notifications ADD COLUMN adjudication TEXT")
            self._conn.execute(
                "ALTER TABLE notifications ADD COLUMN adjudicated_by TEXT")
            self._conn.execute(
                "ALTER TABLE notifications ADD COLUMN adjudicated_at TEXT")

    def close(self):
        global _store
        with self._lock:
            self._conn.close()
        if _store is self:
            _store = None

    # ------------------------------------------------------------ writes --
    def upsert_source_meta(self, src: dict, ok: bool, error: str | None = None,
                           at: str | None = None):
        with self._lock:
            self._conn.execute(
                """INSERT INTO sources_meta(source_id, reliability, authority,
                            independence_group, last_success_at, last_error)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET
                     reliability=excluded.reliability,
                     authority=excluded.authority,
                     independence_group=excluded.independence_group,
                     last_success_at=COALESCE(excluded.last_success_at,
                                              sources_meta.last_success_at),
                     last_error=excluded.last_error""",
                (
                    src["id"], src.get("reliability", "UNKNOWN"),
                    src.get("authority", "SECONDARY"),
                    src.get("independence_group", src["id"]),
                    (at or _now()) if ok else None, error,
                ),
            )
            self._conn.commit()

    def source_meta(self, source_id: str) -> dict | None:
        """Last-known-good fetch state for one source — drives §2.4/§20
        staleness banners ('last successful fetch Xh ago')."""
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM sources_meta WHERE source_id=?",
                (source_id,)).fetchone()
        return dict(r) if r else None

    def all_source_meta(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sources_meta").fetchall()
        return [dict(r) for r in rows]

    def update_source_health(self, source_id: str, health: float,
                             note: str, authority: str | None = None):
        """§Willison U1 — persist the auto scorecard (and any auto authority
        change); the note is the audit trail, always human-readable."""
        with self._lock:
            if authority is not None:
                self._conn.execute(
                    """UPDATE sources_meta SET health_score=?, health_note=?,
                           health_checked_at=?, authority=?
                       WHERE source_id=?""",
                    (health, note, _now(), authority, source_id))
            else:
                self._conn.execute(
                    """UPDATE sources_meta SET health_score=?, health_note=?,
                           health_checked_at=? WHERE source_id=?""",
                    (health, note, _now(), source_id))
            self._conn.commit()

    def existing_content_hashes(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT content_hash FROM evidence").fetchall()
        return {r[0] for r in rows if r[0]}

    def insert_evidence(self, raw: RawEvidence, signals: list[Signal]) -> int:
        """Store fetched content + its signals. Idempotent by content hash.

        Two granularities:
          * ARTICLE mode — structured payloads (spec Part 10): every article/
            entry/feature becomes ONE evidence row + ONE signal (provenance
            per item, §16-17).
          * PAGE mode — a single fetched page/document → one row.
        """
        if signals and all(s.evidence_id for s in signals):
            return self._insert_articles(raw, signals)

        with self._lock:
            exists = self._conn.execute(
                "SELECT id FROM evidence WHERE content_hash=? AND source_id=?",
                (raw.content_hash, raw.source_id),
            ).fetchone()
            if exists:
                return 0
            ev_id = str(uuid.uuid4())
            title = raw.raw_text[:80].split("\n")[0]
            self._conn.execute(
                """INSERT INTO evidence(id, source_id, url, fetched_at,
                    published_at, reliability, reliability_score, authority,
                    independence_group, content_hash, title, excerpt,
                    raw_ref, metadata_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ev_id, raw.source_id, raw.url, raw.fetched_at,
                    raw.metadata.get("published_at"),
                    raw.metadata.get("reliability", "UNKNOWN"),
                    Reliability.__members__.get(
                        raw.metadata.get("reliability", "UNKNOWN"),
                        Reliability.UNKNOWN).value,
                    raw.metadata.get("authority", "SECONDARY"),
                    raw.metadata.get("independence_group", raw.source_id),
                    raw.content_hash, title, raw.raw_text[:300],
                    f"vault://enc/{raw.content_hash[:16]}",
                    json.dumps(raw.metadata),
                ),
            )
            inserted = 0
            for sig in signals:
                self._insert_signal_row(ev_id, sig)
                inserted += 1
            self._conn.commit()
        return inserted

    def _insert_articles(self, raw: RawEvidence, signals: list[Signal]) -> int:
        inserted = 0
        with self._lock:
            for sig in signals:
                # deterministic idempotency: source + article id
                chash = hashlib.sha256(
                    f"{raw.source_id}|{sig.evidence_id}".encode()
                ).hexdigest()
                exists = self._conn.execute(
                    "SELECT id FROM evidence WHERE content_hash=?",
                    (chash,)).fetchone()
                if exists:
                    continue
                ev_id = str(uuid.uuid4())
                meta = dict(sig.metadata or {})
                title = (meta.get("headline") or sig.claim_text[:80]).strip()
                self._conn.execute(
                    """INSERT INTO evidence(id, source_id, url, fetched_at,
                        published_at, reliability, reliability_score, authority,
                        independence_group, content_hash, title, excerpt,
                        raw_ref, metadata_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ev_id, raw.source_id, meta.get("url") or raw.url,
                        raw.fetched_at,
                        meta.get("published_at") or sig.time,
                        raw.metadata.get("reliability", "UNKNOWN"),
                        sig.confidence_input,
                        raw.metadata.get("authority", "SECONDARY"),
                        raw.metadata.get("independence_group", raw.source_id),
                        chash, title, sig.claim_text[:400],
                        f"vault://enc/{chash[:16]}",
                        json.dumps({**raw.metadata, "article_id": sig.evidence_id,
                                    "designed_to_test": sig.designed_to_test,
                                    "severity": meta.get("severity"),
                                    "segment": meta.get("segment"),
                                    "time_of_day": meta.get("time_of_day")}),
                    ),
                )
                self._insert_signal_row(ev_id, sig)
                inserted += 1
            self._conn.commit()
        return inserted

    def _insert_signal_row(self, ev_id: str, sig: Signal):
        emb = nlp_lite.embed(sig.claim_text)
        self._conn.execute(
            """INSERT INTO signals(id, evidence_id, entity, event_type,
                location, event_time, claim_text, claim_embedding,
                supports_claim, reliability_score, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), ev_id, sig.entity, sig.event_type,
                sig.location, sig.time, sig.claim_text,
                json.dumps(emb),
                None if sig.supports_claim is None
                else int(bool(sig.supports_claim)),
                sig.confidence_input, _now(),
            ),
        )

    def insert_hypothesis(self, case_id: str, statement: str, supporting: int,
                          contradicting: int, score: float, confidence: str,
                          status: str = "ACTIVE"):
        with self._lock:
            self._conn.execute(
                """INSERT INTO hypotheses(id, case_id, statement, supporting,
                    contradicting, score, confidence, status, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), case_id, statement, supporting,
                 contradicting, score, confidence, status, _now()),
            )
            self._conn.commit()

    def record_check(self, module: str, subject: str, outcome: str,
                     confidence: str, response: dict, check_id: str | None = None,
                     latency_ms: float | None = None) -> str:
        cid = check_id or str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """INSERT INTO checks(id, module, subject, outcome, confidence,
                    response_json, model_versions, created_at, latency_ms)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (cid, module, subject, outcome, confidence,
                 json.dumps(response), json.dumps(settings.MODEL_VERSIONS),
                 _now(), latency_ms),
            )
            self._conn.commit()
        return cid

    def enqueue_review(self, module: str, case_ref: str, reason: str,
                       risk: str = "MODERATE", priority: int = 25,
                       tier: str | None = None) -> str:
        rid = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """INSERT INTO review_queue(id, module, case_ref, reason, risk,
                    priority, tier, created_at, sla_deadline)
                   VALUES (?,?,?,?,?,?,?,?, datetime('now', '+4 hours'))""",
                (rid, module, case_ref, reason, risk, priority, tier, _now()),
            )
            self._conn.commit()
        return rid

    # ------------------------------------------------------------- reads --
    def all_evidence(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM evidence").fetchall()
        return [dict(r) for r in rows]

    def get_evidence(self, evidence_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        return dict(r) if r else None

    def all_signals(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT s.*, e.source_id, e.independence_group, e.reliability,
                          e.authority, e.url, e.fetched_at, e.published_at,
                          e.excerpt
                   FROM signals s JOIN evidence e ON e.id = s.evidence_id"""
            ).fetchall()
        return [dict(r) for r in rows]

    def search_signals(self, claim: str, limit: int = 50,
                       elements: dict | None = None) -> list[dict]:
        """Semantic source discovery over the evidence store (pgvector cosine
        in prod; here: cosine over stored embeddings + entity/date boosts).

        Retrieval stays entity-anchored for §1.9 honesty: claim-side office
        titles resolve to their institutions via same_entity title aliasing
        ("the Governor" co-refers to "... Government"), so claims like the
        airport announcement match records filed under the government entity
        without opening the pool to every document mentioning a city."""
        rows = self.all_signals()
        if not rows:
            return []
        vec = nlp_lite.embed(claim)
        elements = elements or nlp_lite.extract_claim_elements(claim)
        ents = [e.lower() for e in elements.get("entities", [])
                + elements.get("orgs", [])]
        return self._score(rows, vec, ents, elements, limit)

    def _score(self, rows: list[dict], vec, ents: list[str],
               elements: dict, limit: int,
               tag: str | None = None) -> list[dict]:
        ev_type = elements.get("event_type")
        dates = elements.get("dates", [])

        scored = []
        for r in rows:
            stored = json.loads(r["claim_embedding"]) if r.get("claim_embedding") else None
            base = nlp_lite.cosine(vec, stored) if stored else 0.0
            score = base
            entity_hit = any(
                r.get("entity") and (e in r["entity"].lower() or r["entity"].lower() in e)
                for e in ents
            ) or any(nlp_lite.same_entity(e, r.get("entity"),
                                          allow_title_alias=True)
                     for e in ents)
            if entity_hit:
                score += 0.35
            if ev_type and r.get("event_type") and ev_type == r["event_type"]:
                score += 0.20
            if dates and r.get("event_time"):
                ev_month = str(r["event_time"])[:7]
                if any(str(d)[:7] == ev_month for d in dates):
                    score += 0.10
            entity_applicable = (not ents) or entity_hit
            scored.append((score, entity_hit, entity_applicable, r))

        scored.sort(key=lambda t: t[0], reverse=True)
        # Entity claims: require entity match OR very high semantic similarity.
        out = []
        for score, entity_hit, applicable, r in scored[:limit]:
            if not applicable and score < 0.62:
                continue
            if score < 0.12:
                continue
            r = dict(r)
            r["relevance"] = score
            r["entity_matched"] = entity_hit
            if tag:
                r["retrieval"] = tag
            out.append(r)
        return out

    def recent_checks(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM checks ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_check(self, check_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
        return dict(r) if r else None

    def get_hypotheses(self, case_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM hypotheses WHERE case_id=? ORDER BY score DESC",
                (case_id,)).fetchall()
        return [dict(r) for r in rows]

    def review_queue(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM review_queue WHERE status='OPEN' "
                "ORDER BY priority DESC, created_at ASC").fetchall()
        return [dict(r) for r in rows]

    def statistics(self) -> dict:
        with self._lock:
            c = self._conn.cursor()
            total = c.execute("SELECT COUNT(*) FROM checks").fetchone()[0]
            verdict_rows = c.execute(
                "SELECT outcome, COUNT(*) FROM checks GROUP BY outcome").fetchall()
            conf_map = {"VERY_HIGH": .95, "HIGH": .8, "MODERATE": .6, "LOW": .4,
                        "VERY_LOW": .2, "UNDETERMINED": .1}
            confs = [r[0] for r in c.execute(
                "SELECT DISTINCT confidence FROM checks").fetchall()]
            avg_conf = (sum(conf_map.get(k, .1) for k in confs) / len(confs)
                        if confs else 0.0)
            ev_total = c.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            sig_total = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            src_total = c.execute("SELECT COUNT(*) FROM sources_meta").fetchone()[0]
            q_depth = c.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status='OPEN'").fetchone()[0]
        # Part 4.4 — copy-chain ratio: near-identical items inside the same
        # independence group ÷ total items (rising = echo/disinfo pattern)
        from ..scraper.dedupe import hamming, simhash64
        evidence = self.all_evidence()
        by_group: dict[str, list[dict]] = {}
        for ev in evidence:
            by_group.setdefault(ev["independence_group"], []).append(ev)
        total_refs = len(evidence)
        dup_refs = 0
        for g in by_group.values():
            if len(g) < 2:
                continue
            hashes = [simhash64(e.get("excerpt") or "") for e in g]
            seen: list[int] = []
            for h in hashes:
                if any(hamming(h, s) <= 12 for s in seen):
                    dup_refs += 1
                else:
                    seen.append(h)
        copy_ratio = (dup_refs / total_refs) if total_refs else 0.0
        return {
            "total_checks": total,
            "verdict_mix": {k: n for k, n in verdict_rows},
            "avg_confidence_score": round(avg_conf, 3),
            "sources_active": src_total,
            "evidence_items": ev_total,
            "signals_indexed": sig_total,
            "copy_chain_ratio": round(copy_ratio, 3),
            "review_queue_depth": q_depth,
            "model_versions": settings.MODEL_VERSIONS,
        }

    # ----------------------------------------------------- budget ledger --
    def insert_budget_tx(self, tx: dict):
        with self._lock:
            self._conn.execute(
                """INSERT INTO budget_tx(id, purpose, model_id, est_nano,
                    actual_nano, mode, case_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (tx["id"], tx.get("purpose"), tx.get("model_id"),
                 tx.get("est_nano", 0), tx.get("actual_nano"),
                 tx.get("mode", "STANDARD"), tx.get("case_id"),
                 tx.get("created_at") or _now()),
            )
            self._conn.commit()

    def budget_tx_rows(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM budget_tx").fetchall()
        return [dict(r) for r in rows]

    def budget_tx_for_case(self, case_id: str) -> list[dict]:
        """§2.1 Stage 4 — full spend trail attributed to one case, in
        reserve order, with usd computed like the ledger (actual wins;
        unsettled rows count at their estimate)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM budget_tx WHERE case_id=? "
                "ORDER BY created_at, rowid", (case_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            nano = d["actual_nano"] if d.get("actual_nano") is not None \
                else (d.get("est_nano") or 0)
            d["usd"] = round((nano or 0) / 1e9, 6)
            out.append(d)
        return out

    # ---------------------------------------------------------- analytics --
    def analytics_daily(self, days: int = 30) -> list[dict]:
        """§4.1 analytics_daily view — one row per day: volume, verdict mix,
        confidence, source independence and spend (SQLite equivalent of the
        Postgres view in the spec)."""
        conf_map = {"VERY_HIGH": .95, "HIGH": .8, "MODERATE": .6, "LOW": .4,
                    "VERY_LOW": .2, "UNDETERMINED": .1}
        with self._lock:
            checks = self._conn.execute(
                """SELECT * FROM checks
                   WHERE created_at >= date('now', ? || ' days')
                   ORDER BY created_at""", (f"-{days}",)).fetchall()
            spend = self._conn.execute(
                """SELECT * FROM budget_tx
                   WHERE created_at >= date('now', ? || ' days')""",
                (f"-{days}",)).fetchall()
        by_day: dict[str, dict] = {}
        for c in checks:
            day = str(c["created_at"])[:10]
            entry = by_day.setdefault(day, {
                "day": day, "checks_total": 0, "verified": 0, "unverified": 0,
                "false_or_misleading": 0, "kyc_cases": 0, "journeys": 0,
                "conf_sum": 0.0, "diversity_sum": 0.0, "diversity_n": 0,
            })
            entry["checks_total"] += 1
            oc = c["outcome"]
            if oc == "VERIFIED":
                entry["verified"] += 1
            elif oc == "UNVERIFIED":
                entry["unverified"] += 1
            elif oc in ("FALSE", "MISLEADING"):
                entry["false_or_misleading"] += 1
            if c["module"] == "kyc":
                entry["kyc_cases"] += 1
            if c["module"] == "journey":
                entry["journeys"] += 1
            entry["conf_sum"] += conf_map.get(c["confidence"], 0.1)
            if c["module"] == "factcheck":
                try:
                    resp = json.loads(c["response_json"])
                    tot = resp.get("sources_total") or 0
                    ind = resp.get("sources_independent") or 0
                    if tot:
                        entry["diversity_sum"] += ind / tot
                        entry["diversity_n"] += 1
                except Exception:
                    pass
        spend_by_day: dict[str, float] = {}
        calls_by_day: dict[str, int] = {}
        for tx in spend:
            day = str(tx["created_at"])[:10]
            amt = int(tx["actual_nano"] if tx["actual_nano"] is not None
                      else tx["est_nano"] or 0) / 1e9
            spend_by_day[day] = spend_by_day.get(day, 0.0) + amt
            calls_by_day[day] = calls_by_day.get(day, 0) + 1
        out = []
        for day, entry in sorted(by_day.items()):
            entry["avg_confidence"] = round(
                entry.pop("conf_sum") / max(entry["checks_total"], 1), 3)
            dsum, dn = entry.pop("diversity_sum"), entry.pop("diversity_n") or 1
            entry["avg_source_diversity"] = round(dsum / dn, 3)
            entry["llm_cost_usd"] = round(spend_by_day.get(day, 0.0), 6)
            entry["llm_calls"] = calls_by_day.get(day, 0)
            entry["outlier"] = bool(
                entry["llm_cost_usd"] > 0.5 and entry["checks_total"] <= 2)
            out.append(entry)
        return out

    # ====================================== v3.0 SOVEREIGN FUSION stores ==

    # ------------------------------------------------ PATHFINDER trees ----
    def create_tree(self, tree_id: str, goal: str, dispatch_plan: dict,
                    peer_id: str):
        with self._lock:
            self._conn.execute(
                """INSERT INTO ops_trees(tree_id, goal, status, dispatch_plan,
                       peer_id, created_at, updated_at)
                   VALUES (?,?, 'RUNNING', ?,?,?,?)""",
                (tree_id, goal, json.dumps(dispatch_plan), peer_id,
                 _now(), _now()))
            self._conn.commit()

    def update_tree(self, tree_id: str, status: str | None = None,
                    report: dict | None = None, peer_id: str | None = None):
        with self._lock:
            if status is not None:
                self._conn.execute(
                    "UPDATE ops_trees SET status=?, updated_at=? WHERE tree_id=?",
                    (status, _now(), tree_id))
            if report is not None:
                self._conn.execute(
                    "UPDATE ops_trees SET report_json=?, updated_at=? "
                    "WHERE tree_id=?",
                    (json.dumps(report), _now(), tree_id))
            if peer_id is not None:
                self._conn.execute(
                    "UPDATE ops_trees SET peer_id=?, updated_at=? "
                    "WHERE tree_id=?", (peer_id, _now(), tree_id))
            self._conn.commit()

    def get_tree(self, tree_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM ops_trees WHERE tree_id=?",
                (tree_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["dispatch_plan"] = json.loads(d.get("dispatch_plan") or "{}")
        d["report"] = json.loads(d.get("report_json") or "null")
        d.pop("report_json", None)
        d["tasks"] = self.tasks_for_tree(tree_id)
        return d

    def list_trees(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tree_id, goal, status, peer_id, created_at, updated_at "
                "FROM ops_trees ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------ PATHFINDER tasks ----
    def upsert_task(self, task: dict):
        with self._lock:
            self._conn.execute(
                """INSERT INTO ops_tasks(task_id, tree_id, parent_id, agent,
                       function, title, status, classified_error, result_json,
                       started_at, ended_at, position)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                     status=excluded.status,
                     classified_error=excluded.classified_error,
                     result_json=excluded.result_json,
                     started_at=excluded.started_at,
                     ended_at=excluded.ended_at""",
                (task["task_id"], task["tree_id"], task.get("parent_id"),
                 task["agent"], task["function"], task.get("title", ""),
                 task.get("status", "PENDING"), task.get("classified_error"),
                 json.dumps(task.get("result") or {}),
                 task.get("started_at"), task.get("ended_at"),
                 task.get("position", 0)))
            self._conn.commit()

    def tasks_for_tree(self, tree_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM ops_tasks WHERE tree_id=? ORDER BY position",
                (tree_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["result"] = json.loads(d.get("result_json") or "{}")
            d.pop("result_json", None)
            out.append(d)
        return out

    def all_tasks(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM ops_tasks ORDER BY started_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------------- v3.2 blocker E — user control / exit ramps ----------
    def request_halt(self, tree_id: str):
        with self._lock:
            self._conn.execute(
                "UPDATE ops_trees SET halt_requested=1, updated_at=? "
                "WHERE tree_id=?", (_now(), tree_id))
            self._conn.commit()

    def is_halted(self, tree_id: str) -> bool:
        with self._lock:
            r = self._conn.execute(
                "SELECT halt_requested FROM ops_trees WHERE tree_id=?",
                (tree_id,)).fetchone()
        return bool(r and r[0])

    def delete_tree(self, tree_id: str):
        """Exit ramp: permanently remove a tree + its tasks + report."""
        with self._lock:
            t = self._conn.execute(
                "DELETE FROM ops_tasks WHERE tree_id=?", (tree_id,))
            g = self._conn.execute(
                "DELETE FROM ops_trees WHERE tree_id=?", (tree_id,))
            self._conn.commit()
        return {"tasks_deleted": t.rowcount, "tree_deleted": g.rowcount}

    # ---------------- v3.2 blocker G — functional crisis pathway ----------
    def declare_incident(self, incident_id: str, severity: str,
                         summary: str, declared_by: str, delivery: dict):
        with self._lock:
            self._conn.execute(
                """INSERT INTO declared_incidents(incident_id, severity,
                       summary, declared_by, delivery_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (incident_id, severity, summary, declared_by,
                 json.dumps(delivery), _now()))
            self._conn.commit()

    def list_incidents(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM declared_incidents "
                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["delivery"] = json.loads(d.get("delivery_json") or "{}")
            d.pop("delivery_json", None)
            out.append(d)
        return out

    def active_incident(self) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM declared_incidents WHERE status='ACTIVE' "
                "ORDER BY created_at DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(r)
        d["delivery"] = json.loads(d.get("delivery_json") or "{}")
        d.pop("delivery_json", None)
        return d

    def resolve_incident(self, incident_id: str):
        with self._lock:
            self._conn.execute(
                "UPDATE declared_incidents SET status='RESOLVED', "
                "resolved_at=? WHERE incident_id=?", (_now(), incident_id))
            self._conn.commit()

    def safety_event_counts(self) -> dict[str, int]:
        """v3.2 checklist J — the safety learning loop reads off the audit
        trail (single source of truth, no shadow counters)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT action, COUNT(*) c FROM audit_trail "
                "WHERE action LIKE 'safety_event:%' GROUP BY action").fetchall()
        return {r["action"].split(":", 1)[1]: r["c"] for r in rows}

    # --------------------------------------- Trust Layer notifications ----
    def notify(self, kind: str, title: str, body: str, ref: str | None = None
               ) -> str:
        nid = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """INSERT INTO notifications(id, kind, title, body, ref,
                       created_at) VALUES (?,?,?,?,?,?)""",
                (nid, kind, title, body, ref, _now()))
            self._conn.commit()
        # v4.3 §26 — every operator-facing notification IS an AlertTriggered
        # event on the single audit store (no shadow event log).
        self.audit(actor="platform", action="event:AlertTriggered",
                   decision="ALLOW",
                   detail=f"{kind}: {title[:120]}",
                   policy_version="platform-events/4.3.0")
        return nid

    def list_notifications(self, limit: int = 25) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------- AUDITOR trail ----
    def audit(self, actor: str, action: str, decision: str, detail: str,
              policy_version: str) -> str:
        aid = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """INSERT INTO audit_trail(id, actor, action, decision, detail,
                       policy_version, created_at) VALUES (?,?,?,?,?,?,?)""",
                (aid, actor, action, decision, detail, policy_version, _now()))
            self._conn.commit()
        return aid

    def audit_trail(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_trail ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------- Custom agent SDK (§5.2/A-13) ----
    def register_custom_agent(self, agent_id: str, name: str,
                              functions: list[str], status: str,
                              drift_notes: str | None = None):
        with self._lock:
            self._conn.execute(
                """INSERT INTO custom_agents(agent_id, name, functions_json,
                       status, drift_notes, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (agent_id, name, json.dumps(functions), status, drift_notes,
                 _now()))
            self._conn.commit()

    def get_custom_agent(self, agent_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM custom_agents WHERE agent_id=?",
                (agent_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["functions"] = json.loads(d.get("functions_json") or "[]")
        d.pop("functions_json", None)
        return d

    def list_custom_agents(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM custom_agents ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["functions"] = json.loads(d.get("functions_json") or "[]")
            d.pop("functions_json", None)
            out.append(d)
        return out

    def update_custom_agent(self, agent_id: str, status: str | None = None,
                            shadow_tree_count: int | None = None,
                            drift_notes: str | None = None):
        with self._lock:
            if status is not None:
                self._conn.execute(
                    "UPDATE custom_agents SET status=? WHERE agent_id=?",
                    (status, agent_id))
            if shadow_tree_count is not None:
                self._conn.execute(
                    "UPDATE custom_agents SET shadow_tree_count=? "
                    "WHERE agent_id=?", (shadow_tree_count, agent_id))
            if drift_notes is not None:
                self._conn.execute(
                    "UPDATE custom_agents SET drift_notes=? WHERE agent_id=?",
                    (drift_notes, agent_id))
            self._conn.commit()

    # ------------------------------ VOYAGER journey watches (§5.1/P3) ----
    def add_watch(self, watch_id: str, origin: str, destination: str,
                  departure_time: str, baseline_risk: str,
                  priority: str = "balanced", tolerance: str = "MODERATE",
                  user_id: str | None = None):
        with self._lock:
            self._conn.execute(
                """INSERT INTO journey_watches(watch_id, origin, destination,
                       departure_time, priority, baseline_risk, current_risk,
                       tolerance, user_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (watch_id, origin, destination, departure_time, priority,
                 baseline_risk, baseline_risk, tolerance, user_id,
                 _now(), _now()))
            self._conn.commit()

    def get_watch(self, watch_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM journey_watches WHERE watch_id=?",
                (watch_id,)).fetchone()
        return dict(r) if r else None

    def list_watches(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM journey_watches"
        if active_only:
            sql += " WHERE status IN ('MONITORING','ELEVATED')"
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def update_watch(self, watch_id: str, current_risk: str | None = None,
                     status: str | None = None,
                     reroute_pending: int | None = None):
        with self._lock:
            if current_risk is not None:
                self._conn.execute(
                    "UPDATE journey_watches SET current_risk=?, updated_at=? "
                    "WHERE watch_id=?", (current_risk, _now(), watch_id))
            if status is not None:
                self._conn.execute(
                    "UPDATE journey_watches SET status=?, updated_at=? "
                    "WHERE watch_id=?", (status, _now(), watch_id))
            if reroute_pending is not None:
                # v4.6 — a watch elevated beyond tolerance DOES recommend a
                # reroute; that recommendation is pending until adjudicated.
                self._conn.execute(
                    "UPDATE journey_watches SET reroute_pending=?, "
                    "updated_at=? WHERE watch_id=?",
                    (reroute_pending, _now(), watch_id))
            self._conn.commit()

    # --------------------- v4.6 §71 adjudication write-paths ---------------
    def review_get(self, review_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM review_queue WHERE id=?", (review_id,)
            ).fetchone()
        return dict(r) if r else None

    def review_decide(self, review_id: str, *, decision: str, decided_by: str,
                      prior_outcome: str | None,
                      corrected_outcome: str | None) -> int:
        """Atomic single-decision guard (same discipline as approvals):
        UPDATE … WHERE status='OPEN' — a second human decision returns 0 and
        the caller 409s; both attempts stay on the audit trail."""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE review_queue SET status='DECIDED', decision=?,
                   decided_by=?, decided_at=?, prior_outcome=?,
                   corrected_outcome=?
                   WHERE id=? AND status='OPEN'""",
                (decision, decided_by, _now(), prior_outcome,
                 corrected_outcome, review_id))
            self._conn.commit()
            return cur.rowcount

    def notification_get(self, notification_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM notifications WHERE id=?",
                (notification_id,)).fetchone()
        return dict(r) if r else None

    def adjudicate_notification(self, notification_id: str, *,
                                verdict: str, adjudicated_by: str) -> int:
        """One adjudication per alert (WHERE adjudication IS NULL) — the
        §71 false-alarm denominator can never be silently rewritten."""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE notifications SET adjudication=?, adjudicated_by=?,
                   adjudicated_at=? WHERE id=? AND adjudication IS NULL""",
                (verdict, adjudicated_by, _now(), notification_id))
            self._conn.commit()
            return cur.rowcount

    def decide_watch_reroute(self, watch_id: str, *, outcome: str) -> int:
        """Resolve a PENDING reroute recommendation once (ACCEPTED/DECLINED;
        AUTO_RESOLVED is the engine's own when risk eases)."""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE journey_watches SET reroute_pending=0,
                   reroute_outcome=?, reroute_decided_at=?, updated_at=?
                   WHERE watch_id=? AND reroute_pending=1""",
                (outcome, _now(), _now(), watch_id))
            self._conn.commit()
            return cur.rowcount

    def reroute_rows(self, limit: int = 50) -> list[dict]:
        """Pending + recently decided reroute recommendations (journey
        oversight strip in the Governance pane)."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT watch_id, origin, destination, current_risk, status,
                          reroute_pending, reroute_outcome, reroute_decided_at,
                          updated_at FROM journey_watches
                   WHERE reroute_pending=1 OR reroute_outcome IS NOT NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------- §3.4 personalization (presentation only) ----
    def get_prefs(self, user_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM user_preferences WHERE user_id=?",
                (user_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["watchlists"] = json.loads(d.pop("watchlists_json") or "[]")
        d["watchlist_state"] = json.loads(
            d.pop("watchlist_state_json") or "{}")
        return d

    def upsert_prefs(self, user_id: str, *, watchlists: list[str],
                     journey_priority: str, notify_tolerance: str,
                     output_format: str,
                     watchlist_state: dict | None = None):
        existing = self.get_prefs(user_id)
        state = watchlist_state if watchlist_state is not None else (
            existing or {}).get("watchlist_state", {})
        with self._lock:
            self._conn.execute(
                """INSERT INTO user_preferences(user_id, watchlists_json,
                       journey_priority, notify_tolerance, output_format,
                       watchlist_state_json, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     watchlists_json=excluded.watchlists_json,
                     journey_priority=excluded.journey_priority,
                     notify_tolerance=excluded.notify_tolerance,
                     output_format=excluded.output_format,
                     watchlist_state_json=excluded.watchlist_state_json,
                     updated_at=excluded.updated_at""",
                (user_id, json.dumps(watchlists), journey_priority,
                 notify_tolerance, output_format, json.dumps(state), _now()))
            self._conn.commit()

    def set_prefs_region(self, user_id: str, region: str) -> None:
        """v3.4 — region is a *privacy* input (consent defaults), not a
        personalization surface, so it is writable without the
        personalization-consent gate; the write is audited in privacy.py."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO user_preferences(user_id, region, updated_at)
                   VALUES (?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     region=excluded.region, updated_at=excluded.updated_at""",
                (user_id, region, _now()))
            self._conn.commit()

    def update_watchlist_state(self, user_id: str, state: dict):
        with self._lock:
            self._conn.execute(
                "UPDATE user_preferences SET watchlist_state_json=?, "
                "updated_at=? WHERE user_id=?",
                (json.dumps(state), _now(), user_id))
            self._conn.commit()

    def delete_user_artifacts(self, user_id: str) -> dict:
        """v3.2 "Manage Data" exit ramp: erase a user's personal data.
        Scope (documented): preferences + watchlist state + that user's
        journey watches. The consent ledger is intentionally NOT touched —
        it is the §5.3 tamper-evident audit record (pseudonymous ids)."""
        with self._lock:
            p = self._conn.execute(
                "DELETE FROM user_preferences WHERE user_id=?", (user_id,))
            w = self._conn.execute(
                "DELETE FROM journey_watches WHERE user_id=?", (user_id,))
            self._conn.commit()
        return {"preferences_deleted": p.rowcount,
                "watches_deleted": w.rowcount}

    def all_prefs(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT user_id FROM user_preferences"
                                      ).fetchall()
        return [self.get_prefs(r[0]) for r in rows]

    # ------------------------- v4.0 §2 Investigation Core -----------------
    def inv_create(self, inv_id: str, objective: str, subject_type: str,
                   subject: str, purpose: str, authority: str, scope: str,
                   allowed_sources_json: str, expires_at: str, status: str,
                   user_id: str):
        with self._lock:
            self._conn.execute(
                """INSERT INTO investigations(id, objective, subject_type,
                       subject, purpose, authority, scope, allowed_sources_json,
                       expires_at, status, user_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, objective, subject_type, subject, purpose, authority,
                 scope, allowed_sources_json, expires_at, status, user_id,
                 _now(), _now()))
            self._conn.commit()

    @staticmethod
    def _inv_row(r) -> dict:
        d = dict(r)
        d["allowed_sources"] = json.loads(
            d.pop("allowed_sources_json", None) or "[]")
        return d

    def inv_get(self, inv_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM investigations WHERE id=?",
                (inv_id,)).fetchone()
        if not r:
            return None
        d = self._inv_row(r)
        d["links"] = self.inv_links_for(inv_id)
        return d

    def inv_list(self, user_id: str | None = None,
                 limit: int = 50) -> list[dict]:
        with self._lock:
            sql = "SELECT * FROM investigations"
            args: tuple = ()
            if user_id:
                sql += " WHERE user_id=?"
                args = (user_id,)
            sql += " ORDER BY created_at DESC LIMIT ?"
            rows = self._conn.execute(sql, (*args, limit)).fetchall()
        return [self._inv_row(r) for r in rows]

    def inv_set_status(self, inv_id: str, status: str):
        with self._lock:
            self._conn.execute(
                "UPDATE investigations SET status=?, updated_at=? WHERE id=?",
                (status, _now(), inv_id))
            self._conn.commit()

    def inv_link(self, link_id: str, inv_id: str, kind: str, ref_id: str):
        """§5 evidence chain: link any artifact (tree, evidence, watch,
        case) to the investigation that authorizes it."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO investigation_links(id, investigation_id, kind,
                       ref_id, created_at) VALUES (?,?,?,?,?)""",
                (link_id, inv_id, kind, ref_id, _now()))
            self._conn.commit()

    def inv_links_for(self, inv_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, kind, ref_id, created_at FROM investigation_links
                   WHERE investigation_id=? ORDER BY created_at""",
                (inv_id,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------- v4.2 approval engine (§26) ------------------
    def approval_create(self, approval_id: str, kind: str, subject_ref: str,
                        summary: str, requester: str, context_json: str,
                        auto_decide: tuple[str, str] | None = None):
        with self._lock:
            if auto_decide is None:
                self._conn.execute(
                    """INSERT INTO approvals(id, kind, subject_ref, summary,
                           requester, status, context_json, created_at)
                       VALUES (?,?,?,?,?, 'PENDING', ?, ?)""",
                    (approval_id, kind, subject_ref, summary, requester,
                     context_json, _now()))
            else:
                self._conn.execute(
                    """INSERT INTO approvals(id, kind, subject_ref, summary,
                           requester, status, decided_by, decided_at,
                           context_json, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (approval_id, kind, subject_ref, summary, requester,
                     auto_decide[0], auto_decide[1], _now(), context_json,
                     _now()))
            self._conn.commit()

    def approval_get(self, approval_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM approvals WHERE id=?",
                (approval_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["context"] = json.loads(d.pop("context_json", None) or "{}")
        return d

    def approval_list(self, status: str | None = None,
                      limit: int = 50) -> list[dict]:
        with self._lock:
            sql = "SELECT * FROM approvals"
            args: tuple = ()
            if status:
                sql += " WHERE status=?"
                args = (status,)
            sql += " ORDER BY created_at DESC LIMIT ?"
            rows = self._conn.execute(sql, (*args, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["context"] = json.loads(d.pop("context_json", None) or "{}")
            out.append(d)
        return out

    def approval_decide(self, approval_id: str, status: str,
                        decided_by: str):
        """Atomic-ish PENDING→decided transition; returns rows changed so
        double-decides surface as 0 (409 to the caller, never silent)."""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE approvals SET status=?, decided_by=?, decided_at=?
                   WHERE id=? AND status='PENDING'""",
                (status, decided_by, _now(), approval_id))
            self._conn.commit()
            return cur.rowcount

    # ------------------------- v4.3 continuous assurance -------------------
    def assurance_record(self, run_id: str, actor: str, posture: str,
                         summary_json: str, started_at: str,
                         finished_at: str):
        with self._lock:
            self._conn.execute(
                """INSERT INTO assurance_runs(id, actor, posture,
                       summary_json, started_at, finished_at)
                   VALUES (?,?,?,?,?,?)""",
                (run_id, actor, posture, summary_json, started_at,
                 finished_at))
            self._conn.commit()

    def assurance_list(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM assurance_runs
                   ORDER BY started_at DESC LIMIT ?""", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d.pop("summary_json", None) or "{}")
            out.append(d)
        return out

    def assurance_latest(self) -> dict | None:
        runs = self.assurance_list(limit=1)
        return runs[0] if runs else None

    # ------------------------- v4.4 custom connectors (§80) ----------------
    def connector_create(self, connector_id: str, name: str, kind: str,
                         base_url: str, auth_env: str | None,
                         registered_by: str, approval_id: str):
        with self._lock:
            self._conn.execute(
                """INSERT INTO connectors(id, name, kind, base_url, auth_env,
                       status, registered_by, approval_id, created_at)
                   VALUES (?,?,?,?,?, 'PENDING_APPROVAL', ?,?,?)""",
                (connector_id, name, kind, base_url, auth_env,
                 registered_by, approval_id, _now()))
            self._conn.commit()

    def connector_get(self, connector_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM connectors WHERE id=?",
                (connector_id,)).fetchone()
        return dict(r) if r else None

    def connector_list(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connectors ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def connector_set_status(self, connector_id: str, status: str):
        with self._lock:
            if status == "RETIRED":
                self._conn.execute(
                    """UPDATE connectors SET status=?, retired_at=?
                       WHERE id=?""",
                    (status, _now(), connector_id))
            else:
                self._conn.execute(
                    "UPDATE connectors SET status=? WHERE id=?",
                    (status, connector_id))
            self._conn.commit()

    # ------------------------- v4.5 pilot readiness ------------------------
    def kpi_sql(self, sql: str, params: tuple = ()) -> list[dict]:
        """Read-only SELECT accessor for the §71 KPI engine (v4.5).

        Single chokepoint for telemetry queries: anything not starting with
        SELECT is refused, so a KPI can never write — the telemetry layer
        observes the store, it does not mutate it (§20/§76 discipline
        applied to the metrics plane itself)."""
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("kpi_sql is read-only (SELECT only)")
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def evidence_id_by_hash(self, source_id: str,
                            content_hash: str) -> str | None:
        """Idempotency lookup for live-source ingestion (§68: one content,
        one row — re-observing the same bytes never duplicates evidence)."""
        with self._lock:
            row = self._conn.execute(
                """SELECT id FROM evidence
                   WHERE source_id=? AND content_hash=?
                   ORDER BY fetched_at DESC LIMIT 1""",
                (source_id, content_hash)).fetchone()
        return row["id"] if row else None

    # ------------------------- v4.4 retention sweeper ----------------------
    def delete_notifications_older_than(self, cutoff_iso: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM notifications WHERE created_at < ?",
                (cutoff_iso,))
            self._conn.commit()
            return cur.rowcount

    def delete_assurance_older_than(self, cutoff_iso: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM assurance_runs WHERE started_at < ?",
                (cutoff_iso,))
            self._conn.commit()
            return cur.rowcount

    def old_trees(self, cutoff_iso: str,
                      statuses: tuple[str, ...] = ("COMPLETE", "CANCELLED",
                                                   "REFUSED")
                      ) -> list[str]:
        with self._lock:
            marks = ",".join("?" * len(statuses))
            rows = self._conn.execute(
                f"""SELECT tree_id FROM ops_trees
                    WHERE status IN ({marks}) AND updated_at < ?""",
                (*statuses, cutoff_iso)).fetchall()
        return [r[0] for r in rows]

    # ------------------------- §5.3 consent ledger (append-only chain) ----
    def consent_append(self, entry_id: str, user_id: str, purpose: str,
                       state: str, detail: str, prev_hash: str,
                       entry_hash: str):
        """Append-only: callers compute the hash chain in core/privacy.py.
        No UPDATE/DELETE path exists for this table by design (immutable)."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO consent_ledger(id, user_id, purpose, state,
                       detail, prev_hash, entry_hash, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (entry_id, user_id, purpose, state, detail, prev_hash,
                 entry_hash, _now()))
            self._conn.commit()

    def consent_ledger(self, user_id: str | None = None,
                       limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM consent_ledger"
        args: tuple = ()
        if user_id:
            sql += " WHERE user_id=?"
            args = (user_id,)
        sql += " ORDER BY rowid LIMIT ?"
        rows = self._conn.execute(sql, (*args, limit)).fetchall()
        return [dict(r) for r in rows]

    def consent_latest_hash(self) -> str:
        with self._lock:
            r = self._conn.execute(
                "SELECT entry_hash FROM consent_ledger ORDER BY rowid DESC "
                "LIMIT 1").fetchone()
        return r[0] if r else "GENESIS"

    # ------------------------------------------------------- maintenance --
    def expire_raw_content(self, retention_days: int):
        """§25 retention: null out excerpts older than retention window."""
        with self._lock:
            self._conn.execute(
                """UPDATE evidence SET excerpt = NULL, raw_ref = 'purged'
                   WHERE fetched_at < datetime('now', ? || ' days')""",
                (f"-{retention_days}",),
            )
            self._conn.commit()


_store: EvidenceStore | None = None


def get_store() -> EvidenceStore:
    global _store
    if _store is None:
        _store = EvidenceStore()
    return _store


def reset_store(path: str | None = None) -> EvidenceStore:
    global _store
    if _store is not None:
        _store.close()
    _store = EvidenceStore(path)
    return _store
