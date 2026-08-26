#!/usr/bin/env bash
# ThreatHunter360 — one-command demo (spec Part 10)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ Installing backend deps (idempotent)…"
pip install -q -r backend/requirements.txt 2>/dev/null || \
  pip install -q --user --break-system-packages -r backend/requirements.txt

echo "▶ Starting API on :8000 (auto-seeds demo pack)…"
(cd backend && exec uvicorn app.main:app --host 0.0.0.0 --port 8000) &
API_PID=$!
trap "kill $API_PID 2>/dev/null || true" EXIT

echo "▶ Waiting for API…"
until curl -sf http://localhost:8000/healthz >/dev/null; do sleep 1; done

echo ""
echo "✅ ThreatHunter360 is running:"
echo "   API + docs : http://localhost:8000/docs"
echo "   Scenarios  : see seed/demo_scenarios.md"
echo ""
echo "Tip: python seed/seed_script.py --confirm  → scenario 5 (live reassessment)"
wait $API_PID
