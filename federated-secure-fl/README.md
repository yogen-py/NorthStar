# Project North Star — Secure Federated Learning Pipeline

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)
![Flower 1.8.0](https://img.shields.io/badge/Flower-1.8.0-green?style=flat-square)
![Keycloak 24.0](https://img.shields.io/badge/Keycloak-24.0-orange?style=flat-square)
![OPA](https://img.shields.io/badge/OPA-Policy_Engine-purple?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-teal?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-Compose_v2-2496ED?style=flat-square)

Privacy-preserving federated learning across distributed hospital nodes with identity-verified admission, OPA policy enforcement, behaviorally-scored trust weighting, Byzantine fault simulation, and audit-grade assurance reporting — all containerised and reproducible in a single command.

---

## 1. Overview

Project North Star is a research-grade federated learning pipeline designed to demonstrate that **security architecture**, not model accuracy, is the hard problem in production FL deployments. Three hospital clients train a shared model without ever exposing raw data; every participation attempt is authenticated via Keycloak JWT credentials and authorised by an OPA policy engine before any gradient update is admitted. A persistent trust scoring engine computes per-client behavioural reputation using exponential moving average (EMA) smoothing, and those scores directly re-weight the FedAvg aggregation so that low-trust clients contribute proportionally less to the global model. 

The pipeline concludes each run by generating a self-contained HTML assurance report that provides an auditable record of every identity decision, trust event, and compliance flag — making the system suitable for regulated environments where model provenance must be demonstrated.

> **Scope note.** Client-side "training" is mocked with numpy random weight perturbations. This is intentional: the contribution of this project is the end-to-end security and observability stack, not the ML model. All trust signals, anomaly detections, and aggregation weights are computed on real update norms derived from those perturbations.

---

## 2. Architecture

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          Docker bridge network: fl-net                       ║
║                                                                              ║
║  ┌──────────────────┐   JWT creds    ┌──────────────────────────────────┐   ║
║  │   hospital_a     │──────────────► │       fl-middleware  :8000        │   ║
║  │   hospital_b     │──────────────► │  (FastAPI)                        │   ║
║  │   hospital_c     │──────────────► │  1. Verify JWT  (Keycloak JWKS)  │   ║
║  └──────────────────┘                │  2. OPA admit check              │   ║
║                                      │  3. Proxy admit/deny             │   ║
║  ┌──────────────────┐                └──────────────┬───────────────────┘   ║
║  │ malicious_client │  (profile:attack)             │ admit_decision logged  ║
║  │  ATTACK_MODE=    │                               ▼                        ║
║  │  noise|sign_flip │           ┌───────────────────────────────────────┐   ║
║  └──────────────────┘           │          fl-server  :9080 (gRPC)      │   ║
║                                 │                    :9081 (FastAPI)    │   ║
║  ┌──────────────────┐           │  ┌─────────────────────────────────┐  │   ║
║  │  keycloak :8080  │◄──JWKS───►│  │  TrustWeightedFedAvg strategy  │  │   ║
║  │  (AuthN / IdP)   │           │  │  ┌──────────────────────────┐  │  │   ║
║  └──────────────────┘           │  │  │   TrustEngine (scoring)  │  │  │   ║
║                                 │  │  │   EMA + norm history     │──┼──┼──► trust.db (SQLite)
║  ┌──────────────────┐           │  │  └──────────────────────────┘  │  │   ║
║  │    opa  :8181    │◄─policy──►│  │  weights → aggregate → bcast   │  │   ║
║  │  (AuthZ / Rego)  │           │  └─────────────────────────────────┘  │   ║
║  └──────────────────┘           │  HITL gate  POST /gate/{approve|reject}│  ║
║                                 │  Assurance  GET  /assurance/report     │   ║
║                                 └───────────────────────────────────────┘   ║
║                                              │                               ║
║                                              ▼                               ║
║                                    logs/run_<id>/                            ║
║                                    ├── server.jsonl                          ║
║                                    ├── middleware.jsonl                      ║
║                                    ├── trust.jsonl                           ║
║                                    ├── hospital_{a,b,c}.jsonl                ║
║                                    ├── _manifest.json                        ║
║                                    └── report.html  ◄── generate_report.py  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Data flows
  JWT → middleware → OPA → admit/deny
  update weights → fl-server → trust scoring → trust.db
  trust-weighted aggregation → broadcast new global weights
  all JSONL events → generate_report.py → report.html
```

---

## 3. Phase Map

| Phase | Name | What Was Built | Status |
|-------|------|----------------|--------|
| **0** | Scaffold & Smoke Test | Docker Compose stack with Flower server, three hospital clients, Keycloak, and OPA wired into a `fl-net` bridge network with health checks. | ✅ Complete |
| **1** | End-to-End FL Pipeline | FedAvg training loop over 5 rounds using a mock numpy model with partitioned MNIST-like data; structured JSONL logging via `shared/logger.py`. | ✅ Complete |
| **2** | JWT Authentication | Keycloak 24.0 identity provider with realm import; `fl-middleware` verifies client JWTs via JWKS endpoint before proxying any FL participation request. | ✅ Complete |
| **3** | OPA Policy Enforcement | OPA Rego policy (`fl_policy.rego`) enforces `role==trainer` and revocation list; live client revocation via `PUT /v1/data/revoked_clients` without container restart. | ✅ Complete |
| **3.5** | HITL Gate | Human-in-the-Loop gate on `fl-server` that can pause training after each round for operator approval, rejection, or emergency stop via REST endpoints. | ✅ Complete |
| **4** | Trust Scoring Engine | Persistent SQLite-backed `TrustEngine` with EMA smoothing, per-client norm history, six scoring rules (including cosine similarity), and warmup guard. | ✅ Complete |
| **5** | Byzantine Attack Simulation | `malicious_client.py` with `noise` (10× Gaussian) and `sign_flip` modes; deterministic seeding for mock consensus; verified comparison runs. | ✅ Complete |
| **6** | Assurance Reporting | `GET /assurance/report` live JSON endpoint and `generate_report.py` offline HTML generator producing a self-contained report with compliance flags and trust trajectory. | ✅ Complete |

---

## 4. Security Architecture

### 4a. Zero Trust Admission (Keycloak + OPA)

Every client must present a valid JWT before any FL interaction. The flow is:

1. **Client credentials grant** — each hospital service requests a token from Keycloak using its `CLIENT_ID` / `CLIENT_SECRET`. Tokens carry a `role: trainer` claim.
2. **JWT verification** — `fl-middleware` fetches Keycloak's JWKS endpoint and verifies the token's signature, expiry, and issuer on every inbound request.
3. **OPA policy check** — the verified claims are forwarded to OPA. The Rego policy is deliberately minimal and auditable:

```rego
package fl

import rego.v1

default allow := false

allow if {
    input.role == "trainer"
    not input.client_id in data.revoked_clients
}
```

4. **Admit / deny** — if OPA returns `allow=true`, the request is proxied to `fl-server`; otherwise it is rejected with HTTP 403 and an `admit_decision` event is written to `middleware.jsonl`.
5. **Live revocation** — a client can be removed from the federation mid-run without restarting any container:

```bash
curl -X PUT http://localhost:8181/v1/data/revoked_clients \
     -H "Content-Type: application/json" \
     -d '["hospital_c"]'
```

### 4b. Trust Scoring Engine (EMA)

The `TrustEngine` class in `trust/scoring.py` maintains a persistent reputation score per client in SQLite.

**EMA formula:**
```
T_new = 0.3 × O_current + 0.7 × T_prev
```
where `O_current` is the observation score for the current round, computed by applying the six rules below to `T_prev` as a starting point.

**Scoring rules:**

| Rule | Signal | Δ Score | Trigger Condition |
|------|--------|---------|-------------------|
| 1 | Dropout penalty | −0.10 | Client did not submit an update this round |
| 2 | Policy warning | −0.20 | OPA `policy_warning` flag set by middleware |
| 3 | Norm anomaly | −0.15 | `update_norm > 2× client's rolling 5-round mean` (post-warmup) |
| 4 | Low-loss bonus | +0.03 | `train_loss < LOW_LOSS_THRESHOLD` (default 0.3) and no dropout |
| 5 | Participation bonus | +0.05 | Client present every round so far and zero lifetime anomalies |
| 6 | Direction anomaly | −0.20 | Cosine similarity against global median < -0.3 (flags opposite-direction gradients) |

**Additional guards:**
- **Anomaly floor**: after 3+ lifetime anomalies, `O_current` is capped at 0.6, preventing EMA recovery for persistently malicious clients.
- **Score clamp**: `T_new ∈ [0.1, 1.0]` — a client can never be fully expelled or fully trusted by score alone.
- **Warmup guard**: during rounds 1–`WARMUP_ROUNDS` (default 3), `get_score()` returns the neutral baseline 0.8 regardless of DB state. Rule 6 is specifically skipped in Round 1 before a global consensus exists.

**Per-client norm history — design rationale and bug fix:**
> The naive approach — maintaining a single *shared* `baseline_norm` averaged across all clients — was the first implementation and introduced a reproducible bug. When `malicious_client` began submitting high-norm updates, those values inflated the shared running mean. After a few rounds, the shared baseline had risen far enough that even *legitimate* hospital updates appeared to exceed the `2× baseline` anomaly threshold, triggering Rule 3 penalties against honest clients.
>
> **The fix** gives each client an independent in-memory deque of its own last five update norms. Rule 3 compares a client's current norm against *its own* rolling mean only. A malicious client's escalating norms cannot touch any other client's anomaly threshold.

### 4c. Synchronization of Client Mocks
To make Rule 6 (Direction-Based Detection) effective, "honest" mock clients were updated to use deterministic random seeding (`numpy.random` seeded with the current `server_round`). This forces all honest clients to share a common "true gradient" direction in each round, allowing the server's median direction to act as a rock-solid reference for detecting sign-flippers.

### 4d. Trust-Weighted Aggregation (TrustWeightedFedAvg)

The custom Flower strategy in `server/server.py` replaces FedAvg's uniform weighting with trust-scaled effective sample counts:

```
w_eff_i = (n_i × T_i) / Σ_j (n_j × T_j)
```

where `n_i` is the number of examples reported by client `i` and `T_i` is its current trust score. A client with `T = 0.4` contributes half as much weight as an identical client with `T = 0.8`. As an attacker's trust decays, its influence on the global model asymptotically approaches zero. 

Furthermore, **clients flagged by Rule 3 or Rule 6 are programmatically excluded from the global model aggregation** entirely for that round.

---

## 5. Attack Simulation

The attack profile is gated behind a Docker Compose profile so it never starts by accident:

```bash
docker compose --profile attack up malicious_client
```

**Attack modes** (set via `ATTACK_MODE` environment variable):

| Mode | Mechanism | Detection Signal |
|------|-----------|-----------------|
| `noise` | Adds Gaussian noise at **10× the normal update scale** | `update_norm` spikes 10× above client's rolling mean; triggers Rule 3 from round 4 |
| `sign_flip` | Multiplies every weight by **−1** | Opposite geometric direction; triggers Rule 6 (Cosine Sim < -0.3) and rapid trust decay |

---

## 6. Verification Sweep & Assurance Reporting

We validated the entire pipeline across three scenarios using the `run_experiment.sh` script:

- **Run A (Noise Attack)**: Verified magnitude-based detection successfully down-weights and excludes clients pushing massive random updates.
- **Run B (Sign-Flip Attack)**: Verified the new Rule 6 successfully flags the adversary (Cosine Sim ≈ -0.4) and rapidly decays their score.
- **Run C (Clean Baseline)**: Confirmed zero false positives for honest hospitals across the board.

### Assurance Reports

After each run, an HTML assurance report is generated in `logs/run_<id>/report.html`. This report provides transparent observability to auditors:

- **New Metrics**: A "Cosine Sim" column has been added to the Trust Trajectory table.
- **Anomaly Flagging**: Direction and norm anomalies are visually flagged, tracking exact exclusion events programmatically.

**Live JSON endpoint** is also available while `fl-server` is running:
```bash
curl http://localhost:9081/assurance/report
```

**Compliance flag types:**

| Flag Type | Trigger |
|-----------|---------|
| `POLICY_DENIAL` | OPA rejected an admission attempt |
| `TRUST_ANOMALY` | `is_anomaly=true` in a `trust_updated` event |
| `OPERATOR_REJECT` | Human operator rejected a round via HITL gate |
| `OPERATOR_STOP` | Human operator issued emergency stop |

---

## 7. Quick Start

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker + Docker Compose v2 | `docker compose version` to verify |
| Python 3.10+ | For offline report generation only |
| 8 GB RAM recommended | Keycloak needs ~1.5 GB; all containers ~4 GB |

### Steps

**1. Clone and enter the project:**
```bash
git clone <repo-url> NorthStar
cd NorthStar/federated-secure-fl
```

**2. Create your environment file:**
```bash
cp .env.example infra/.env
```

**3. Run a normal experiment (automated, no attack):**
```bash
export HITL_ENABLED=false
./run_experiment.sh
# Builds images, runs 5 rounds, and generates report.html.
```

**4. Run with Human-in-the-Loop gate enabled:**
```bash
export HITL_ENABLED=true
./run_experiment.sh
# From a second terminal, control each round:
curl http://localhost:9081/gate/status           # inspect round result
curl -X POST http://localhost:9081/gate/approve  # accept and continue
curl -X POST http://localhost:9081/gate/reject   # discard round, continue
curl -X POST http://localhost:9081/gate/stop     # emergency stop
```

**5. Run with a malicious client (Byzantine attack simulation):**
```bash
export HITL_ENABLED=false
export ATTACK_MODE=sign_flip  # or 'noise'
export COMPOSE_PROFILES=attack
./run_experiment.sh
```

**6. Revoke a client mid-run (from a separate terminal):**
```bash
# Revoke hospital_c
curl -X PUT http://localhost:8181/v1/data/revoked_clients \
     -H "Content-Type: application/json" \
     -d '["hospital_c"]'

# Restore full access
curl -X PUT http://localhost:8181/v1/data/revoked_clients \
     -H "Content-Type: application/json" \
     -d '[]'
```

---

## 8. Configuration Reference

All variables can be set in `infra/.env` or exported before calling `run_experiment.sh`.

| Variable | Default | Description |
|----------|---------|-------------|
| `FLOWER_NUM_ROUNDS` | `5` | Number of FL training rounds |
| `SERVER_ADDRESS` | `fl-server:9080` | Flower gRPC server address (inside fl-net) |
| `DB_URL` | `sqlite:///./trust.db` | Trust database connection string |
| `WARMUP_ROUNDS` | `3` | Rounds excluded from trust-weighted aggregation |
| `TRUST_WEIGHTING` | `true` | Set `false` to revert to uniform FedAvg |
| `LOW_LOSS_THRESHOLD` | `0.3` | Training loss below which the Rule 4 bonus applies |
| `HITL_ENABLED` | `true` | Pause after each round for human gate approval |
| `GATE_PORT` | `9081` | Port for the HITL gate and assurance API |
| `KEYCLOAK_URL` | `http://keycloak:8080` | Keycloak base URL |
| `OPA_URL` | `http://opa:8181` | OPA policy decision endpoint |
| `KC_ADMIN` | `admin` | Keycloak admin username |
| `KC_ADMIN_PASSWORD` | `admin` | Keycloak admin password |
| `ATTACK_MODE` | `noise` | Attack type for malicious client: `noise` or `sign_flip` |
| `RUN_ID` | `default` | Injected by `run_experiment.sh`; scopes log filenames |
| `LOG_DIR` | `/app/logs` | Log directory inside containers (mounted from `./logs`) |

---

## 9. Academic References

1. **McMahan, H. B., et al. (2017).** Communication-Efficient Learning of Deep Networks from Decentralized Data. *AISTATS 2017.*
2. **Blanchard, P., et al. (2017).** Machine Learning with Adversaries: Byzantine Tolerant Gradient Descent. *NeurIPS 2017.*
3. **Fung, C., et al. (2020).** The Limitations of Federated Learning in Sybil Settings. *RAID 2020.*
4. **Cao, X., et al. (2021).** FLTrust: Byzantine-Robust Federated Learning via Trust Bootstrapping. *NDSS 2021.*
5. **Mothukuri, V., et al. (2021).** A Survey on Security and Privacy of Federated Learning. *Future Generation Computer Systems, 115.*
6. **Open Policy Agent Documentation.** https://www.openpolicyagent.org/docs/

---
*Project North Star — internal research use only.*
