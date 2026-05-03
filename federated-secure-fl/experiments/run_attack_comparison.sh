#!/bin/bash
set -e

echo "=== Phase 5: Attack Comparison ==="
echo ""

# Run A: No trust weighting, attack active
export RUN_ID="runA_$(date +%H-%M-%S)_baseline"
export TRUST_WEIGHTING=false
export HITL_ENABLED=false
export FLOWER_NUM_ROUNDS=15
mkdir -p logs/run_${RUN_ID}
cat > logs/run_${RUN_ID}/_manifest.json << EOF
{"run_id":"${RUN_ID}","trust_weighting":false,"attack":"noise","notes":"baseline_undefended"}
EOF
echo "▶ Run A: Standard FedAvg + malicious client (no trust weighting)"
docker compose -f infra/docker-compose.yml --profile attack up --build -d
docker compose -f infra/docker-compose.yml wait fl-server
docker compose -f infra/docker-compose.yml --profile attack down
echo "✅ Run A complete → logs/run_${RUN_ID}/"

echo ""
sleep 5

# Run B: Trust weighting active, attack active
export RUN_ID="runB_$(date +%H-%M-%S)_defended"
export TRUST_WEIGHTING=true
export HITL_ENABLED=false
export FLOWER_NUM_ROUNDS=15
mkdir -p logs/run_${RUN_ID}
cat > logs/run_${RUN_ID}/_manifest.json << EOF
{"run_id":"${RUN_ID}","trust_weighting":true,"attack":"noise","notes":"trust_defended"}
EOF
echo "▶ Run B: Trust-weighted FedAvg + malicious client (defended)"
docker compose -f infra/docker-compose.yml --profile attack up --build -d
docker compose -f infra/docker-compose.yml wait fl-server
docker compose -f infra/docker-compose.yml --profile attack down
echo "✅ Run B complete → logs/run_${RUN_ID}/"

echo ""
echo "=== Comparison complete ==="
echo "Run A logs: logs/run_runA_*/"
echo "Run B logs: logs/run_runB_*/"
echo "To analyze: python experiments/analyze_runs.py"
