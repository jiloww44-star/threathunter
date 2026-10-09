"""Evidence graph for a case — spec Part 12 (Neo4j-backed in production).

Demo profile serves the same node/edge model derived from the SQL store:
  (:Claim)-[:TESTED_BY]->(:Hypothesis)-[:EVIDENCED_BY]->(:Evidence)
  (:Evidence)-[:PUBLISHED_BY]->(:Source)
  (:Source)-[:COPIED_FROM]->(:Source)   ← copy chains visualized (§1.6)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from ...api.deps import current_user, get_db
from ...models.schemas import GraphData
from ...scraper.dedupe import hamming, simhash64

router = APIRouter(prefix="/api/v1/graph", tags=["Evidence Graph"])


@router.get("/case/{case_id}", response_model=GraphData)
async def case_graph(case_id: str, depth: int = 2, db=Depends(get_db),
                     user=Depends(current_user)):
    check = db.get_check(case_id)
    if not check:
        raise HTTPException(status_code=404, detail="Case not found")
    depth = min(depth, 3)  # Part 15.4 — cap depth for latency

    nodes: list[dict] = []
    edges: list[dict] = []
    claim_node_id = f"claim-{case_id}"
    nodes.append({"id": claim_node_id, "type": "Claim",
                  "label": (check["subject"] or "")[:60],
                  "outcome": check["outcome"],
                  "confidence": check["confidence"]})

    resp = json.loads(check["response_json"])
    hypotheses = db.get_hypotheses(case_id)
    evidence_ids_in_response = []

    for h in hypotheses:
        hid = f"hyp-{h['id'][:8]}"
        nodes.append({"id": hid, "type": "Hypothesis",
                      "label": h["statement"],
                      "status": h["status"], "score": h["score"]})
        edges.append({"id": f"e-{claim_node_id}-{hid}", "source": claim_node_id,
                      "target": hid, "type": "TESTED_BY"})

    for e in resp.get("key_evidence", []):
        # resolve stored evidence rows by metadata match on source/url
        evidence_ids_in_response.append(e)

    # Evidence + Source nodes from the persisted response
    seen_src: dict[str, str] = {}
    for idx, e in enumerate(resp.get("key_evidence", [])):
        ev_id = f"ev-{idx}"
        nodes.append({"id": ev_id, "type": "Evidence",
                      "label": (e.get("excerpt") or "")[:70],
                      "reliability": e.get("reliability"),
                      "authority": e.get("authority"),
                      "independence_group": e.get("independence_group"),
                      "supports_claim": e.get("supports_claim"),
                      "url": e.get("url"),
                      "fetched_at": e.get("fetched_at"),
                      "is_duplicate_copy": e.get("is_duplicate_copy", False)})
        src_key = e.get("source_id", "unknown")
        if src_key not in seen_src:
            src_id = f"src-{src_key}"
            seen_src[src_key] = src_id
            nodes.append({"id": src_id, "type": "Source", "label": src_key,
                          "reliability": e.get("reliability"),
                          "authority": e.get("authority"),
                          "independence_group": e.get("independence_group")})
        edges.append({"id": f"e-{ev_id}-pub", "source": ev_id,
                      "target": seen_src[src_key], "type": "PUBLISHED_BY"})
        # link evidence to the winning (ACTIVE) hypothesis
        for h in hypotheses:
            if h["status"] == "ACTIVE":
                edges.append({"id": f"e-{ev_id}-h{h['id'][:8]}",
                              "source": f"hyp-{h['id'][:8]}",
                              "target": ev_id, "type": "EVIDENCED_BY"})

    # COPIED_FROM edges: duplicates vs group primary — the §1.6 visual
    originals = [e for e in resp.get("key_evidence", [])
                 if not e.get("is_duplicate_copy")]
    copies = [e for e in resp.get("key_evidence", []) if e.get("is_duplicate_copy")]
    for c in copies:
        for o in originals:
            if (c.get("independence_group") == o.get("independence_group")
                    and hamming(simhash64(c.get("excerpt", "")),
                                simhash64(o.get("excerpt", ""))) <= 16):
                edges.append({
                    "id": f"e-copy-{c['source_id']}-{o['source_id']}",
                    "source": seen_src.get(c["source_id"], ""),
                    "target": seen_src.get(o["source_id"], ""),
                    "type": "COPIED_FROM",
                })

    return GraphData(nodes=nodes, edges=edges)
