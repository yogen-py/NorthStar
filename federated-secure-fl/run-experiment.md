---
description: How to run and control Federated Learning experiments in Project North Star
---

# Running Federated Learning Experiments

This workflow describes how to launch, monitor, and control a Project North Star experiment using the automated orchestrator, Keycloak identity, OPA policy enforcement, and the Human-in-the-Loop (HITL) gate.

## 1. Initial Setup
Ensure your environment is clean and all dependencies are available.
```bash
# Optional: Clear all previous data and volumes
docker compose down -v
```

## 2. Launching the Experiment
The experiment is launched using `run_experiment.sh`. You can toggle the Human-in-the-Loop gate via the `HITL_ENABLED` environment variable.

### Option A: Vanilla Run (Automated)
Runs the experiment through all 5 rounds without pausing.
```bash
export HITL_ENABLED=false
./run_experiment.sh
```

### Option B: Interactive Run (HITL Enabled)
Pauses after every round for human inspection and approval.
```bash
export HITL_ENABLED=true
./run_experiment.sh
```

## 3. Controlling the HITL Gate
When `HITL_ENABLED=true`, the experiment will pause when a round is complete. Use the following commands from a **separate terminal** to control the flow.

### Check Status
View the latest round results, client norms, and trust scores.
```bash
curl http://localhost:9081/gate/status
```

### Approve Round
Accept the aggregated weights and proceed to the next round.
```bash
curl -X POST http://localhost:9081/gate/approve
```

### Reject Round
Discard the current round's updates and proceed.
```bash
curl -X POST http://localhost:9081/gate/reject
```

### Emergency Stop
Terminate the experiment immediately.
```bash
curl -X POST http://localhost:9081/gate/stop
```

## 4. OPA Policy Management (Live Revocation)
You can dynamically revoke client access during an experiment by updating the OPA data.

### Revoke a Client
```bash
curl -X PUT http://localhost:8181/v1/data/revoked_clients \
     -H "Content-Type: application/json" \
     -d '["hospital_c"]'
```

### Restore Access
```bash
curl -X PUT http://localhost:8181/v1/data/revoked_clients \
     -H "Content-Type: application/json" \
     -d '[]'
```

## 5. Monitoring Logs
Structured JSON logs are generated in `logs/run_<timestamp>/`.
- `server.jsonl`: Global aggregation events.
- `middleware.jsonl`: Authentication and OPA policy decisions.
- `hospital_a.jsonl`: Client-side training metrics.
