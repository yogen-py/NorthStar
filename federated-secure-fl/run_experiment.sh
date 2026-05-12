#!/bin/bash
export RUN_ID=$(date +"%Y-%m-%d_%H-%M-%S")
export FLOWER_NUM_ROUNDS=${NUM_ROUNDS:-15}
mkdir -p logs/run_${RUN_ID}

# Derive attack_profile from COMPOSE_PROFILES (the actual driver)
if [[ "${COMPOSE_PROFILES:-}" == *"attack"* ]]; then
  ATTACK_PROFILE_LABEL="attack:${ATTACK_MODE:-noise}"
else
  ATTACK_PROFILE_LABEL="none"
fi

cat > logs/run_${RUN_ID}/_manifest.json << EOF
{
  "run_id":            "${RUN_ID}",
  "started_at":        "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "num_rounds":        "${NUM_ROUNDS:-5}",
  "trust_weighting":   "${TRUST_WEIGHTING:-true}",
  "attack_profile":    "${ATTACK_PROFILE_LABEL}",
  "hitl_enabled":      "${HITL_ENABLED:-true}",
  "clients":           ["hospital_a", "hospital_b", "hospital_c"],
  "notes":             "${RUN_NOTES:-}"
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

cd infra && docker compose down -v && docker compose up --build --abort-on-container-exit
cd ..
echo ""
echo "Run complete. Generating assurance report..."
python3 experiments/generate_report.py logs/run_${RUN_ID}/
echo "Report: logs/run_${RUN_ID}/report.html"
echo "✅ Run ${RUN_ID} complete. Logs → logs/run_${RUN_ID}/"
