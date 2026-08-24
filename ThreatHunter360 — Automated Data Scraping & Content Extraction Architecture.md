# ThreatHunter360 — Automated Data Scraping & Content Extraction Architecture

Below is a complete design that combines the ThreatHunter360 intelligence model with an automated scraping/extraction layer feeding the Fact Checker, Journey Advisor, and KYC modules.

---

## 1\. SYSTEM ARCHITECTURE OVERVIEW

┌─────────────────────────────────────────────────────────────┐  
│                    THREATHUNTER360 PLATFORM                  │  
├──────────────┬──────────────┬──────────────┬────────────────┤  
│ FACT CHECKER │ JOURNEY      │ KYC          │ RECENT CHECKS  │  
│              │ ADVISOR      │ VERIFICATION │ & STATISTICS   │  
└──────┬───────┴──────┬───────┴──────┬───────┴────────────────┘  
       │              │              │  
┌──────▼──────────────▼──────────────▼────────────────────────┐  
│           INDUCTIVE-LOGICAL REASONING ENGINE                 │  
│  Observation → Signals → Patterns → Hypotheses → Confidence │  
└──────────────────────────┬──────────────────────────────────┘  
                           │  
┌──────────────────────────▼──────────────────────────────────┐  
│            EVIDENCE CORRELATION & GRAPH STORE                │  
│   (Neo4j / PostgreSQL \+ pgvector for semantic matching)     │  
└──────────────────────────┬──────────────────────────────────┘  
                           │  
┌──────────────────────────▼──────────────────────────────────┐  
│         AUTOMATED SCRAPING & EXTRACTION PIPELINE             │  
│  Scheduler → Fetchers → Parsers → Normalizers → Validators  │  
└──────────────────────────┬──────────────────────────────────┘  
                           │  
┌──────────────────────────▼──────────────────────────────────┐  
│                     DATA SOURCE LAYER                        │  
│ News APIs · Gov/regulatory feeds · Weather · Traffic ·      │  
│ Threat intel feeds · OSINT · Maps/geospatial · Sanctions    │  
└─────────────────────────────────────────────────────────────┘

---

## 2\. SCRAPING PIPELINE DESIGN

### 2.1 Pipeline Stages

SCHEDULE ─► FETCH ─► EXTRACT ─► NORMALIZE ─► SIGNALIZE ─► WEIGHT ─► STORE  
   │           │         │           │            │           │         │  
 cron/     requests/  BeautifulSoup  JSON-LD    Entity      Source    Evidence  
 event-    Playwright \+ NLP        schema.org extraction  scoring   graph \+  
 driven    RSS/APIs   pipelines    \+ custom   \+ date/loc  \+ dedupe  metadata

### 2.2 Source Registry (config-driven)

\# sources.yaml  
sources:  
  \- id: gov\_sanctions\_feed  
    type: regulatory  
    method: api  
    url: "https://api.example-sanctions.gov/v1/list"  
    schedule: "0 \*/6 \* \* \*"          \# every 6 hours  
    reliability: HIGH  
    authority: PRIMARY

  \- id: news\_rss\_cluster  
    type: news  
    method: rss  
    urls:  
      \- "https://newsoutlet-a.com/feed"  
      \- "https://newsoutlet-b.com/feed"  
    schedule: "\*/15 \* \* \* \*"  
    reliability: MODERATE  
    independence\_group: press         \# used to detect copy-chains

  \- id: threat\_intel\_osint  
    type: threat\_intel  
    method: scraper  
    url: "https://osint-portal.example/reports"  
    parser: osint\_report\_v2  
    schedule: "0 \* \* \* \*"  
    requires\_auth: true

**Key principle:** each source carries reliability, authority, and an independence\_group so the engine can distinguish *5 independent sources* from *1 source copied by 5 websites* (§1.6).

---

## 3\. IMPLEMENTATION — SCRAPER CORE (Python)

\# scraper/pipeline.py  
import asyncio, hashlib, json  
from dataclasses import dataclass, field  
from datetime import datetime, timezone  
from enum import Enum

class Reliability(Enum):  
    VERY\_HIGH \= 0.95; HIGH \= 0.8; MODERATE \= 0.6; LOW \= 0.35; UNKNOWN \= 0.2

@dataclass  
class RawEvidence:  
    source\_id: str  
    url: str  
    fetched\_at: str  
    content\_hash: str  
    raw\_text: str  
    metadata: dict \= field(default\_factory=dict)

@dataclass  
class Signal:  
    entity: str | None  
    event\_type: str | None  
    location: str | None  
    time: str | None  
    claim\_text: str  
    confidence\_input: float      \# from source reliability  
    source\_id: str  
    independence\_group: str

### 3.1 Fetcher with deduplication & provenance

\# scraper/fetcher.py  
import httpx, hashlib  
from datetime import datetime, timezone

async def fetch(client: httpx.AsyncClient, src: dict) \-\> RawEvidence | None:  
    try:  
        r \= await client.get(src\["url"\], timeout=15,  
                             headers={"User-Agent": "ThreatHunter360Bot/1.0"})  
        r.raise\_for\_status()  
        text \= r.text  
        h \= hashlib.sha256(text.encode()).hexdigest()  
        return RawEvidence(  
            source\_id=src\["id"\],  
            url=src\["url"\],  
            fetched\_at=datetime.now(timezone.utc).isoformat(),  
            content\_hash=h,  
            raw\_text=text,  
            metadata={"reliability": src\["reliability"\],  
                      "authority": src.get("authority", "SECONDARY"),  
                      "independence\_group": src.get("independence\_group", src\["id"\])},  
        )  
    except Exception as e:  
        \# §20 ERROR HANDLING — classify, never fabricate  
        log\_error(source=src\["id"\], code="SOURCE\_UNAVAILABLE", detail=str(e))  
        return None

### 3.2 Content extraction → structured signals

\# scraper/extractor.py  
from bs4 import BeautifulSoup  
import json, re

def extract\_signals(ev: RawEvidence) \-\> list\[Signal\]:  
    soup \= BeautifulSoup(ev.raw\_text, "lxml")

    \# Prefer structured data when present  
    signals \= \[\]  
    for script in soup.find\_all("script", type\="application/ld+json"):  
        try:  
            data \= json.loads(script.string)  
            signals.extend(from\_jsonld(data, ev))  
        except Exception:  
            pass

    if not signals:  
        text \= soup.get\_text(separator=" ", strip=True)  
        signals.extend(from\_nlp(text, ev))   \# spaCy NER \+ dateparser  
    return signals

def from\_nlp(text: str, ev: RawEvidence) \-\> list\[Signal\]:  
    doc \= nlp(text\[:10000\])  
    entities \= \[(e.text, e.label\_) for e in doc.ents\]  
    dates \= extract\_dates(text)  
    locations \= \[t for t, l in entities if l in ("GPE", "LOC")\]  
    orgs      \= \[t for t, l in entities if l \== "ORG"\]  
    return \[Signal(  
        entity=(orgs or \[None\])\[0\],  
        event\_type=classify\_event(text),  
        location=(locations or \[None\])\[0\],  
        time=(dates or \[None\])\[0\],  
        claim\_text=text\[:500\],  
        confidence\_input=Reliability\[ev.metadata\["reliability"\]\].value,  
        source\_id=ev.source\_id,  
        independence\_group=ev.metadata\["independence\_group"\],  
    )\]

### 3.3 Copy-chain detection (independence analysis)

\# scraper/dedupe.py  
from simhash import Simhash

def detect\_copy\_chains(signals: list\[Signal\], threshold: int \= 6):  
    """Group near-identical claims; a group of 5 similar items from the  
    same independence\_group counts as ONE source, not five."""  
    groups \= \[\]  
    for s in signals:  
        placed \= False  
        for g in groups:  
            if abs(Simhash(s.claim\_text).distance(Simhash(g\[0\].claim\_text))) \<= threshold \\  
               and s.independence\_group \== g\[0\].independence\_group:  
                g.append(s); placed \= True; break  
        if not placed:  
            groups.append(\[s\])  
    return groups   \# each group \= one effective independent source

### 3.4 Orchestrator

\# scraper/orchestrator.py  
async def run\_pipeline():  
    async with httpx.AsyncClient() as client:  
        tasks \= \[fetch(client, s) for s in load\_sources()\]  
        results \= await asyncio.gather(\*tasks)  
    evidence \= \[r for r in results if r\]  
    signals \= \[sig for ev in evidence for sig in extract\_signals(ev)\]  
    independent\_groups \= detect\_copy\_chains(signals)  
    store\_evidence\_graph(evidence, signals, independent\_groups)  
    trigger\_reassessment()   \# §1.10 continuous updating

Schedule via **Celery beat** or **APScheduler**; event-driven fetches triggered by breaking-news keywords for urgent claims.

---

## 4\. EVIDENCE STORAGE SCHEMA

CREATE TABLE evidence (  
    id UUID PRIMARY KEY,  
    source\_id TEXT NOT NULL,  
    url TEXT,  
    fetched\_at TIMESTAMPTZ,  
    reliability NUMERIC,  
    authority TEXT,               \-- PRIMARY | SECONDARY  
    independence\_group TEXT,  
    content\_hash TEXT,  
    raw\_ref TEXT                  \-- pointer to encrypted blob store  
);

CREATE TABLE signals (  
    id UUID PRIMARY KEY,  
    evidence\_id UUID REFERENCES evidence(id),  
    entity TEXT, event\_type TEXT,  
    location GEOGRAPHY, event\_time TIMESTAMPTZ,  
    claim\_embedding VECTOR(1536), \-- pgvector for semantic correlation  
    extracted\_at TIMESTAMPTZ  
);

CREATE TABLE hypotheses (  
    id UUID PRIMARY KEY,  
    case\_id UUID,  
    statement TEXT,  
    supporting INT, contradicting INT,  
    confidence TEXT CHECK (confidence IN  
      ('VERY\_HIGH','HIGH','MODERATE','LOW','VERY\_LOW','UNDETERMINED')),  
    status TEXT DEFAULT 'ACTIVE',  
    updated\_at TIMESTAMPTZ  
);

New scraped evidence automatically triggers hypothesis re-testing and confidence updates (§1.10).

---

## 5\. FEEDING THE THREE MODULES

| Module | Scraped data consumed |
| :---- | :---- |
| **Fact Checker** | News/regulatory/gov claims → correlated against user's 280-char claim → verdict \+ confidence |
| **Journey Advisor** | Weather API, traffic API, incident feeds, crime patterns → risk timeline per route segment |
| **KYC** | Sanctions lists, watchlists, document-format registries → consistency & anomaly checks |

Example Journey risk ingestion:

def build\_risk\_timeline(route\_segments, weather, incidents, traffic):  
    timeline \= \[\]  
    for seg in route\_segments:  
        env\_risk  \= score(weather.at(seg.point, seg.eta))  
        sec\_risk  \= score(incidents.near(seg.point, window="72h"))  
        mob\_risk  \= score(traffic.at(seg.point, seg.eta))  
        level \= fuse(env\_risk, sec\_risk, mob\_risk)   \# LOW→MODERATE→HIGH  
        timeline.append({  
            "time": seg.eta, "segment": seg.name, "risk": level,  
            "why": explain(level, env\_risk, sec\_risk, mob\_risk)  \# §7 explains changes  
        })  
    return timeline

---

## 6\. FRONTEND INTEGRATION (per §18–19 UX model)

Home exposes three capabilities immediately:

┌──────────────────────────────────────────────┐  
│  🔍 FACT CHECKER      "Is this claim true?"  │  
│  🛡️ JOURNEY ADVISOR   "Is my journey safe?"  │  
│  🪪 KYC VERIFY        "Verify my identity"   │  
└──────────────────────────────────────────────┘

Every result renders the consistent response model with progressive disclosure:

ANSWER  ──────────────────────────  visible first  
CONFIDENCE  ●●●○○  HIGH  
KEY EVIDENCE        \[expand ▾\]  ← analysts only  
CONTRADICTIONS      \[expand ▾\]  
INTERPRETATION  
RECOMMENDED ACTION  
SOURCES (n independent of m total)  \[expand ▾\]

Loading states reflect real pipeline stages (§21):

Analyzing claim… → Comparing sources… → Checking contradictions…  
→ Assessing confidence…

Errors surface classified codes (SOURCE\_UNAVAILABLE, INSUFFICIENT\_EVIDENCE) with what happened / what it means / what to do next — never a fabricated result.

---

## 7\. OPERATIONAL GUARDRAILS

1. **Rate limiting & robots.txt compliance** per source; authenticated APIs use secret manager.  
2. **Provenance on everything**: every stored item keeps source, timestamp, reliability, independence group (§16–17).  
3. **Human-in-the-loop queue**: high-conflict or high-risk cases route to analyst review (§27).  
4. **Retention policies**: raw scraped content auto-expires; KYC data encrypted at rest, minimized, securely deleted (§25).  
5. **Monitoring**: scrape success rate, source freshness lag, copy-chain ratio alerts.

---

Want me to go deeper on any piece next — e.g., the full FastAPI backend, the React dashboard UI, the NLP extraction models, or the Celery scheduling setup?

Copy  
yes

# ThreatHunter360 — Full Implementation Deep Dive

Below are the four components in production-ready form.

---

# PART 1 — FASTAPI BACKEND

## 1.1 Project Structure

threathunter360/  
├── app/  
│   ├── main.py  
│   ├── config.py  
│   ├── api/  
│   │   ├── routes/  
│   │   │   ├── factcheck.py  
│   │   │   ├── journey.py  
│   │   │   ├── kyc.py  
│   │   │   └── feed.py          \# recent checks \+ statistics  
│   │   └── deps.py  
│   ├── core/  
│   │   ├── reasoning\_engine.py  \# inductive-logical engine  
│   │   ├── confidence.py  
│   │   ├── contradictions.py  
│   │   └── trust\_model.py       \# FACT/EVIDENCE/INFERENCE separation  
│   ├── scraper/  
│   │   ├── orchestrator.py  
│   │   ├── fetcher.py  
│   │   ├── extractor.py  
│   │   └── dedupe.py  
│   ├── models/  
│   │   ├── schemas.py           \# Pydantic request/response models  
│   │   └── db.py                \# SQLAlchemy async  
│   └── tasks/  
│       ├── celery\_app.py  
│       └── scheduled\_scrapes.py  
├── alembic/  
├── tests/  
└── docker-compose.yml

