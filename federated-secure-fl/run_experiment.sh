#!/bin/bash
export RUN_ID=$(date +"%Y-%m-%d_%H-%M-%S")
mkdir -p logs/run_${RUN_ID}

cat > logs/run_${RUN_ID}/_manifest.json << EOF
{
  "run_id":         "${RUN_ID}",
  "started_at":     "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "num_rounds":     "${NUM_ROUNDS:-5}",
  "clients":        ["hospital_a", "hospital_b", "hospital_c"],
  "attack_profile": "${ATTACK_PROFILE:-none}",
  "notes":          "${RUN_NOTES:-}"
}
EOF

echo "▶ Run ${RUN_ID} starting..."

if [ "${HITL_ENABLED:-true}" = "true" ]; then
  echo ""
  echo "⚠️  Human-in-the-Loop mode is ACTIVE."
  echo "    After each round, use these commands from"
  echo "    a NEW terminal to control the experiment:"
  echo ""
  echo "    curl -X POST http://localhost:9081/gate/approve"
  echo "    curl -X POST http://localhost:9081/gate/reject"
  echo "    curl -X POST http://localhost:9081/gate/stop"
  echo ""
  echo "    Check round status anytime:"
  echo "    curl http://localhost:9081/gate/status"
  echo ""
fi

cd infra && docker compose down -v && docker compose up --build
echo "✅ Run ${RUN_ID} complete. Logs → logs/run_${RUN_ID}/"
