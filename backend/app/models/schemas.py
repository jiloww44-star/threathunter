"""Pydantic schemas — spec Part 1.3 (the response contract, §19).

Every intelligence endpoint returns the IntelligenceResponse shape so the UI
can render one consistent progressive-disclosure result card.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- enums ----
class Confidence(str, Enum):  # §1.7 — honest levels, UNDETERMINED is first-class
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"
    UNDETERMINED = "UNDETERMINED"


class Verdict(str, Enum):  # §19 verdict taxonomy
    VERIFIED = "VERIFIED"
    MOSTLY_TRUE = "MOSTLY_TRUE"
    PARTIALLY_TRUE = "PARTIALLY_TRUE"
    MISLEADING = "MISLEADING"
    FALSE = "FALSE"
    UNVERIFIED = "UNVERIFIED"  # absence of evidence ≠ FALSE (§1.9)


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrustLabel(str, Enum):
    """§26 trust model — never present inference as fact."""

    FACT = "FACT"
    EVIDENCE = "EVIDENCE"
    INFERENCE = "INFERENCE"


class KYCDecision(str, Enum):  # §13 decision taxonomy
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_REVIEW = "VERIFIED_WITH_ADDITIONAL_REVIEW"
    PENDING = "PENDING"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"
    REQUIRES_MANUAL_REVIEW = "REQUIRES_MANUAL_REVIEW"


# ------------------------------------------------------------ components ----
class EvidenceItem(BaseModel):
    source_id: str
    url: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    reliability: str
    reliability_score: float = 0.2
    authority: str  # PRIMARY | SECONDARY
    independence_group: str
    supports_claim: bool | None = None  # True / False / None (neutral)
    excerpt: str
    is_duplicate_copy: bool = False  # flagged copy-chain member (§1.6)


class Contradiction(BaseModel):
    description: str
    evidence_a_id: str
    evidence_b_id: str
    severity: RiskLevel


# ------------------------------------------------------------- responses ----
class IntelligenceResponse(BaseModel):
    """§19 — every intelligence endpoint returns this shape."""

    answer: str
    confidence: Confidence
    key_evidence: list[EvidenceItem] = []
    contradictions: list[Contradiction] = []
    interpretation: str = ""  # clearly labeled INFERENCE
    recommended_action: str = ""
    sources_independent: int = 0  # copy-chain aware count (§1.6)
    sources_total: int = 0
    what_would_change_conclusion: str = ""
    reasoning_trace: list[str] = []  # expandable by analysts


class FactCheckRequest(BaseModel):
    claim: str = Field(max_length=280)


class FactCheckResponse(IntelligenceResponse):
    verdict: Verdict
    claim: str
    checked_at: datetime
    check_id: str | None = None
    graph_url: str | None = None  # evidence graph for this case (Part 12)
    ai_narrative: dict | None = None  # OpenRouter provenance {model_used, mode}
    # §1.6 display metrics — near-text clusters across ALL candidates
    # (syndication often spans hosts/groups). Pure display fields: verdict
    # math always uses independence groups, never text clusters.
    copy_chain_clusters: int | None = None
    copy_chain_note: str | None = None  # "13 articles trace to <origin>"
    # Part 18 D1 — where this verdict went after scoring and why (§20:
    # routing is disclosed, never silently skipped)
    review_route: str | None = None


class JourneySegmentRisk(BaseModel):
    time: str
    segment: str
    risk: RiskLevel
    why: str  # §7 — every change of level is explained
    lat: float | None = None   # segment midpoint for map overlay (spec §1.4-1.5)
    lon: float | None = None
    incident_count: int = 0
    max_severity: str = "NONE"


class RouteOption(BaseModel):
    route: str
    safety_score: float
    travel_time_min: int
    exposure_km_high_risk: float
    trade_off: str  # §8 — explicit trade-offs, never silent shortest-path


class JourneyRequest(BaseModel):
    origin: str
    destination: str
    departure_time: datetime | None = None
    transport_mode: str | None = None
    priority: str = "balanced"  # safest | fastest | balanced | lowest_exposure


class JourneyPrediction(BaseModel):
    segment: str
    predicted_risk: RiskLevel
    language: str  # hedged phrasing (§9) — never false certainty
    confidence: Confidence
    basis: str
    factors: dict[str, float]


class JourneyResponse(BaseModel):
    # §19 shape retained: same fields as IntelligenceResponse plus journey data
    answer: str
    confidence: Confidence
    status: str = "COMPLETE"  # COMPLETE | CLARIFICATION_NEEDED
    missing_fields: list[str] = []
    question: str | None = None  # §14-15 conversational clarification
    context_retained: dict = {}
    risk_timeline: list[JourneySegmentRisk] = []
    route_options: list[RouteOption] = []
    prediction: list[JourneyPrediction] = []
    interpretation: str = ""
    recommended_action: str = ""
    what_would_change_conclusion: str = ""
    reasoning_trace: list[str] = []
    review_route: str | None = None  # Part 18 D1 routing lane (disclosed)
    sources_independent: int = 0
    sources_total: int = 0
    # OSM integration (spec §1) — honest mode marker per §20
    data_mode: str = "offline-fixture"   # live | offline-fixture
    route_geometry: dict | None = None   # geojson polyline for Leaflet (§1.5)
    route_summary: dict | None = None    # {total_km, total_min, origin, destination}
    ai_narrative: dict | None = None     # OpenRouter narrative {model_used, mode}


# ------------------------------------------------------------------ KYC ----
class KYCDocumentExtraction(BaseModel):
    """Input contract for the document the user uploaded (already OCR-parsed)."""

    name: str
    dob: str  # ISO date
    doc_type: str = "passport"
    number_hash: str = ""  # never the raw number — §25 data minimization
    issue_date: str
    expiry_date: str
    min_issue_age: int = 16
    country: str = "NG"


class KYCUserInput(BaseModel):
    name: str
    dob: str


class KYCVerifyRequest(BaseModel):
    document: KYCDocumentExtraction
    user_input: KYCUserInput
    selfie_ref: str | None = None  # demo: "mock:pass" | "mock:spoof" | "mock:low_quality"
    fixture_id: str | None = None  # seed-pack driven demo scenario


class KYCAnomaly(BaseModel):
    type: str
    severity: RiskLevel = RiskLevel.LOW
    detail: str = ""
    action: str = "Additional verification recommended"  # anomaly ≠ fraud (§12)


class KYCResponse(BaseModel):
    case_id: str
    decision: KYCDecision
    confidence: Confidence
    anomalies: list[KYCAnomaly] = []
    checks: dict[str, bool | str | float] = {}
    answer: str
    interpretation: str
    recommended_action: str
    what_would_change_conclusion: str = ""
    reasoning_trace: list[str] = []
    routed_to_human_review: bool = False  # §27 human-in-the-loop


# --------------------------------------------------------------- feed/etc ----
class RecentCheck(BaseModel):
    check_id: str
    module: str  # factcheck | journey | kyc
    subject: str
    outcome: str
    confidence: Confidence
    created_at: datetime


class Statistics(BaseModel):
    total_checks: int
    verdict_mix: dict[str, int]
    avg_confidence_score: float
    sources_active: int
    evidence_items: int
    signals_indexed: int
    copy_chain_ratio: float  # monitoring metric (Part 4.4)
    review_queue_depth: int  # §27 human-in-the-loop backlog
    source_freshness_lag_min: dict[str, float] = {}
    model_versions: dict[str, str] = {}


class GraphData(BaseModel):
    nodes: list[dict]
    edges: list[dict]