## 1.2 Config & Secrets

\# app/config.py  
from pydantic\_settings import BaseSettings

class Settings(BaseSettings):  
    DATABASE\_URL: str  
    REDIS\_URL: str \= "redis://redis:6379/0"  
    OPENWEATHER\_KEY: str        \# from secret manager / env, never hardcoded  
    TRAFFIC\_API\_KEY: str  
    THREAT\_INTEL\_TOKEN: str  
    MAX\_CLAIM\_LENGTH: int \= 280  
    KYC\_ENCRYPTION\_KEY: str     \# Fernet key for PII at rest

    class Config:  
        env\_file \= ".env"

settings \= Settings()

## 1.3 Pydantic Schemas (the response contract)

These schemas enforce §19's consistent response model across every module:

\# app/models/schemas.py  
from pydantic import BaseModel, Field  
from enum import Enum  
from datetime import datetime

class Confidence(str, Enum):  
    VERY\_HIGH \= "VERY\_HIGH"; HIGH \= "HIGH"; MODERATE \= "MODERATE"  
    LOW \= "LOW"; VERY\_LOW \= "VERY\_LOW"; UNDETERMINED \= "UNDETERMINED"

class Verdict(str, Enum):  
    VERIFIED \= "VERIFIED"; MOSTLY\_TRUE \= "MOSTLY\_TRUE"  
    PARTIALLY\_TRUE \= "PARTIALLY\_TRUE"; MISLEADING \= "MISLEADING"  
    FALSE \= "FALSE"; UNVERIFIED \= "UNVERIFIED"

class RiskLevel(str, Enum):  
    LOW \= "LOW"; MODERATE \= "MODERATE"; HIGH \= "HIGH"; CRITICAL \= "CRITICAL"

class EvidenceItem(BaseModel):  
    source\_id: str  
    url: str | None  
    published\_at: datetime | None  
    fetched\_at: datetime  
    reliability: str  
    authority: str                 \# PRIMARY | SECONDARY  
    independence\_group: str  
    supports\_claim: bool | None    \# True/False/None (neutral)  
    excerpt: str

class Contradiction(BaseModel):  
    description: str  
    evidence\_a\_id: str  
    evidence\_b\_id: str  
    severity: RiskLevel

class IntelligenceResponse(BaseModel):  
    """§19 — every intelligence endpoint returns this shape."""  
    answer: str  
    confidence: Confidence  
    key\_evidence: list\[EvidenceItem\]  
    contradictions: list\[Contradiction\]  
    interpretation: str            \# clearly labeled INFERENCE  
    recommended\_action: str  
    sources\_independent: int  
    sources\_total: int  
    what\_would\_change\_conclusion: str  
    reasoning\_trace: list\[str\]     \# expandable by analysts

class FactCheckRequest(BaseModel):  
    claim: str \= Field(max\_length=280)

class FactCheckResponse(IntelligenceResponse):  
    verdict: Verdict  
    claim: str  
    checked\_at: datetime

class JourneySegmentRisk(BaseModel):  
    time: str  
    segment: str  
    risk: RiskLevel  
    why: str                       \# §7 explains each change

class JourneyRequest(BaseModel):  
    origin: str  
    destination: str  
    departure\_time: datetime | None \= None  
    transport\_mode: str | None \= None  
    priority: str \= "balanced"     \# safest|fastest|balanced|lowest\_exposure

class KYCDecision(str, Enum):  
    VERIFIED \= "VERIFIED"  
    VERIFIED\_WITH\_REVIEW \= "VERIFIED\_WITH\_ADDITIONAL\_REVIEW"  
    PENDING \= "PENDING"  
    UNABLE\_TO\_VERIFY \= "UNABLE\_TO\_VERIFY"  
    REQUIRES\_MANUAL\_REVIEW \= "REQUIRES\_MANUAL\_REVIEW"

## 1.4 Fact Check Endpoint

\# app/api/routes/factcheck.py  
from fastapi import APIRouter, BackgroundTasks, HTTPException  
from app.models.schemas import FactCheckRequest, FactCheckResponse, Verdict  
from app.core.reasoning\_engine import ReasoningEngine  
from app.api.deps import get\_db, current\_user

router \= APIRouter(prefix="/api/v1/factcheck", tags=\["Fact Checker"\])

@router.post("", response\_model=FactCheckResponse)  
async def check\_fact(  
    req: FactCheckRequest,  
    background\_tasks: BackgroundTasks,  
    db=Depends(get\_db),  
    user=Depends(current\_user),  
):  
    if len(req.claim.strip()) \== 0:  
        raise HTTPException(422, "Claim cannot be empty")

    engine \= ReasoningEngine(db)  
    result \= await engine.run\_full\_pipeline(req.claim)   \# §2 pipeline of spec

    \# Persist for Recent Checks feed \+ statistics (§3, §4)  
    background\_tasks.add\_task(engine.persist\_check, req.claim, result, user.id)  
    return result

## 1.5 The Reasoning Engine (core of the product)

\# app/core/reasoning\_engine.py  
import asyncio  
from datetime import datetime, timedelta, timezone

class ReasoningEngine:  
    """Implements: Observation → Signals → Patterns → Hypotheses →  
    Testing → Weighting → Confidence → Verdict."""

    def \_\_init\_\_(self, db):  
        self.db \= db

    async def run\_full\_pipeline(self, claim: str) \-\> dict:  
        trace \= \[\]

        \# \---- 1\. OBSERVATION (§1.1) \------------------------------------  
        entities, dates, locations \= extract\_claim\_elements(claim)  
        trace.append(f"Extracted {len(entities)} entities, "  
                     f"{len(dates)} dates, {len(locations)} locations")

        \# \---- 2\. SOURCE DISCOVERY (semantic search over scraped store) \--  
        candidates \= await self.db.search\_signals(  
            embedding=embed(claim),  
            entity\_filter=entities,  
            date\_range=self.\_relevant\_window(dates),  
            limit=50,  
        )  
        if not candidates:  
            return self.\_unverified(claim,  
                reason="No relevant evidence found in indexed sources.",  
                action="Try rephrasing or check back later as new data is ingested.")

        \# \---- 3\. INDEPENDENCE ANALYSIS (§1.6) \---------------------------  
        groups \= group\_by\_independence(candidates)   \# copy-chain aware  
        n\_independent \= len(groups)

        \# \---- 4\. CONTRADICTION DETECTION (§1.8) \-------------------------  
        contradictions \= detect\_contradictions(candidates)

        \# \---- 5\. HYPOTHESIS GENERATION & TESTING (§1.4–1.5) \-------------  
        hypotheses \= \[  
            Hypothesis("H1", "The event genuinely occurred."),  
            Hypothesis("H2", "Sources copied a single originating report."),  
            Hypothesis("H3", "Entity name confusion between similar entities."),  
            Hypothesis("H4", "Partially true but materially misleading."),  
        \]  
        for h in hypotheses:  
            h.test\_against(groups, contradictions, dates, locations)

        best \= max(hypotheses, key=lambda h: h.score())

        \# \---- 6\. CONFIDENCE (§1.7) \--------------------------------------  
        confidence \= score\_confidence(best, groups, contradictions)

        \# \---- 7\. VERDICT MAPPING \----------------------------------------  
        verdict \= map\_hypothesis\_to\_verdict(best, confidence)

        return self.\_build\_response(claim, verdict, confidence, best,  
                                    groups, contradictions, trace)

    def \_build\_response(self, claim, verdict, confidence, hyp,  
                        groups, contradictions, trace):  
        supporting \= \[e for g in groups for e in g if e.supports\_claim\]  
        contradicting \= \[e for g in groups for e in g if e.supports\_claim is False\]  
        return {  
            "verdict": verdict,  
            "confidence": confidence,  
            "claim": claim,  
            "answer": render\_answer(verdict, hyp),  
            "key\_evidence": \[e.to\_schema() for e in (supporting \+ contradicting)\[:10\]\],  
            "contradictions": \[c.to\_schema() for c in contradictions\],  
            \# Trust model labels (§26) — never present inference as fact:  
            "interpretation": f"INFERENCE: {hyp.statement}",  
            "recommended\_action": recommend\_action(verdict, confidence),  
            "sources\_independent": len(groups),  
            "sources\_total": sum(len(g) for g in groups),  
            "what\_would\_change\_conclusion":  
                "A primary official source confirming or denying the event, "  
                "or resolution of the flagged date conflict, would materially "  
                "change this assessment.",  
            "reasoning\_trace": trace,  
        }

## 1.6 Journey Endpoint with Conversational Clarification (§14–15)

\# app/api/routes/journey.py  
@router.post("/assess")  
async def assess\_journey(req: JourneyRequest, session=Depends(get\_session)):  
    missing \= \[\]  
    if req.departure\_time is None:  
        missing.append("departure\_time")

    if missing:  
        \# Ask ONLY for materially important info — don't restart the form  
        return {  
            "status": "CLARIFICATION\_NEEDED",  
            "question": "What time do you expect to leave?",  
            "missing\_fields": missing,  
            "context\_retained": {"origin": req.origin,  
                                 "destination": req.destination},  
        }

    timeline \= await build\_risk\_timeline(req)      \# weather+traffic+incidents  
    routes \= await compare\_routes(req, priority=req.priority)  
    prediction \= await predictive\_risk(req)        \# hedged language only

    return {  
        "status": "COMPLETE",  
        "risk\_timeline": timeline,  
        "route\_options": routes,                   \# explicit trade-offs  
        "prediction": prediction,                  \# "Risk appears elevated…"  
        "confidence": derive\_confidence(timeline),  
    }

## 1.7 Error Handling Middleware (§20)

\# app/api/errors.py  
ERROR\_MAP \= {  
    "SOURCE\_UNAVAILABLE": ("A data source could not be reached",  
                           "Results may be less complete than usual",  
                           "Retry shortly; we'll refresh automatically"),  
    "INSUFFICIENT\_EVIDENCE": ("Not enough reliable evidence was found",  
                              "No confident conclusion is possible",  
                              "Add context or try again later"),  
    "DOCUMENT\_UNREADABLE": ("The uploaded document couldn't be processed",  
                            "Verification is paused",  
                            "Upload a clearer photo or a different format"),  
}

@app.exception\_handler(PipelineError)  
async def pipeline\_error\_handler(request, exc):  
    title, meaning, next\_step \= ERROR\_MAP.get(exc.code, (  
        "An unexpected error occurred", "Processing stopped",  
        "Please retry or contact support"))  
    return JSONResponse(status\_code=exc.status, content={  
        "error\_code": exc.code, "title": title,  
        "meaning": meaning, "next\_step": next\_step})

---

# PART 2 — REACT DASHBOARD UI

## 2.1 Component Tree

\<App\>  
 ├─ \<Home/\>                        \# three capability cards (§18)  
 ├─ \<FactChecker/\>  
 │   ├─ \<ClaimInput maxLength=280 counter/\>  
 │   ├─ \<LoadingStages/\>           \# real pipeline stages (§21)  
 │   └─ \<IntelligenceResult\>       \# progressive disclosure (§19)  
 │       ├─ \<VerdictBadge/\> \<ConfidenceMeter/\>  
 │       ├─ \<EvidenceList collapsible/\>  
 │       ├─ \<ContradictionPanel/\>  
 │       └─ \<SourceProvenance independentOfTotal/\>  
 ├─ \<JourneyAdvisor/\>  
 │   ├─ \<ConversationalForm/\>      \# asks only missing fields  
 │   ├─ \<RiskTimeline/\>            \# vertical chronological viz (§7)  
 │   └─ \<RouteComparison/\>         \# trade-off table  
 ├─ \<KYCFlow/\>  
 │   ├─ \<StepProgress "Step 3 of 6"/\>  
 │   ├─ \<DocumentDropzone/\>  
 │   └─ \<DecisionBadge/\>  
 └─ \<RecentChecks/\> \<Statistics/\>

## 2.2 Claim Input with Character Counter

// src/components/FactChecker/ClaimInput.tsx  
export function ClaimInput({ onSubmit }: { onSubmit: (c: string) \=\> void }) {  
  const \[claim, setClaim\] \= useState("");  
  const MAX \= 280;  
  const over \= claim.length \> MAX;

  return (  
    \<form onSubmit\={(e) \=\> { e.preventDefault(); if (\!over && claim.trim()) onSubmit(claim); }}\>  
      \<label htmlFor\="claim"\>Enter a claim to verify\</label\>  
      \<textarea  
        id\="claim"  
        value\={claim}  
        onChange\={(e) \=\> setClaim(e.target.value)}  
        aria-describedby="char-count"  
        rows={3}  
      /\>  
      \<div id\="char-count" aria-live\="polite"\>  
        Characters: {claim.length} / {MAX}  
      \</div\>  
      \<button type\="submit" disabled\={over || \!claim.trim()}\>  
        Check Fact  
      \</button\>  
    \</form\>  
  );  
}

## 2.3 Meaningful Loading Stages (§21)

// src/components/shared/LoadingStages.tsx  
const STAGES \= \[  
  "Analyzing claim...",  
  "Comparing sources...",  
  "Checking contradictions...",  
  "Assessing confidence...",  
\];

