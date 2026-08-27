"""v3.5 crisis-focus tests — red-team review #10.

The crisis pathway must (a) carry its checklist + honest guidance on the
ACTIVE-INCIDENT POLL, not only on the declare response — restored sessions
and late joiners see the same contract; (b) simplify, not accelerate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.store.db import reset_store                            # noqa: E402
from app.swarm import incident                                  # noqa: E402


class TestActiveIncidentContract:
    def _client(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import app
        reset_store(str(tmp_path / "crisis.db"))
        return TestClient(app)

    def test_active_poll_carries_checklist_and_guidance(self, tmp_path):
        client = self._client(tmp_path)
        r = client.post("/api/v1/ops/incident/declare",
                        json={"severity": "SEV1",
                              "summary": "live ransomware on file server",
                              "declared_by": "op-1"})
        assert r.status_code == 200
        body = client.get("/api/v1/ops/incident/active").json()["incident"]
        assert body is not None
        assert body["checklist"] == incident.RESPONSE_CHECKLIST
        assert len(body["checklist"]) == 6
        assert "not a substitute" in body["ui_guidance"]
        assert "simplifies" in body["ui_guidance"]

    def test_guidance_never_accelerates(self):
        g = incident.UI_GUIDANCE.lower()
        assert "reduced motion" in g
        assert "no feed acceleration" in g

    def test_resolve_clears_checklist(self, tmp_path):
        client = self._client(tmp_path)
        client.post("/api/v1/ops/incident/declare",
                    json={"severity": "SEV2", "summary": "drill incident",
                          "declared_by": "op-1"})
        inc = client.get("/api/v1/ops/incident/active").json()["incident"]
        client.post(f"/api/v1/ops/incident/{inc['incident_id']}/resolve")
        assert client.get("/api/v1/ops/incident/active").json()["incident"] \
            is None