export function LoadingStages({ active }: { active: boolean }) {  
  const \[stage, setStage\] \= useState(0);  
  useEffect(() \=\> {  
    if (\!active) return;  
    const t \= setInterval(() \=\> setStage(s \=\> Math.min(s \+ 1, STAGES.length \- 1)), 1200);  
    return () \=\> clearInterval(t);  
  }, \[active\]);

  if (\!active) return null;  
  return (  
    \<div role\="status" aria-live\="polite"\>  
      {STAGES.map((s, i) \=\> (  
        \<div key\={s} className\={i \=== stage ? "active" : i \< stage ? "done" : ""}\>  
          {i \< stage ? "✓" : i \=== stage ? "◌" : "·"} {s}  
        \</div\>  
      ))}  
    \</div\>  
  );  
}

## 2.4 Progressive Disclosure Result Card (§19)

// src/components/FactChecker/IntelligenceResult.tsx  
export function IntelligenceResult({ r }: { r: FactCheckResponse }) {  
  const \[showDetail, setShowDetail\] \= useState(false);

  return (  
    \<article className\="result-card"\>  
      {/\* Novice view first \*/}  
      \<header\>  
        \<VerdictBadge verdict\={r.verdict} /\>  
        \<ConfidenceMeter level\={r.confidence} /\>  
      \</header\>

      \<p className\="answer"\>{r.answer}\</p\>

      \<section className\="trust-labels"\>  
        \<span className\="tag inference"\>INFERENCE\</span\>  
        \<p\>{r.interpretation}\</p\>  
      \</section\>

      \<p className\="action"\>\<strong\>Recommended:\</strong\> {r.recommended\_action}\</p\>

      \<button onClick\={() \=\> setShowDetail(v \=\> \!v)}  
              aria-expanded={showDetail}\>  
        {showDetail ? "Hide analysis" : "Show full analysis"}  
      \</button\>

      {/\* Analyst view — progressively disclosed \*/}  
      {showDetail && (  
        \<\>  
          \<EvidenceList items\={r.key\_evidence} /\>  
          \<ContradictionPanel items\={r.contradictions} /\>  
          \<SourceProvenance independent\={r.sources\_independent}  
                            total\={r.sources\_total} /\>  
          \<ReasoningTrace steps\={r.reasoning\_trace} /\>  
          \<p className\="caveat"\>{r.what\_would\_change\_conclusion}\</p\>  
        \</\>  
      )}  
    \</article\>  
  );  
}

## 2.5 Risk Timeline Visualization (§7)

export function RiskTimeline({ segments }: { segments: JourneySegmentRisk\[\] }) {  
  const color \= { LOW: "\#22c55e", MODERATE: "\#f59e0b", HIGH: "\#ef4444", CRITICAL: "\#b91c1c" };  
  return (  
    \<ol className\="timeline" role\="list"\>  
      {segments.map((s, i) \=\> (  
        \<li key\={i} style\={{ borderLeftColor: color\[s.risk\] }}\>  
          \<time\>{s.time}\</time\>  
          \<strong\>{s.segment}\</strong\>  
          \<span className\={\`badge ${s.risk.toLowerCase()}\`}\>{s.risk}\</span\>  
          \<p className\="why"\>{s.why}\</p\>   {/\* always explain the change \*/}  
        \</li\>  
      ))}  
    \</ol\>  
  );  
}

Accessibility built in throughout: aria-live regions, keyboard-navigable disclosures, prefers-reduced-motion media query disabling transitions, semantic landmarks.

---

# PART 3 — NLP EXTRACTION MODELS

## 3.1 Model Stack

| Task | Tool | Notes |
| :---- | :---- | :---- |
| Entity recognition | spaCy en\_core\_web\_trf | ORG/GPE/PERSON/DATE |
| Date normalization | dateparser | Handles "last Tuesday", relative dates |
| Claim classification | Fine-tuned transformer (roberta-base) | factual/opinion/prediction |
| Semantic similarity | sentence-transformers/all-MiniLM-L6-v2 | claim↔evidence matching |
| Event typing | Zero-shot classifier (facebook/bart-large-mnli) | sanction/incident/outage/etc. |

## 3.2 Extraction Module

\# nlp/extractor.py  
import spacy, dateparser  
from sentence\_transformers import SentenceTransformer  
from zero\_shot import classify\_zero\_shot

nlp \= spacy.load("en\_core\_web\_trf")  
embedder \= SentenceTransformer("all-MiniLM-L6-v2")

EVENT\_LABELS \= \["sanction", "security incident", "natural disaster",  
                "regulatory action", "criminal activity", "infrastructure outage"\]

def extract\_claim\_elements(text: str):  
    doc \= nlp(text)  
    entities \= \[(e.text, e.label\_) for e in doc.ents\]  
    dates \= \[dateparser.parse(e.text) for e in doc.ents if e.label\_ in ("DATE", "TIME")\]  
    dates \= \[d for d in dates if d\]  
    locations \= \[e.text for e in doc.ents if e.label\_ in ("GPE", "LOC", "FAC")\]  
    orgs \= \[e.text for e in doc.ents if e.label\_ \== "ORG"\]  
    event\_type \= classify\_zero\_shot(text, EVENT\_LABELS)  
    return {"entities": entities, "dates": dates,  
            "locations": locations, "orgs": orgs, "event\_type": event\_type}

def embed(text: str):  
    return embedder.encode(text).tolist()

def similarity(a: str, b: str) \-\> float:  
    ea, eb \= embedder.encode(\[a, b\])  
    return float((ea @ eb) / ((ea\*\*2).sum()\*\*0.5 \* (eb\*\*2).sum()\*\*0.5))

## 3.3 Contradiction Detection Logic

\# core/contradictions.py  
def detect\_contradictions(signals: list\[Signal\]) \-\> list\[Contradiction\]:  
    out \= \[\]  
    for i, a in enumerate(signals):  
        for b in signals\[i+1:\]:  
            if not same\_entity(a, b):        \# fuzzy entity match ≥ 0.85  
                continue  
            \# Temporal contradiction  
            if a.time and b.time and abs(a.time \- b.time) \> timedelta(days=1):  
                out.append(Contradiction(  
                    description=f"Date conflict: {a.source\_id} says "  
                                f"{a.time.date()}, {b.source\_id} says {b.time.date()}",  
                    severity=RiskLevel.MODERATE))  
            \# Numeric/factual contradiction via NLI  
            nli \= nli\_score(a.claim\_text, b.claim\_text)  
            if nli\["contradiction"\] \> 0.75:  
                out.append(Contradiction(  
                    description=f"{a.source\_id} and {b.source\_id} make "  
                                f"incompatible claims about the same event",  
                    severity=RiskLevel.HIGH))  
    return out

## 3.4 KYC Document Consistency Checks (§12)

def kyc\_consistency\_checks(extracted\_doc: dict, user\_input: dict) \-\> list\[dict\]:  
    anomalies \= \[\]  
    \# Identity consistency  
    if normalize\_name(extracted\_doc\["name"\]) \!= normalize\_name(user\_input\["name"\]):  
        anomalies.append({"type": "NAME\_MISMATCH",  
                          "action": "Additional verification recommended"})  
    \# Temporal consistency — DOB vs document issue date  
    age\_at\_issue \= (extracted\_doc\["issue\_date"\] \- extracted\_doc\["dob"\]).days / 365.25  
    if age\_at\_issue \< extracted\_doc\["min\_issue\_age"\]:  
        anomalies.append({"type": "DATE\_INCONSISTENCY",  
                          "detail": "Issue date implausible given date of birth"})  
    \# Expiry  
    if extracted\_doc\["expiry\_date"\] \< today():  
        anomalies.append({"type": "DOCUMENT\_EXPIRED", "action": "Re-upload required"})  
    \# Anomaly ≠ fraud (§12): flag, never auto-deny on anomaly alone  
    return anomalies

Decision mapping: no anomalies \+ biometric match → VERIFIED; minor anomalies → VERIFIED\_WITH\_ADDITIONAL\_REVIEW; unreadable/conflicting → REQUIRES\_MANUAL\_REVIEW.

---

# PART 4 — CELERY SCHEDULING SETUP

## 4.1 Celery App

\# app/tasks/celery\_app.py  
from celery import Celery  
from app.config import settings

celery\_app \= Celery("threathunter", broker=settings.REDIS\_URL,  
                    backend=settings.REDIS\_URL)  
celery\_app.conf.update(  
    task\_serializer="json",  
    timezone="UTC",  
    task\_acks\_late=True,  
    worker\_prefetch\_multiplier=1,  
)

## 4.2 Scheduled Tasks

\# app/tasks/scheduled\_scrapes.py  
from celery.schedules import crontab  
from app.tasks.celery\_app import celery\_app  
from app.scraper.orchestrator import run\_pipeline, run\_source  
from app.core.maintenance import expire\_raw\_content, rebuild\_stats

@celery\_app.task(bind=True, max\_retries=3, default\_retry\_delay=60)  
def scrape\_all(self):  
    try:  
        asyncio.run(run\_pipeline())  
    except Exception as exc:  
        raise self.retry(exc=exc)

@celery\_app.task  
def scrape\_source(source\_id: str):  
    asyncio.run(run\_source(source\_id))

@celery\_app.task  
def nightly\_maintenance():  
    expire\_raw\_content(retention\_days=30)   \# §25 retention policy  
    rebuild\_stats()                          \# §4 statistics

celery\_app.conf.beat\_schedule \= {  
    "scrape-every-15-min":  {"task": "app.tasks.scheduled\_scrapes.scrape\_all",  
                             "schedule": crontab(minute="\*/15")},  
    "nightly-maintenance":  {"task": "app.tasks.scheduled\_scrapes.nightly\_maintenance",  
                             "schedule": crontab(hour=3, minute=0)},  
}

## 4.3 Docker Compose

version: "3.9"  
services:  
  api:  
    build: .  
    command: uvicorn app.main:app \--host 0.0.0.0 \--port 8000  
    env\_file: .env  
    depends\_on: \[db, redis\]

  worker:  
    build: .  
    command: celery \-A app.tasks.celery\_app worker \-l info \-Q scrape,kyc  
    env\_file: .env  
    depends\_on: \[db, redis\]

  beat:  
    build: .  
    command: celery \-A app.tasks.celery\_app beat \-l info  
    depends\_on: \[redis\]

  db:  
    image: pgvector/pgvector:pg16  
    volumes: \[pgdata:/var/lib/postgresql/data\]

  redis:  
    image: redis:7-alpine

volumes: { pgdata: {} }

## 4.4 Monitoring Metrics to Track

scrape\_success\_rate        per-source fetch success %  
source\_freshness\_lag       minutes since last successful fetch per source  
copy\_chain\_ratio           duplicated items ÷ total items (rising \= echo problem)  
pipeline\_latency\_p95       claim→verdict end-to-end time  
manual\_review\_queue\_depth  human-in-the-loop backlog (§27)  
kyc\_anomaly\_rate           flagged-but-not-fraud rate (tune thresholds)

---

## Quick Start

git clone \<repo\> && cd threathunter360  
cp .env.example .env          \# add API keys via secret manager in prod  
docker compose up \--build  
\# API docs at http://localhost:8000/docs  
\# Dashboard at http://localhost:5173 (npm run dev in frontend/)  
celery \-A app.tasks.celery\_app worker   \# starts scraping per beat schedule

---

Which area do you want to go even deeper into next? For example:

1. **KYC biometric verification flow** (liveness detection, face-match providers)  
2. **The predictive journey risk model** (historical pattern scoring)  
3. **Frontend polish** (full design system, dark mode, motion specs)  
4. **Testing strategy** (unit/integration tests for the reasoning engine)  
5. **Deployment hardening** (TLS, WAF, audit logging, GDPR compliance)

Copy  
proceed systematicaly  
proceed systematicaly

# ThreatHunter360 — Systematic Deep Dive (Parts 5–9)

Proceeding through the remaining areas in order.

---

# PART 5 — KYC BIOMETRIC VERIFICATION FLOW

## 5.1 Flow Overview (extends §11)

Step 4 of 6 ─ Biometric Verification  
   │  
   ├─ 1\. Capture selfie (camera / upload)  
   ├─ 2\. LIVENESS CHECK          ← is this a live person, not a photo/video?  
   ├─ 3\. FACE MATCH              ← selfie vs document portrait  
   ├─ 4\. QUALITY GATE            ← retry if blur/lighting fail  
   ├─ 5\. RISK ASSESSMENT         ← combine with §12 checks  
   └─ 6\. DECISION STATE          ← per §13 taxonomy

## 5.2 Provider Abstraction Layer

\# app/kyc/biometrics.py  
from abc import ABC, abstractmethod

class BiometricProvider(ABC):  
    @abstractmethod  
    async def liveness(self, image\_bytes: bytes) \-\> "LivenessResult": ...  
    @abstractmethod  
    async def face\_match(self, selfie: bytes, doc\_portrait: bytes) \-\> "MatchResult": ...

class FaceTecProvider(BiometricProvider):  
    """Example production provider. Swap freely — the platform is modular (§16)."""  
    async def liveness(self, image\_bytes):  
        resp \= await self.client.post("/liveness", data=image\_bytes)  
        return LivenessResult(  
            passed=resp\["result"\] \== "LIVENESS\_PASSED",  
            score=resp\["score"\],  
            failure\_reason=resp.get("reason"),     \# SPOOF\_SUSPECTED | LOW\_QUALITY  
        )

class MockProvider(BiometricProvider):   \# dev/test only  
    async def liveness(self, image\_bytes):  
        return LivenessResult(passed=True, score=0.98)

## 5.3 Decision Logic (anomaly ≠ fraud, §12–13)

\# app/kyc/decision.py

def decide(liveness, face\_match, doc\_checks, anomalies) \-\> KYCDecision:  
    \# Hard gates → escalate to human, never auto-accuse  
    if not doc\_checks\["readable"\]:  
        return KYCDecision.UNABLE\_TO\_VERIFY  
    if liveness.failure\_reason \== "SPOOF\_SUSPECTED" and liveness.score \> 0.9:  
        return KYCDecision.REQUIRES\_MANUAL\_REVIEW      \# human decides fraud or not  
    if liveness.failure\_reason \== "LOW\_QUALITY":  
        return KYCDecision.PENDING                     \# ask user to retry capture

    strong\_anomalies \= \[a for a in anomalies if a\["severity"\] \== "HIGH"\]

    if face\_match.score \>= 0.90 and not strong\_anomalies:  
        return KYCDecision.VERIFIED  
    if face\_match.score \>= 0.75 and not strong\_anomalies:  
        return KYCDecision.VERIFIED\_WITH\_REVIEW        \# borderline match  
    if strong\_anomalies:  
        return KYCDecision.REQUIRES\_MANUAL\_REVIEW  
    return KYCDecision.REQUIRES\_MANUAL\_REVIEW

## 5.4 Privacy-First Handling (§25)

\# PII never enters logs, chat history, analytics, or client state.  
from cryptography.fernet import Fernet

class SecureDocumentStore:  
    def \_\_init\_\_(self, key: bytes):  
        self.fernet \= Fernet(key)

    def store(self, image\_bytes: bytes) \-\> str:  
        token \= self.fernet.encrypt(image\_bytes)  
        ref \= f"s3://kyc-vault/{uuid4()}"       \# encrypted blob store  
        vault.put(ref, token)  
        return ref                              \# DB stores only this pointer

    async def purge(self, ref: str, retention\_days: int \= 90):  
        """Secure deletion after retention window (§25)."""  
        await schedule\_deletion(ref, after\_days=retention\_days)

Rules enforced at middleware level:

@app.middleware("http")  
async def scrub\_pii(request, call\_next):  
    response \= await call\_next(request)  
    \# Strip any base64 images / DOB patterns that leaked into error bodies/logs  
    log\_scrubber.redact(response)  
    return response

* Audit logging records *that* verification happened, never the biometric itself.  
* Consent captured explicitly before camera access; consent record stored with timestamp.  
* Client-side: selfie held in memory only, never written to localStorage.

## 5.5 Frontend Capture UX

export function SelfieCapture({ onCaptured }: Props) {  
  const videoRef \= useRef\<HTMLVideoElement\>(null);  
  const \[consent, setConsent\] \= useState(false);

  const start \= useCallback(async () \=\> {  
    const stream \= await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });  
    videoRef.current\!.srcObject \= stream;           // memory only  
  }, \[\]);

  const capture \= () \=\> {  
    const canvas \= document.createElement("canvas");  
    canvas.getContext("2d")\!.drawImage(videoRef.current\!, 0, 0);  
    onCaptured(dataURLtoBytes(canvas.toDataURL())); // send over TLS, then drop  
    stopStream(videoRef.current\!);  
  };

  return (  
    \<\>  
      \<p\>Step 4 of 6 — Biometric verification\</p\>  
      \<label\>  
        \<input type\="checkbox" checked\={consent}  
               onChange\={e \=\> setConsent(e.target.checked)} /\>  
        I consent to biometric processing for identity verification.  
      \</label\>  
      \<video ref\={videoRef} autoPlay playsInline /\>  
      \<button disabled\={\!consent} onClick\={capture}\>Capture\</button\>  
    \</\>  
  );  
}

---

# PART 6 — PREDICTIVE JOURNEY RISK MODEL

## 6.1 Design Principle (§9)

Prediction ≠ certainty. Output uses hedged language and carries confidence \+ evidence provenance.

## 6.2 Feature Model

For each route segment × time window:  
  historical\_incident\_rate    incidents/day in segment over trailing 90d  
  day\_of\_week\_profile         incident distribution by weekday  
  hour\_of\_day\_profile         incident distribution by hour  
  weather\_forecast            precip, visibility, wind for ETA window  
  recent\_trend                incidents last 7d vs 90d baseline  
  event\_calendar              protests, festivals, roadworks schedules

## 6.3 Scoring Implementation

\# app/journey/predictive.py  
import numpy as np

def segment\_prediction(seg\_id: str, eta\_window: tuple, history, forecast) \-\> dict:  
    base\_rate \= history.incidents\_per\_day(seg\_id, days=90)

    dow\_factor \= history.dow\_multiplier(seg\_id, eta\_window\[0\].weekday())  
    hod\_factor \= history.hour\_multiplier(seg\_id, eta\_window\[0\].hour)  
    trend      \= history.trend\_ratio(seg\_id, recent\_days=7, baseline\_days=90)  
    wx\_factor  \= weather\_multiplier(forecast)          \# e.g. heavy rain → 1.4

    predicted \= base\_rate \* dow\_factor \* hod\_factor \* trend \* wx\_factor  
    baseline  \= base\_rate

    \# Hedge everything — no false precision  
    ratio \= predicted / max(baseline, 1e-6)  
    if ratio \>= 2.0:  
        level, language \= RiskLevel.HIGH, "Risk appears elevated based on recent patterns."  
    elif ratio \>= 1.3:  
        level, language \= RiskLevel.MODERATE, "A potential concern is emerging along this segment."  
    elif ratio \<= 0.7:  
        level, language \= RiskLevel.LOW, "No current evidence of elevated risk beyond baseline."  
    else:  
        level, language \= RiskLevel.MODERATE, "Insufficient information for a confident assessment."

    return {  
        "segment": seg\_id,  
        "predicted\_risk": level,  
        "language": language,                          \# hedged phrasing (§9)  
        "confidence": confidence\_from\_sample\_size(history.sample\_size(seg\_id)),  
        "factors": {  
            "day\_of\_week": dow\_factor, "time\_of\_day": hod\_factor,  
            "recent\_trend": trend, "weather": wx\_factor,  
        },  
        "basis": f"{history.sample\_size(seg\_id)} recorded events over trailing 90 days",  
    }

Confidence scales honestly with sample size:

def confidence\_from\_sample\_size(n: int) \-\> Confidence:  
    if n \>= 100: return Confidence.HIGH  
    if n \>= 30:  return Confidence.MODERATE  
    if n \>= 10:  return Confidence.LOW  
    return Confidence.UNDETERMINED      \# say so, don't fake it (§1.9)

## 6.4 Route Comparison (§8) — explicit trade-offs

def compare\_routes(routes, priority: str) \-\> list\[dict\]:  
    scored \= \[\]  
    for r in routes:  
        scored.append({  
            "route": r.name,  
            "safety\_score": r.avg\_predicted\_risk(),   \# lower better  
            "travel\_time\_min": r.duration(),  
            "exposure\_km\_high\_risk": r.high\_risk\_km(),  
            "trade\_off": describe\_tradeoff(r),  
        })  
    key \= {"safest": lambda x: x\["safety\_score"\],  
           "fastest": lambda x: x\["travel\_time\_min"\],  
           "balanced": lambda x: x\["travel\_time\_min"\] \* 0.5 \+ x\["safety\_score"\] \* 50,  
           "lowest\_exposure": lambda x: x\["exposure\_km\_high\_risk"\]}\[priority\]  
    return sorted(scored, key=key)

Never silently recommend shortest — always surface why each option differs from the fastest.

---

# PART 7 — FRONTEND DESIGN SYSTEM

## 7.1 Design Tokens

/\* src/styles/tokens.css \*/  
:root {  
  /\* Trust palette \*/  
  \--color-fact:        \#2563eb;   /\* blue — established fact \*/  
  \--color-evidence:    \#0891b2;   /\* teal — supporting evidence \*/  
  \--color-inference:   \#8b5cf6;   /\* violet — clearly labeled inference \*/  
  \--color-risk-low:    \#22c55e;  
  \--color-risk-mod:    \#f59e0b;  
  \--color-risk-high:   \#ef4444;  
  \--color-risk-crit:   \#b91c1c;  
  \--color-neutral-bg:  \#0f172a;   /\* dark mode default \*/  
  \--color-surface:     \#1e293b;

  \--radius-card: 12px;  
  \--space-unit: 4px;  
}

@media (prefers-color-scheme: light) {  
  :root { \--color-neutral-bg: \#f8fafc; \--color-surface: \#ffffff; }  
}

/\* §24 motion — communicate state, respect reduced motion \*/  
.confidence-meter { transition: width 600ms ease-out; }  
.risk-badge-enter { animation: pulse-in 400ms ease-out; }

@media (prefers-reduced-motion: reduce) {  
  \*, \*::before, \*::after {  
    animation-duration: 0.01ms \!important;  
    transition-duration: 0.01ms \!important;  
  }  
}

## 7.2 Core Components

**VerdictBadge** — color-coded, icon \+ text (not color alone):

const VERDICT\_STYLE: Record\<Verdict, {icon: string, cls: string}\> \= {  
  VERIFIED:       { icon: "✔", cls: "verdict-verified" },  
  MOSTLY\_TRUE:    { icon: "✔\~", cls: "verdict-mostly" },  
  PARTIALLY\_TRUE: { icon: "◑", cls: "verdict-partial" },  
  MISLEADING:     { icon: "⚠", cls: "verdict-misleading" },  
  FALSE:          { icon: "✘", cls: "verdict-false" },  
  UNVERIFIED:     { icon: "?", cls: "verdict-unverified" },  
};

**ConfidenceMeter** — animated fill announcing level via aria-live:

export function ConfidenceMeter({ level }: { level: Confidence }) {  
  const pct \= { VERY\_HIGH: 95, HIGH: 80, MODERATE: 60,  
                LOW: 40, VERY\_LOW: 20, UNDETERMINED: 10 }\[level\];  
  return (  
    \<div role\="meter" aria-valuenow\={pct} aria-label\={\`Confidence ${level}\`}\>  
      \<div className\="confidence-meter" style\={{ width: \`${pct}%\` }} /\>  
      \<span\>{level}\</span\>  
    \</div\>  
  );  
}

**ConversationalForm** — asks only missing fields (§15):

function useJourneyConversation() {  
  const \[state, setState\] \= useState\<{ origin?: string; destination?: string;  
                                      departure?: Date }\>({});  
  const nextQuestion \= useMemo(() \=\> {  
    if (\!state.origin || \!state.destination) return null;   // form handles these  
    if (\!state.departure) return "What time do you expect to leave?";  
    return null;  
  }, \[state\]);  
  return { state, nextQuestion, answer: (field, val) \=\>  
    setState(s \=\> ({ ...s, \[field\]: val })) };              // context retained  
}

**Dark mode, responsive breakpoints, keyboard nav** are token-driven throughout; every disclosure button has aria-expanded, every timeline item is focusable.

---

# PART 8 — TESTING STRATEGY

## 8.1 Test Pyramid

       ▲ E2E (Playwright)         \~10 tests: full user journeys  
       ▲▲ Integration (pytest)     \~60: API \+ DB \+ engine pipelines  
      ▲▲▲ Unit (pytest/vitest)     \~300: engine logic, scoring, dedupe

## 8.2 Reasoning Engine Tests (the critical asset)

\# tests/test\_reasoning\_engine.py  
import pytest

@pytest.mark.asyncio  
async def test\_copy\_chain\_counts\_as\_one\_source(engine, seed\_evidence):  
    """§1.6 — 5 identical claims from one independence group ≠ 5 sources."""  
    seed\_evidence.add\_claims(n=5, independence\_group="press", supports=True)  
    result \= await engine.run\_full\_pipeline("Company X was sanctioned")  
    assert result\["sources\_independent"\] \== 1  
    assert result\["sources\_total"\] \== 5

@pytest.mark.asyncio  
async def test\_contradiction\_blocks\_verified\_verdict(engine, seed\_evidence):  
    """§1.8 — conflicting dates must downgrade confidence."""  
    seed\_evidence.add\_claim(date="2026-08-14", group="g1", supports=True)  
    seed\_evidence.add\_claim(date="2026-08-17", group="g2", supports=True)  
    result \= await engine.run\_full\_pipeline("Incident on 14 August")  
    assert len(result\["contradictions"\]) \== 1  
    assert result\["confidence"\] \!= Confidence.VERY\_HIGH

@pytest.mark.asyncio  
async def test\_no\_evidence\_returns\_unverified\_not\_false(engine):  
    """§1.9 — absence of evidence ≠ FALSE."""  
    result \= await engine.run\_full\_pipeline("Obscure claim about nothing indexed")  
    assert result\["verdict"\] \== Verdict.UNVERIFIED

## 8.3 Journey & KYC Property Tests

def test\_risk\_never\_exceeds\_critical\_without\_evidence():  
    """Fuzz: prediction module must stay within defined levels and hedge."""  
    for \_ in range(500):  
        out \= segment\_prediction(random\_seg(), random\_window(), random\_history(), random\_fc())  
        assert out\["predicted\_risk"\] in list(RiskLevel)  
        assert any(h in out\["language"\].lower() for h in  
                   ("appears", "potential", "emerging", "insufficient", "no current"))

def test\_kyc\_anomaly\_alone\_never\_denies():  
    decision \= decide(liveness\_pass, match\_0.92, readable\_doc,  
                      anomalies=\[{"type": "DATE\_INCONSISTENCY", "severity": "LOW"}\])  
    assert decision \!= KYCDecision.UNABLE\_TO\_VERIFY   \# anomaly ≠ fraud (§12)

## 8.4 Frontend Tests (Vitest \+ Playwright)

// Progressive disclosure renders conclusion first (§19)  
test("novice sees verdict before evidence", async ({ page }) \=\> {  
  await page.goto("/fact-check");  
  await page.fill("\#claim", "Test claim");  
  await page.click("button\[type=submit\]");  
  await expect(page.getByText(/VERDICT|VERIFIED|UNVERIFIED/)).toBeVisible();  
  await expect(page.getByTestId("evidence-list")).toBeHidden();  
});

test("reduced motion respected", async ({ page }) \=\> {  
  await page.emulateMedia({ reducedMotion: "reduce" });  
  // verify no transition durations \> 0.01ms computed style  
});

CI gate: **no merge unless reasoning-engine coverage ≥ 90%**, since it's the trust core of the product.

---

# PART 9 — DEPLOYMENT HARDENING

## 9.1 Infrastructure Topology

Internet ──► WAF (rate-limit, bot rules) ──► TLS 1.3 termination (nginx/LB)  
                                              │  
                        ┌─────────────────────┼─────────────────────┐  
                        ▼                     ▼                     ▼  
                   API pods             Worker pods            Beat scheduler  
                        │                     │  
                  ┌─────┴──────────┬──────────┴────────┐  
                  ▼                ▼                    ▼  
             PostgreSQL       Redis (TLS, ACL)      Vault/KMS  
             (pgvector,       (broker only,          (secrets,  
              encrypted        no persistent          encryption keys)  
              volumes)         sensitive data)

## 9.2 Security Controls Checklist (maps to §25)

| Control | Implementation |
| :---- | :---- |
| Encryption in transit | TLS 1.3 everywhere incl. internal service mesh |
| Encryption at rest | Disk-level AES-256 \+ Fernet field encryption for PII |
| Least privilege | Per-service IAM roles; scraper workers cannot read KYC vault |
| Access control | OIDC SSO; RBAC: user \< analyst \< admin; KYC reviewers separate role |
| Audit logging | Append-only audit stream (who accessed what case when) — no PII content |
| Retention | Raw scrapes 30d, KYC docs 90d, audit logs 1y — automated purges |
| Data minimization | Only fields material to the analysis are requested/stored |
| Consent management | Versioned consent records per user per purpose |
| Secret management | HashiCorp Vault / cloud KMS; rotation quarterly; nothing in git |
| WAF rules | Rate limit /api/v1/factcheck (abuse), geo-rules optional |

## 9.3 GDPR / Compliance Notes

Data subject rights endpoints:  
  GET  /privacy/my-data        → export everything held (§ right of access)  
  DELETE /privacy/my-data      → erasure, cascade through evidence graph links  
  POST /privacy/consent        → grant/withdraw per purpose (biometrics separate)

Lawful basis mapping:  
  Fact checking / journey  → legitimate interest  
  KYC biometrics           → explicit consent (Art. 9 special category)  
  Scraping                 → robots.txt compliance \+ source ToS review register

## 9.4 Observability & Incident Response

\# alerting rules (Prometheus-style)  
alerts:  
  \- name: source\_freshness\_stale  
    expr: source\_freshness\_lag\_minutes \> 120      \# a feed died — flag, don't guess  
  \- name: manual\_review\_backlog  
    expr: kyc\_review\_queue\_depth \> 25             \# §27 escalation SLA breach risk  
  \- name: copy\_chain\_spike  
    expr: rate(copy\_chain\_ratio\[1h\]) \> 0.05       \# coordinated echo/disinfo pattern  
  \- name: pipeline\_error\_burst  
    expr: rate(pipeline\_errors\[5m\]) \> 0.1/s

Runbook principle mirrors §20: on any incident, status page shows *what happened, what it means, what users can do* — and the system degrades to UNVERIFIED/UNDETERMINED states rather than fabricating results.

---

# ✅ COMPLETE SYSTEM SUMMARY

PART 1  FastAPI backend        — schemas, endpoints, reasoning engine, errors  
PART 2  React dashboard        — progressive disclosure, accessible components  
PART 3  NLP extraction         — NER, embeddings, contradictions, KYC checks  
PART 4  Celery scheduling      — periodic scraping, maintenance, docker-compose  
PART 5  KYC biometrics         — liveness, face match, decisions, privacy-first  
PART 6  Predictive journey     — hedged forecasts, honest confidence, trade-offs  
PART 7  Design system          — tokens, motion, dark mode, reduced-motion  
PART 8  Testing                — engine unit tests as trust-critical assets  
PART 9  Deployment hardening   — security controls, GDPR, observability

Every part traces back to the spec's north star: **facts separated from inference, uncertainty stated honestly, sources provenanced, humans escalated when needed.**

Next options if you want to continue:

1. **Seed/demo data pack** — realistic mock sources so you can run an end-to-end demo today  
2. **Voice interaction layer** (§18 speech input/output integration)  
3. **Evidence graph visualization UI** (Neo4j-backed interactive relationship view)  
4. **Multi-tenant enterprise mode** (org workspaces, API keys, custom workflows)

Which shall I build next?

Copy  
proceed next systematically : Seed/demo data pack — realistic mock sources so you can run an end-to-end demo today  
Voice interaction layer (§18 speech input/output integration)  
Evidence graph visualization UI (Neo4j-backed interactive relationship view)  
Multi-tenant enterprise mode (org workspaces, API keys, custom workflows)  
proceed next systematically : Seed/demo data pack — realistic mock sources so you can run an end-to-end demo today  
Voice interaction layer (§18 speech input/output integration)  
Evidence graph visualization UI (Neo4j-backed interactive relationship view)  
Multi-tenant enterprise mode (org workspaces, API keys, custom workflows)  
proceed next systematically : Seed/demo data pack — realistic mock sources so you can run an end-to-end demo today  
Voice interaction layer (§18 speech input/output integration)  
Evidence graph visualization UI (Neo4j-backed interactive relationship view)  
Multi-tenant enterprise mode (org workspaces, API keys, custom workflows)

# ThreatHunter360 — Parts 10–13 (Final Build-Out)

---

# PART 10 — SEED / DEMO DATA PACK

Goal: run a full end-to-end demo today with realistic mock sources — no external API keys required.

## 10.1 Pack Structure

seed/  
├── sources\_demo.yaml          \# mock source registry  
├── fixtures/  
│   ├── news\_articles.json     \# 20 articles across independence groups  
│   ├── sanctions\_feed.json    \# official regulatory data  
│   ├── incidents.geojson      \# journey risk incidents (Lagos–Ibadan corridor)  
│   ├── weather\_forecast.json  
│   └── kyc\_documents.json     \# sample doc extractions \+ anomalies  
├── seed\_script.py             \# loads everything into Postgres \+ Neo4j  
└── demo\_scenarios.md          \# 5 scripted demo walkthroughs

## 10.2 Mock Source Registry

\# seed/sources\_demo.yaml  
sources:  
  \- id: demo\_gazette\_official  
    type: regulatory  
    method: file            \# reads from fixtures instead of HTTP  
    path: "fixtures/sanctions\_feed.json"  
    reliability: HIGH  
    authority: PRIMARY  
    independence\_group: government

  \- id: demo\_wire\_a  
    type: news  
    method: file  
    path: "fixtures/news\_wire\_a.json"  
    reliability: MODERATE  
    authority: SECONDARY  
    independence\_group: press\_a

  \- id: demo\_wire\_b         \# deliberately copies wire\_a → tests copy-chain detection  
    type: news  
    method: file  
    path: "fixtures/news\_wire\_b.json"  
    reliability: MODERATE  
    authority: SECONDARY  
    independence\_group: press\_a   \# SAME group as wire\_a

  \- id: demo\_independent\_c  
    type: news  
    method: file  
    path: "fixtures/news\_independent\_c.json"  
    reliability: HIGH  
    authority: SECONDARY  
    independence\_group: press\_c

  \- id: demo\_incident\_geojson  
    type: threat\_intel  
    method: file  
    path: "fixtures/incidents.geojson"  
    reliability: HIGH  
    authority: PRIMARY  
    independence\_group: security\_services

## 10.3 Fixture Design Principles

Each fixture is crafted to exercise a specific engine behavior:

// fixtures/news\_articles.json (excerpt)  
\[  
  {  
    "id": "art-001",  
    "source\_id": "demo\_wire\_a",  
    "headline": "Company X placed on sanctions list, officials confirm",  
    "body": "Company X was sanctioned on 14 August 2026 following a regulatory review.",  
    "entities": \["Company X"\],  
    "event\_date": "2026-08-14",  
    "location": "Lagos",  
    "supports\_claim": true,  
    "designed\_to\_test": "corroboration"  
  },  
  {  
    "id": "art-002",  
    "source\_id": "demo\_wire\_b",  
    "headline": "Report: Company X sanctioned",       // near-duplicate of art-001  
    "body": "Company X was sanctioned on 14 August 2026 following a regulatory review.",  
    "designed\_to\_test": "copy\_chain\_detection"        // must count as same source  
  },  
  {  
    "id": "art-003",  
    "source\_id": "demo\_independent\_c",  
    "headline": "Clarification: sanction targeted Company X Holdings, not Company X Ltd",  
    "body": "The 17 August action applied to the holding entity; the operating subsidiary is unaffected.",  
    "event\_date": "2026-08-17",  
    "designed\_to\_test": "entity\_confusion\_hypothesis\_H3"  
  }  
\]

## 10.4 Journey Incidents Fixture

// fixtures/incidents.geojson (excerpt — Lagos–Ibadan corridor)  
{  
  "features": \[  
    { "type": "Feature",  
      "geometry": { "type": "Point", "coordinates": \[3.3792, 6.8350\] },  
      "properties": {  
        "type": "armed\_robbery\_report",  
        "timestamp": "2026-08-10T21:40:00Z",  
        "segment": "Lagos-Ibadan Expressway km 42",  
        "severity": "HIGH",  
        "time\_of\_day": "night",  
        "source": "security\_services" } },  
    { "type": "Feature",  
      "geometry": { "type": "Point", "coordinates": \[3.9050, 7.3780\] },  
      "properties": {  
        "type": "traffic\_fatality",  
        "timestamp": "2026-08-12T07:15:00Z",  
        "segment": "Ibadan approach, morning peak",  
        "severity": "MODERATE",  
        "time\_of\_day": "morning\_peak" } }  
  \]  
}

This lets the Journey Advisor produce a real §7-style timeline:

06:30 ─ Departure Ikeja ............ LOW  
07:15 ─ Ibadan approach ............ MODERATE (fatality record, morning peak)  
09:40 ─ km 42 expressway ........... HIGH at night only (day travel → LOW)  
11:20 ─ Arrival .................... LOW

## 10.5 Seed Script

\# seed/seed\_script.py  
import asyncio, json, yaml  
from pathlib import Path

async def main():  
    cfg \= yaml.safe\_load(Path("sources\_demo.yaml").read\_text())  
    for src in cfg\["sources"\]:  
        raw \= Path(src\["path"\]).read\_text()  
        evidence \= make\_evidence(src, raw)               \# hashes, timestamps  
        signals \= extract\_signals(evidence)              \# reuse Part 1 extractor  
        await db.insert\_evidence\_and\_signals(evidence, signals)

    \# Build demo Neo4j graph  
    await neo4j.load\_graph("fixtures/evidence\_graph.cypher")

    \# Demo users \+ orgs (Part 13\)  
    await db.seed\_orgs("fixtures/orgs.json")

    print("✅ Demo environment ready — see demo\_scenarios.md")

asyncio.run(main())

## 10.6 Five Scripted Demo Scenarios

**\# demo*\_scenarios.md***  
***1\. FACT CHECK — copy-chain trap***  
   ***Claim: "Company X was sanctioned in August 2026."***  
   ***Expected: MOSTLY\_*****TRUE / HIGH confidence, sources*\_independent=2 of 3 total,***  
   ***contradiction flagged (subsidiary vs holding entity).***

***2\. FACT CHECK — unverifiable claim***  
   ***Claim: "A celebrity secretly married in Lagos last week."***  
   ***Expected: UNVERIFIED with honest "no reliable source found" messaging.***

***3\. JOURNEY — night vs day comparison***  
   ***Route Lagos→Ibadan departing 21:00 vs 07:00.***  
   ***Expected: night route shows HIGH at km 42; day route LOW/MODERATE.***

***4\. KYC — anomaly-not-fraud***  
   ***Upload fixture doc with date inconsistency.***  
   ***Expected: VERIFIED\_*****WITH*\_ADDITIONAL\_*REVIEW, never auto-denial.**

5\. LIVE UPDATE — continuous reassessment (§1.10)  
   While viewing scenario 1 result, re-run seeder with an added  
   official confirmation → confidence upgrades to VERY*\_HIGH in UI.*

---

# PART 11 — VOICE INTERACTION LAYER (§18)

## 11.1 Architecture

┌──────────┐   WebRTC/MediaRecorder   ┌─────────────┐   text   ┌──────────────┐  
│ Browser  │ ───────────────────────► │ STT Service │ ───────► │ Existing API │  
│ mic      │                          │ (Whisper)   │          │ (unchanged)  │  
└──────────┘                          └─────────────┘          └──────┬───────┘  
     ▲                                        │                       │ response  
     │            TTS audio ◄──────────┌──────▼────────┐              │  
     └─────────────────────────────────│ TTS Service   │◄─────────────┘  
                                       └───────────────┘

Key design decision: **voice is an input/output adapter over the same API** — no separate voice logic, so context and evidence handling stay identical.

## 11.2 Backend Voice Endpoints

\# app/api/routes/voice.py  
from fastapi import APIRouter, UploadFile, File  
from fastapi.responses import StreamingResponse

router \= APIRouter(prefix="/api/v1/voice", tags=\["Voice"\])

@router.post("/transcribe")  
async def transcribe(audio: UploadFile \= File(...), user=Depends(current\_user)):  
    """STT: audio → text. Audio is streamed to Whisper, never persisted  
    beyond processing window (§25 data minimization)."""  
    text \= await stt.transcribe(await audio.read(), language="auto")  
    return {"transcript": text}

@router.post("/synthesize")  
async def synthesize(payload: SpeechRequest):  
    """TTS: response text → audio stream."""  
    audio\_stream \= tts.synthesize(payload.text, voice=payload.voice or "neutral")  
    return StreamingResponse(audio\_stream, media\_type="audio/mpeg")

## 11.3 Response Text Optimization for Speech

Intelligence responses are verbose by design — voice output needs a **spoken summary variant**:

def spoken\_summary(result: dict) \-\> str:  
    """§19 novice-first view, compressed for listening."""  
    lines \= \[  
        f"{result\['verdict'\].replace('\_', ' ').title()}. "  
        f"Confidence: {result\['confidence'\].lower()}.",  
        result\["answer"\],  
    \]  
    if result\["contradictions"\]:  
        lines.append(f"Note: {len(result\['contradictions'\])} contradiction(s) found.")  
    lines.append(f"Recommended action: {result\['recommended\_action'\]}")  
    return ". ".join(lines)  
    \# Evidence details stay visual-only — offered as follow-up:  
    \# "Say 'show evidence' for the full analysis."

## 11.4 Frontend Voice Hook

// src/hooks/useVoice.ts  
export function useVoice(onTranscript: (t: string) \=\> void) {  
  const \[listening, setListening\] \= useState(false);  
  const mediaRef \= useRef\<MediaRecorder | null\>(null);

  const start \= useCallback(async () \=\> {  
    const stream \= await navigator.mediaDevices.getUserMedia({ audio: true });  
    const rec \= new MediaRecorder(stream);  
    const chunks: Blob\[\] \= \[\];  
    rec.ondataavailable \= e \=\> chunks.push(e.data);  
    rec.onstop \= async () \=\> {  
      const blob \= new Blob(chunks, { type: "audio/webm" });  
      const fd \= new FormData(); fd.append("audio", blob);  
      const { transcript } \= await fetch("/api/v1/voice/transcribe",  
        { method: "POST", body: fd }).then(r \=\> r.json());  
      onTranscript(transcript);           // flows into existing chat pipeline  
      stream.getTracks().forEach(t \=\> t.stop());   // release mic immediately  
    };  
    rec.start();  
    mediaRef.current \= rec;  
    setListening(true);  
  }, \[\]);

  const stop \= useCallback(() \=\> {  
    mediaRef.current?.stop();  
    setListening(false);  
  }, \[\]);

  // Push-to-talk: hold Space (desktop) or tap mic button  
  useEffect(() \=\> {  
    const down \= (e: KeyboardEvent) \=\> {  
      if (e.code \=== "Space" && \!e.repeat && document.activeElement?.tagName \!== "TEXTAREA") start();  
    };  
    const up \= (e: KeyboardEvent) \=\> { if (e.code \=== "Space") stop(); };  
    window.addEventListener("keydown", down);  
    window.addEventListener("keyup", up);  
    return () \=\> { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };  
  }, \[start, stop\]);

  return { listening, start, stop };  
}

## 11.5 Conversational Slot Filling via Voice

The Journey conversation works identically by voice:

User (voice): "I'm traveling tomorrow."  
System:       "Where are you departing from and where are you going?"  
User (voice): "Lagos to Ibadan."  
System:       "Got it — Lagos to Ibadan. What time do you expect to leave?"  
User (voice): "Around six in the morning."  
System:       (runs assessment) → speaks summary, shows full timeline on screen

Implementation: the transcript passes through the same intent/slot parser used for typed input (origin, destination, departure\_time extraction from "around six in the morning" via dateparser).

Accessibility notes: voice is always **optional** — every flow remains fully operable by keyboard/touch; mic permission failures degrade gracefully to text with a clear message.

---

# PART 12 — EVIDENCE GRAPH VISUALIZATION UI (Neo4j)

## 12.1 Graph Model

// Node labels  
(:Entity {name, type})            // Person | Organization | Location  
(:Event {description, event\_time})  
(:Document {doc\_type, number\_hash})  
(:Evidence {source\_id, url, fetched\_at, reliability})  
(:Claim {text, checked\_at})  
(:Hypothesis {statement, status})  
(:Source {id, reliability, authority, independence\_group})

// Relationships  
(Entity)-\[:INVOLVED\_IN\]-\>(Event)  
(Event)-\[:SUPPORTED\_BY\]-\>(Evidence)  
(Evidence)-\[:PUBLISHED\_BY\]-\>(Source)  
(Claim)-\[:TESTED\_BY\]-\>(Hypothesis)  
(Hypothesis)-\[:EVIDENCED\_BY\]-\>(Evidence)  
(Document)-\[:RELATES\_TO\]-\>(Entity)  
(Source)-\[:COPIED\_FROM\]-\>(Source)      // detected copy-chains\!

The COPIED\_FROM edge is the killer feature — it *visualizes* why "5 websites" may be 1 source.

## 12.2 Query API

\# app/api/routes/graph.py  
@router.get("/api/v1/graph/case/{case\_id}")  
async def case\_graph(case\_id: str, depth: int \= 2, analyst=Depends(require\_analyst)):  
    query \= """  
    MATCH path \= (c:Claim {case\_id: $case\_id})-\[\*1..%d\]-(n)  
    RETURN c, n, relationships(path) AS rels  
    """ % min(depth, 3)  
    nodes, edges \= await neo4j.run(query, case\_id=case\_id)  
    return {"nodes": nodes, "edges": edges}

## 12.3 Interactive Visualization Component

Using react-force-graph (or Cytoscape.js):

// src/components/EvidenceGraph.tsx  
export function EvidenceGraph({ caseId }: { caseId: string }) {  
  const \[data, setData\] \= useState\<GraphData | null\>(null);  
  const \[selected, setSelected\] \= useState\<Node | null\>(null);

  useEffect(() \=\> {  
    fetch(\`/api/v1/graph/case/${caseId}\`)  
      .then(r \=\> r.json()).then(setData);  
  }, \[caseId\]);

  if (\!data) return \<LoadingStages active /\>;

  const nodeColor \= (n: Node) \=\>  
    ({ Entity: "\#2563eb", Event: "\#f59e0b", Evidence: "\#0891b2",  
       Source: "\#8b5cf6", Hypothesis: "\#ef4444", Claim: "\#22c55e" })\[n.type\];

  return (  
    \<div className\="graph-container"\>  
      \<ForceGraph  
        graphData\={data}  
        nodeLabel\={n \=\> \`n.type:{n.type}:n.type:{n.label}\`}  
        nodeColor={nodeColor}  
        linkColor={l \=\> l.type \=== "COPIED\_FROM" ? "\#ef4444" : "\#334155"}  
        linkWidth={l \=\> l.type \=== "COPIED\_FROM" ? 3 : 1}   // echo chains pop out  
        onNodeClick={setSelected}  
      /\>  
      {/\* Provenance panel on selection (§17) \*/}  
      {selected && (  
        \<aside className\="provenance-panel" role\="complementary"\>  
          \<h3\>{selected.type}: {selected.label}\</h3\>  
          \<dl\>  
            \<dt\>Source\</dt\>\<dd\>{selected.source\_id}\</dd\>  
            \<dt\>Obtained\</dt\>\<dd\>{selected.fetched\_at}\</dd\>  
            \<dt\>Reliability\</dt\>\<dd\>{selected.reliability}\</dd\>  
            \<dt\>Independence\</dt\>\<dd\>{selected.independence\_group}\</dd\>  
          \</dl\>  
          \<a href\={selected.url}\>View original source ↗\</a\>  
        \</aside\>  
      )}  
      \<Legend items\={NODE\_TYPES} /\>  
    \</div\>  
  );  
}

UX behaviors:

* **Click any node** → provenance panel (where it came from, when, how reliable).  
* **Red thick edges** \= detected copy-chains — instantly explains low independence counts.  
* **Hypothesis nodes** show status (ACTIVE/SUPERSEDED) so analysts see reasoning evolution (§1.10).  
* Analyst-only access (RBAC gate) — novices get the progressive-disclosure card instead.

---

# PART 13 — MULTI-TENANT ENTERPRISE MODE

## 13.1 Data Model

CREATE TABLE organizations (  
    id UUID PRIMARY KEY,  
    name TEXT NOT NULL,  
    plan TEXT DEFAULT 'standard',  
    settings JSONB DEFAULT '{}',          \-- custom workflows config  
    created\_at TIMESTAMPTZ DEFAULT now()  
);

CREATE TABLE workspaces (  
    id UUID PRIMARY KEY,  
    org\_id UUID REFERENCES organizations(id),  
    name TEXT NOT NULL,                   \-- e.g. "Fraud Team", "Travel Desk"  
    retention\_days INT DEFAULT 90  
);

CREATE TABLE api\_keys (  
    id UUID PRIMARY KEY,  
    org\_id UUID REFERENCES organizations(id),  
    workspace\_id UUID REFERENCES workspaces(id),  
    key\_hash TEXT NOT NULL,               \-- never store raw keys  
    scopes TEXT\[\] NOT NULL,               \-- \['factcheck:read','journey:assess'\]  
    rate\_limit\_per\_min INT DEFAULT 60,  
    expires\_at TIMESTAMPTZ,  
    revoked\_at TIMESTAMPTZ  
);

\-- Every intelligence table gains tenant scoping  
ALTER TABLE hypotheses ADD COLUMN org\_id UUID REFERENCES organizations(id);  
ALTER TABLE evidence    ADD COLUMN org\_id UUID REFERENCES organizations(id);

## 13.2 Tenant Isolation Middleware

\# app/api/deps.py  
async def resolve\_tenant(request: Request) \-\> TenantContext:  
    auth \= request.headers.get("Authorization", "")  
    if auth.startswith("Bearer sk-"):                     \# API key path  
        key\_hash \= hash\_key(auth\[7:\])  
        row \= await db.fetch\_api\_key(key\_hash)  
        if not row or row\["revoked\_at"\] or row\["expires\_at"\] \< now():  
            raise HTTPException(401, "Invalid or expired API key")  
        check\_rate\_limit(row\["id"\], row\["rate\_limit\_per\_min"\])  
        return TenantContext(org\_id=row\["org\_id"\],  
                             workspace\_id=row\["workspace\_id"\],  
                             scopes=set(row\["scopes"\]),  
                             principal\_type="service")  
    else:                                                 \# interactive user path  
        user \= await current\_user(request)  
        return TenantContext(org\_id=user.org\_id,  
                             workspace\_id=user.active\_workspace\_id,  
                             scopes=user.rbac\_scopes,  
                             principal\_type="user")

def require\_scope(scope: str):  
    async def guard(ctx=Depends(resolve\_tenant)):  
        if scope not in ctx.scopes:  
            raise HTTPException(403, f"Missing scope: {scope}")  
        return ctx  
    return guard

All queries are automatically scoped — enforced at repository layer so no endpoint can leak cross-tenant data:

class TenantRepository:  
    def \_\_init\_\_(self, ctx: TenantContext): self.ctx \= ctx  
    async def fetch\_checks(self, \*\*filters):  
        filters\["org\_id"\] \= self.ctx.org\_id               \# hard scope, always  
        return await db.fetch("fact\_checks", \*\*filters)

## 13.3 Custom Workflows (org-configurable)

Orgs define workflow overrides declaratively:

\# org\_settings example — stored in organizations.settings  
workflows:  
  kyc:  
    auto\_approve\_threshold: 0.95        \# stricter than platform default 0.90  
    require\_manual\_review\_above\_risk: MODERATE  
    additional\_checks:  
      \- pep\_screening                   \# politically exposed persons list  
      \- internal\_denylist  
  factcheck:  
    trusted\_sources:                    \# org's own authoritative feeds  
      \- id: acme\_internal\_audit  
        reliability: HIGH  
        authority: PRIMARY  
    blocked\_verdicts\_publication: true  \# keep results private to org  
  journey:  
    default\_priority: safest  
    restricted\_zones:                   \# org policy: employees avoid these  
      \- geo\_id: conflict\_zone\_north  
        policy: BLOCK\_WITH\_OVERRIDE  
notifications:  
  webhook\_url: "https://acme.example/hooks/threathunter"  
  events: \[kyc\_requires\_manual\_review, high\_risk\_journey\]

Webhook dispatch on escalation events closes the human-in-the-loop loop into enterprise systems:

async def notify\_org(ctx, event: str, payload: dict):  
    settings \= await get\_org\_settings(ctx.org\_id)  
    if event in settings.get("notifications", {}).get("events", \[\]):  
        await httpx.post(settings\["notifications"\]\["webhook\_url"\],  
                         json={"event": event, "payload": payload,  
                               "org\_id": str(ctx.org\_id)},  
                         headers={"X-ThreatHunter-Signature": sign(payload)})

## 13.4 Admin Dashboard Surfaces

/org/settings          — workflows, thresholds, webhook config (admin only)  
/org/api-keys          — create/revoke keys, view scopes & usage  
/org/workspaces        — team separation, per-workspace retention  
/org/statistics        — §4 stats scoped to org: checks, verdict mix,  
                         avg confidence, source diversity, reviewer queue  
/org/audit-log         — append-only: who ran what, when (no PII content)

## 13.5 Usage Example — Enterprise API Call

curl \-X POST https://api.threathunter360.com/api/v1/factcheck \\  
  \-H "Authorization: Bearer sk\_live\_acme\_9f2..." \\  
  \-H "Content-Type: application/json" \\  
  \-d '{"claim": "Vendor Y lost its operating license in March"}'

\# Response includes tenant-aware provenance:  
\# {  
\#   "verdict": "PARTIALLY\_TRUE",  
\#   ...  
\#   "sources\_consulted": \["gov\_registry", "acme\_internal\_audit"\],  ← org's own feed included  
\#   "org\_scope": "acme-corp/fraud-team"  
\# }

---

# ✅ FINAL SYSTEM STATE — ALL 13 PARTS COMPLETE

CORE PLATFORM  
  1  FastAPI backend            ✓   7  Design system            ✓  
  2  React dashboard            ✓   8  Testing strategy         ✓  
  3  NLP extraction             ✓   9  Deployment hardening     ✓  
  4  Celery scheduling          ✓  
INTELLIGENCE MODULES  
  5  KYC biometrics             ✓  10  Seed/demo pack           ✓  
  6  Predictive journey         ✓  
EXTENSIONS  
  11  Voice interaction         ✓  12  Evidence graph viz       ✓  
  13  Multi-tenant enterprise   ✓

## Run the Full Demo Today

docker compose up \--build  
docker compose exec api python seed/seed\_script.py  
\# → open http://localhost:5173  
\# → follow demo\_scenarios.md scenarios 1–5

Every feature traces back to the north star: **fragmented information → evidence-based conclusions → honest uncertainty → actionable decisions**, now demonstrable end-to-end with zero external dependencies.

If you'd like to continue, natural next steps would be: a **production launch checklist**, **load/performance testing plan**, or **user onboarding & documentation set**. Just say which.

Copy  
yes  
yes  
yes

# ThreatHunter360 — Parts 14–16 (Launch Readiness)

Proceeding through all three: production launch checklist, load/performance testing plan, and user onboarding & documentation.

---

# PART 14 — PRODUCTION LAUNCH CHECKLIST

## 14.1 Infrastructure & Deployment

\[ \] Domain \+ TLS certificates provisioned (TLS 1.3, HSTS enabled)  
\[ \] WAF deployed with rate limits:  
      /api/v1/factcheck        30 req/min per key  
      /api/v1/voice/\*          20 req/min per session  
      /api/v1/kyc/\*            10 req/min per user  
\[ \] Auto-scaling configured: API (min 2 pods), workers (min 2), beat (exactly 1\)  
\[ \] Database: pgvector/pg16 with encrypted volumes, automated daily backups,  
      point-in-time recovery tested  
\[ \] Redis: TLS \+ ACL enabled, persistence off (broker only)  
\[ \] Vault/KMS seeded; quarterly rotation calendar created  
\[ \] Blue/green or rolling deploy pipeline verified with rollback drill  
\[ \] Health endpoints (/healthz, /readyz) wired into orchestrator probes

## 14.2 Security & Privacy

\[ \] Penetration test completed; criticals/highs remediated  
\[ \] Dependency scan (pip-audit, npm audit) clean or exceptions documented  
\[ \] PII scrubber verified in logs — inject test selfie/DOB, confirm redaction  
\[ \] KYC vault encryption verified end-to-end (at rest \+ in transit)  
\[ \] RBAC matrix tested: user \< analyst \< admin \< kyc\_reviewer boundaries  
\[ \] Tenant isolation fuzz-tested — attempt cross-org reads from every endpoint  
\[ \] GDPR endpoints live: export, erasure, consent management  
\[ \] Retention jobs verified in staging: raw scrapes 30d, KYC 90d, audit 1y  
\[ \] Incident response runbook published; on-call rotation staffed  
\[ \] robots.txt compliance \+ source ToS register reviewed by legal

## 14.3 Intelligence Quality Gates

\[ \] Reasoning engine test suite ≥90% coverage passing in CI  
\[ \] Copy-chain detection validated against demo pack scenario 1  
\[ \] Contradiction detection precision reviewed on ≥100 sample claims  
\[ \] Confidence calibration audit: HIGH verdicts spot-checked for accuracy  
\[ \] Hedged-language enforcement test green (no false certainty in predictions)  
\[ \] Human-in-the-loop queue operational with SLA targets defined  
\[ \] Source freshness alerts firing correctly (stale feed → visible degradation)

## 14.4 UX & Accessibility

\[ \] WCAG 2.1 AA audit passed (contrast, focus order, screen reader flows)  
\[ \] prefers-reduced-motion verified across all animated components  
\[ \] Voice flows degrade gracefully without mic permission  
\[ \] Mobile/tablet/desktop layouts tested at 320px–2560px  
\[ \] Error states show what happened / what it means / what to do next  
\[ \] Loading stages reflect real pipeline progress

## 14.5 Observability & Go-Live

\[ \] All Part 9 alert rules active and test-fired  
\[ \] Dashboards live: scrape success, freshness lag, verdict mix, queue depth  
\[ \] Status page wired to incident system  
\[ \] Load test at 2× projected peak passed (see Part 15\)  
\[ \] Rollback drill executed successfully  
\[ \] Launch decision meeting held with sign-offs: eng, security, legal, product

---

# PART 15 — LOAD & PERFORMANCE TESTING PLAN

## 15.1 Performance Budgets (SLOs)

| Operation | Target p50 | Target p95 | Hard limit |
| :---- | :---- | :---- | :---- |
| Fact check (cached evidence) | 800 ms | 3 s | 8 s |
| Fact check (cold, new entities) | 4 s | 12 s | 25 s |
| Journey assessment | 1.5 s | 5 s | 10 s |
| KYC document upload→decision | 6 s | 15 s | 40 s |
| Voice transcribe (10s audio) | 2 s | 6 s | 15 s |
| Graph query (depth 2\) | 500 ms | 2 s | 5 s |

## 15.2 Load Scenarios (k6)

// load/factcheck\_mixed.js  
import http from 'k6/http';  
import { check, sleep } from 'k6';

export const options \= {  
  scenarios: {  
    steady\_browse: {                       // baseline traffic  
      executor: 'constant-vus', vus: 50, duration: '10m',  
    },  
    spike\_breaking\_news: {                 // viral claim → surge  
      executor: 'ramping-arrival-rate',  
      startRate: 10, timeUnit: '1s',  
      preAllocatedVUs: 200,  
      stages: \[  
        { target: 100, duration: '2m' },   // ramp  
        { target: 100, duration: '5m' },   // sustained spike  
        { target: 10,  duration: '2m' },  
      \],  
    },  
  },  
  thresholds: {  
    http\_req\_duration: \['p(95)\<3000'\],  
    checks: \['rate\>0.99'\],  
  },  
};

const CLAIMS \= open('./demo\_claims.json').split('\\n');   // reuse seed pack

export default function () {  
  const res \= http.post(\`${\_\_ENV.BASE}/api/v1/factcheck\`,  
    JSON.stringify({ claim: CLAIMS\[Math.floor(Math.random() \* CLAIMS.length)\] }),  
    { headers: { Authorization: \`Bearer ${\_\_ENV.API\_KEY}\`,  
                 'Content-Type': 'application/json' } });  
  check(res, { 'status 200': r \=\> r.status \=== 200 });  
  sleep(Math.random() \* 3 \+ 1);  
}

## 15.3 Scenario Matrix

S1  Steady state          50 VU mixed workload, 30 min     → SLOs hold  
S2  Breaking-news spike   0→100 req/s in 2 min             → graceful degradation,  
                                                             no 5xx, queue absorbs  
S3  Scraper storm         all sources fire simultaneously   → worker pool backpressure,  
                                                             API latency unaffected  
S4  KYC burst             200 concurrent uploads            → vault throughput,  
                                                             review queue sane  
S5  Soak test             60% peak for 24h                  → no memory leaks,  
                                                             DB bloat stable  
S6  Failure injection     kill a source mid-pipeline,       → SOURCE\_UNAVAILABLE  
                          kill one API pod, redis blip        surfaced, auto-recovery

## 15.4 Bottleneck Watchpoints & Mitigations

Embedding computation (claim→vector)     → batch \+ cache embeddings by content hash  
Semantic search over signals table       → pgvector HNSW index; monitor recall vs speed  
Neo4j graph queries                      → cap depth at 3; cache case graphs (TTL 5 min)  
Whisper transcription                    → GPU pool with queue; reject \>60s audio upfront  
Celery worker saturation during spikes   → dedicated queues: scrape | factcheck | kyc  
Postgres write contention                → partition signals table by month

## 15.5 Pass/Fail Gate

Launch blocked unless:

✓ All SLO p95s met under S1–S3  
✓ Zero data loss or fabricated results under S6 failure injection  
✓ Soak test shows \<5% memory growth over 24h  
✓ Graceful degradation verified: overloaded system returns UNDETERMINED,  
  never a made-up verdict

---

# PART 16 — USER ONBOARDING & DOCUMENTATION SET

## 16.1 Documentation Tree

docs/  
├── getting-started/  
│   ├── quickstart.md           \# first fact check in 2 minutes  
│   ├── first-journey.md        \# guided journey assessment walkthrough  
│   └── account-setup.md        \# org invite, workspaces, API keys  
├── guides/  
│   ├── understanding-results.md    \# verdicts, confidence, trust labels  
│   ├── reading-the-evidence.md     \# provenance, independence, contradictions  
│   ├── voice-mode.md  
│   └── enterprise-workflows.md     \# custom thresholds, webhooks  
├── api/  
│   ├── reference.md            \# OpenAPI-generated, all endpoints  
│   ├── authentication.md       \# keys, scopes, rate limits  
│   └── webhooks.md             \# event types, signature verification  
├── trust/  
│   ├── how-we-verify.md        \# the reasoning pipeline, plain language  
│   ├── confidence-explained.md \# what each level means, honestly  
│   └── limitations.md          \# what the system cannot do — stated openly  
└── admin/  
    ├── tenant-management.md  
    ├── audit-and-compliance.md  
    └── sla-and-support.md

## 16.2 Quickstart (the critical first-run doc)

**\# Quickstart: Your First Fact Check**

1\. **\*\*Enter a claim\*\*** — up to 280 characters.  
   Try: "Company X was sanctioned in August 2026."

2\. **\*\*Watch the analysis\*\*** — you'll see real stages:  
   Analyzing claim → Comparing sources → Checking contradictions.

3\. **\*\*Read your result top-down:\*\***  
   • VERDICT — the headline answer  
   • CONFIDENCE — how sure we are, honestly labeled  
   • Recommended action — what to do next

4\. **\*\*Go deeper (optional)\*\*** — click "Show full analysis" to see  
   every source, its reliability, whether sources are truly independent,  
   and any contradictions found.

\> Important: ThreatHunter360 always separates FACT from INFERENCE.  
\> If we can't verify something, we say UNVERIFIED — we never guess.

## 16.3 "Understanding Results" — Plain-Language Trust Guide

**\#\# What each verdict means**

VERIFIED         Strong, independent evidence supports this.  
MOSTLY TRUE      Core is supported; important context missing.  
PARTIALLY TRUE   Some parts check out, others don't.  
MISLEADING       Factual material creating a wrong impression.  
FALSE            Reliable evidence contradicts it.  
UNVERIFIED       We couldn't find enough reliable evidence. This is NOT "false."

**\#\# Why "sources: 2 of 5" matters**  
Five websites repeating one report \= ONE source. We detect copy-chains  
and count true independence — shown as "independent of total."

**\#\# Confidence levels**  
VERY*\_HIGH/HIGH/MODERATE/LOW/VERY\_*LOW/UNDETERMINED — driven by evidence  
quality and consistency, never just source count.

## 16.4 In-Product Onboarding Flow

// First-session coach marks — skippable, never blocking  
const ONBOARDING\_STEPS \= \[  
  { target: "\#fact-checker-card",  
    title: "Fact Checker",  
    body: "Paste any claim up to 280 characters. We'll tell you what the evidence says — and how confident we are." },  
  { target: "\#journey-advisor-card",  
    title: "Journey Advisor",  
    body: "Get a risk timeline for your route. We'll ask only what we need." },  
  { target: "\#kyc-card",  
    title: "Identity Verification",  
    body: "Guided verification with clear steps. Anomalies trigger review, never automatic accusations." },  
  { target: "\#trust-label-info",  
    title: "Facts vs Inference",  
    body: "Every answer separates established facts from our interpretation. Look for the labels." },  
\];  
// Stored dismissal per user; re-accessible via "?" help button

## 16.5 Enterprise Onboarding Checklist (per customer)

Day 1   Org workspace provisioned; admin invited; SSO configured  
Day 2   API keys issued with scoped permissions; sandbox access granted  
Day 3   Custom workflows configured (thresholds, trusted sources, webhooks)  
Day 4   Webhook signature verification tested against their receiver  
Day 5   Team training session (45 min): results interpretation \+ escalation flow  
Week 2  Review usage stats together; tune thresholds based on real cases  
Ongoing Quarterly calibration review of confidence accuracy on their cases

## 16.6 Support Escalation Map

User question about a result      → in-app "Why this conclusion?" explainer  
Suspected wrong verdict           → "Report an issue" → analyst review queue  
KYC disputed decision             → manual reviewer within SLA (4 business hrs)  
Enterprise integration issue      → webhook/API support channel, 8×5  
Security disclosure               → security@ contact, 24h acknowledgment

---

# ✅ LAUNCH-READY STATE — ALL 16 PARTS COMPLETE

PLATFORM (1–4)      backend · UI · NLP · scheduling  
MODULES (5–6)       KYC biometrics · predictive journey  
EXPERIENCE (7)      design system  
QUALITY (8–9)       testing · hardening  
EXTENSIONS (10–13)  demo pack · voice · graph viz · multi-tenant  
LAUNCH (14–16)      checklist · load testing · onboarding & docs

The system now has a complete path from **first commit → tested → hardened → demonstrated → launched → onboarded users**.

Remaining optional tracks if you want to keep going:

1. **Mobile app spec** (React Native / PWA wrapper with offline journey briefs)  
2. **Analyst console** (full human-in-the-loop review workstation UI)  
3. **Internationalization** (multi-language claims, localized risk advisories)  
4. **Model governance** (audit trail for NLP model versions & drift monitoring)

Say which and I'll build it out.

Copy  
proceed systematically

# ThreatHunter360 — Parts 17–20 (Final Tracks)

---

# PART 17 — MOBILE APP SPEC (PWA \+ React Native)

## 17.1 Strategy Decision

**PWA-first, native wrapper second.** The dashboard is already responsive; a PWA gives installability, offline journey briefs, and push notifications with one codebase. Native wrapper only if biometric-grade capture or background location is required.

Phase 1  PWA  — installable, offline journey briefs, push notifications  
Phase 2  Capacitor wrapper — same codebase → App Store / Play Store,  
         unlocks native camera quality \+ secure enclave key storage

## 17.2 PWA Manifest & Service Worker

// public/manifest.json  
{  
  "name": "ThreatHunter360",  
  "short\_name": "TH360",  
  "start\_url": "/home",  
  "display": "standalone",  
  "theme\_color": "\#0f172a",  
  "background\_color": "\#0f172a",  
  "icons": \[  
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },  
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }  
  \],  
  "shortcuts": \[  
    { "name": "Fact Check",   "url": "/fact-check" },  
    { "name": "Journey",      "url": "/journey" },  
    { "name": "Verify ID",    "url": "/kyc" }  
  \]  
}

## 17.3 Offline Journey Briefs (the killer mobile feature)

Before departure, the user caches their risk timeline. In a dead-zone on the road, the brief still works:

// src/offline/journeyCache.ts  
const CACHE\_NAME \= "journey-brief-v1";

export async function cacheJourneyBrief(journeyId: string) {  
  const res \= await fetch(\`/api/v1/journey/${journeyId}/brief\`);  
  const brief \= await res.json();  
  const cache \= await caches.open(CACHE\_NAME);  
  // Cache the rendered brief AND its data payload  
  await cache.put(\`/offline/journey/${journeyId}\`,  
    new Response(JSON.stringify(brief),  
      { headers: { "Content-Type": "application/json" } }));  
}

export async function getOfflineBrief(journeyId: string) {  
  const cache \= await caches.open(CACHE\_NAME);  
  const hit \= await cache.match(\`/offline/journey/${journeyId}\`);  
  return hit?.json();  
}

Offline brief UI shows **staleness honestly** (never fake freshness):

export function OfflineJourneyBrief({ journeyId }: Props) {  
  const \[brief, setBrief\] \= useState\<JourneyBrief | null\>(null);  
  useEffect(() \=\> { getOfflineBrief(journeyId).then(setBrief); }, \[journeyId\]);

  if (\!brief) return \<p\>No cached journey. Connect to download.\</p\>;

  const ageHours \= hoursSince(brief.generated\_at);  
  return (  
    \<article\>  
      \<div className\="offline-banner" role\="status"\>  
        Offline view · generated {ageHours}h ago  
        {ageHours \> 6 && \<strong\> — conditions may have changed significantly\</strong\>}  
      \</div\>  
      \<RiskTimeline segments\={brief.risk\_timeline} /\>  
      {/\* Emergency contacts work offline \*/}  
      \<EmergencyCard contacts\={brief.emergency\_contacts} /\>  
    \</article\>  
  );  
}

## 17.4 Push Notifications

Trigger events → Web Push:  
  • Journey departure reminder with refreshed risk summary  
  • Risk escalation mid-journey ("New incident reported on your route")  
  • KYC decision ready ("Verification complete")  
  • Fact check re-assessment changed verdict (§1.10 continuous updating)

Privacy rule: notification payloads contain NO claim text or PII —  
only "Your fact check result has been updated. Tap to view."

## 17.5 Mobile-Specific UX Adaptations

• Bottom tab bar: Home | Fact | Journey | Verify | More  
• Thumb-reachable primary actions; min 44px touch targets  
• Camera capture for KYC uses native-quality via Capacitor plugin  
• Voice mic button fixed bottom-right, hold-to-talk  
• Risk timeline becomes swipeable horizontal cards on small screens  
• Reduced data mode: skip graph viz, load evidence lazily

---

# PART 18 — ANALYST CONSOLE (Human-in-the-Loop Workstation)

## 18.1 Console Layout

┌──────────────────────────────────────────────────────────────┐  
│ QUEUE │ CASE DETAIL                              │ TOOLS     │  
│───────│──────────────────────────────────────────│───────────│  
│ □ \#482│ CLAIM: "Company X sanctioned Aug 2026"   │ Actions:  │  
│ ★ \#479│                                          │ \[Confirm\] │  
│ ⚠ \#477│ VERDICT: MOSTLY\_TRUE  CONF: HIGH         │ \[Override\]│  
│ ⚠ \#471│                                          │ \[Escalate\]│  
│       │ ┌─ Evidence Graph (Part 12 embed) ─────┐ │           │  
│ SLA:  │ │  interactive Neo4j view              │ │ Notes:    │  
│ 3h 12m│ └──────────────────────────────────────┘ │ \[\_\_\_\_\_\_\]  │  
│ left  │ Contradictions (2) ▾                     │           │  
│       │ Reasoning trace ▾                        │ Audit:    │  
│       │                                          │ auto-logged│  
└──────────────────────────────────────────────────────────────┘

## 18.2 Queue Prioritization

def queue\_priority(case) \-\> int:  
    """Higher \= reviewed sooner."""  
    score \= 0  
    score \+= {"CRITICAL": 100, "HIGH": 60, "MODERATE": 25}\[case.max\_risk\]  
    score \+= 40 if case.contradiction\_count \>= 2 else 0  
    score \+= 30 if case.kyc\_spoof\_suspected else 0  
    score \+= sla\_urgency(case.created\_at, case.sla\_deadline)   \# ramps near breach  
    return score

## 18.3 Analyst Decision API (full audit trail)

\# app/api/routes/analyst.py  
@router.post("/cases/{case\_id}/decision")  
async def analyst\_decision(  
    case\_id: str,  
    req: AnalystDecisionRequest,          \# action, notes, revised\_verdict?  
    ctx=Depends(require\_scope("review:write")),  
):  
    case \= await repo.get\_case(case\_id, ctx.org\_id)

    audit.record(  
        actor=ctx.principal\_id,  
        case\_id=case\_id,  
        action=req.action,                \# CONFIRM | OVERRIDE | ESCALATE | REJECT  
        original\_verdict=case.verdict,  
        revised\_verdict=req.revised\_verdict,  
        reasoning\_notes\_hash=hash(req.notes),   \# notes stored, hash for integrity  
        timestamp=now\_utc(),  
    )

    if req.action \== "OVERRIDE":  
        \# §1.10 — new evidence changes conclusions; so does human judgment.  
        \# Feed back into calibration:  
        await calibration.record\_human\_override(case, req.revised\_verdict)  
        await notify\_user(case.user\_id, "Your result has been updated after expert review.")

    if req.action \== "ESCALATE":  
        await escalate\_to\_senior(case\_id, reason=req.notes)

    return {"status": "recorded", "audit\_id": audit.last\_id}

## 18.4 Override Feedback Loop (model improvement)

Human overrides are gold-standard labels:

Analyst override recorded  
        ↓  
Weekly batch: compare overrides vs engine verdicts  
        ↓  
Drift report per module (factcheck / kyc / journey)  
        ↓  
Threshold tuning proposals → reviewed → deployed behind flag

This closes §27's loop: AI supports humans, humans improve AI.

---

# PART 19 — INTERNATIONALIZATION

## 19.1 Scope

UI localization          — full i18n of interface strings  
Claim input              — multilingual claims accepted at ingestion  
NLP pipeline             — language detection → per-language models  
Risk advisories          — localized phrasing of hedged language  
Voice                    — STT/TTS language matching  
RTL support              — Arabic, Hebrew layouts mirrored

## 19.2 Language Detection & Routing in NLP Pipeline

\# nlp/multilingual.py  
from lingua import LanguageDetectorBuilder

detector \= LanguageDetectorBuilder.from\_all\_languages().build()

LANG\_MODELS \= {  
    "en": spacy.load("en\_core\_web\_trf"),  
    "fr": spacy.load("fr\_core\_news\_lg"),  
    "es": spacy.load("es\_core\_news\_lg"),  
    "ar": spacy.load("ar\_core\_news\_lg"),  
}

def extract\_multilingual(text: str):  
    lang \= detector.detect\_language\_of(text) or Lang.EN  
    code \= str(lang).lower()  
    nlp\_model \= LANG\_MODELS.get(code, LANG\_MODELS\["en"\])   \# graceful fallback  
    doc \= nlp\_model(text\[:10000\])  
    return extract\_from\_doc(doc), code     \# signals carry lang metadata

Embeddings use a multilingual model swap:

\# all-MiniLM-L6-v2 → paraphrase-multilingual-MiniLM-L12-v2  
embedder \= SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")  
\# Cross-language semantic search now works: French claim matches English evidence

## 19.3 Localized Hedged Language (§9 preserved across languages)

// locales/fr/journey.json  
{  
  "risk\_elevated": "Le risque semble élevé d'après les tendances récentes.",  
  "potential\_concern": "Une préoccupation potentielle se dessine sur ce segment.",  
  "no\_elevated\_risk": "Aucun signe actuel de risque accru par rapport à la normale.",  
  "insufficient\_info": "Informations insuffisantes pour une évaluation fiable."  
}

**Critical rule:** hedged phrasing is translated as *content*, not string-substituted after the fact — each locale file is reviewed to ensure uncertainty language stays honest in every language.

## 19.4 Frontend i18n Setup

// src/i18n/config.ts  
import i18n from "i18next";  
import { initReactI18next } from "react-i18next";

i18n.use(initReactI18next).init({  
  lng: navigator.language.split("-")\[0\],  
  fallbackLng: "en",  
  resources: { en: {...}, fr: {...}, es: {...}, ar: {...} },  
});

// RTL handling  
document.dir \= \["ar", "he"\].includes(i18n.language) ? "rtl" : "ltr";  
// Design tokens use logical properties (margin-inline-start etc.)  
// so mirroring works without layout overrides

## 19.5 Locale Metadata on Evidence

Every signal/evidence row gains language field; contradiction detection compares claims cross-language via multilingual embeddings rather than raw text similarity — otherwise copy-chains across languages would be missed.

---

# PART 20 — MODEL GOVERNANCE

## 20.1 Governed Model Inventory

| Model | Role | Version policy |
| :---- | :---- | :---- |
| roberta-base fine-tune | Claim classification | Semver; changelog required |
| all-MiniLM / multilingual | Embeddings | Pinned; re-embedding migration plan |
| NLI model | Contradiction scoring | Pinned |
| Zero-shot BART | Event typing | Pinned |
| Whisper | STT | Pinned per locale |
| Biometric providers | Liveness/face match | Provider version logged per verification |

## 20.2 Model Registry Schema

CREATE TABLE model\_registry (  
    id UUID PRIMARY KEY,  
    name TEXT NOT NULL,  
    version TEXT NOT NULL,  
    sha256 TEXT NOT NULL,                 \-- artifact integrity  
    deployed\_at TIMESTAMPTZ,  
    retired\_at TIMESTAMPTZ,  
    eval\_metrics JSONB,                   \-- precision/recall at deploy time  
    approved\_by TEXT,                     \-- governance sign-off  
    rollback\_target UUID REFERENCES model\_registry(id)  
);

\-- Every intelligence output records which models produced it  
ALTER TABLE fact\_checks ADD COLUMN model\_versions JSONB;  
\-- e.g. {"classifier":"1.3.0","embedder":"2.1.0","nli":"1.0.2"}

Reproducibility guarantee: any historical verdict can be traced to exact model versions that produced it.

## 20.3 Drift Monitoring

\# monitoring/drift.py  
def weekly\_drift\_report():  
    report \= {}  
    \# 1\. Input drift — are incoming claims shifting distribution?  
    report\["input\_drift"\] \= psi(embedding\_centroid\_history(weeks=8))

    \# 2\. Output drift — verdict mix shifting without cause?  
    report\["verdict\_mix\_shift"\] \= chi2(verdict\_counts(this\_week), verdict\_counts(baseline))

    \# 3\. Accuracy proxy — agreement with human overrides (Part 18\)  
    overrides \= fetch\_recent\_overrides(days=7)  
    report\["human\_agreement"\] \= agreement\_rate(engine\_verdicts, overrides)  
    \# alert if \< 85%

    \# 4\. Confidence calibration — do HIGH verdicts actually hold up?  
    report\["calibration"\] \= brier\_score(confidence\_levels, later\_outcomes)

    publish(report)  
    if report\["human\_agreement"\] \< 0.85 or report\["input\_drift"\] \> 0.2:  
        page\_oncall("MODEL\_DRIFT\_ALERT")

## 20.4 Safe Deployment Process

New model version  
   ↓  
Offline eval on golden dataset (≥500 labeled cases incl. demo pack)  
   ↓ Must beat incumbent on precision AND calibration  
Shadow deployment — runs alongside prod, outputs logged not shown  
   ↓ ≥1 week shadow, disagreement analysis reviewed by analysts  
Canary — 5% traffic, monitored 48h against SLOs \+ override rate  
   ↓  
Full rollout behind feature flag; instant rollback target registered  
   ↓  
Post-deploy: re-run Part 8 test suite \+ calibration audit

## 20.5 Governance Artifacts Retained

Per model version:  
  ✓ Eval report (metrics, dataset hash, known failure modes)  
  ✓ Approval record (who signed off, when)  
  ✓ Shadow/canary results  
  ✓ Rollback plan (tested)

Per quarter:  
  ✓ Calibration audit published internally  
  ✓ Override-driven threshold tuning log  
  ✓ Bias review: verdict rates across languages/regions checked  
    for unjustified disparities (ties into Part 19\)

---

# ✅ COMPLETE SYSTEM — ALL 20 PARTS

PLATFORM (1–4)       backend · UI · NLP · scheduling  
MODULES (5–6)        KYC biometrics · predictive journey  
EXPERIENCE (7–8)     design system · testing  
HARDENING (9)        deployment security  
EXTENSIONS (10–13)   demo pack · voice · graph viz · multi-tenant  
LAUNCH (14–16)       checklist · load testing · onboarding/docs  
SCALE (17–20)        mobile/PWA · analyst console · i18n · model governance

ThreatHunter360 is now specified end-to-end: from scraping pipeline through reasoning engine, three intelligence modules, every user surface (web, voice, mobile, analyst console), enterprise tenancy, and the governance layer that keeps the intelligence trustworthy over time.

The north star holds throughout: **evidence-based conclusions, honest uncertainty, provenance everywhere, humans in the loop, and systems that admit what they don't know.**

If you want to continue, possible directions include: an **implementation roadmap with sprint breakdown**, **cost estimation & infrastructure sizing**, or a **security threat model (STRIDE)** document. Otherwise, this specification set is ready to hand to an engineering team.

