# Project North Star — Secure Federated Learning Pipeline

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)
![Flower 1.8.0](https://img.shields.io/badge/Flower-1.8.0-green?style=flat-square)
![Keycloak 24.0](https://img.shields.io/badge/Keycloak-24.0-orange?style=flat-square)
![OPA](https://img.shields.io/badge/OPA-Policy_Engine-purple?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-teal?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-Compose_v2-2496ED?style=flat-square)

Privacy-preserving federated learning across distributed hospital nodes with identity-verified admission, OPA policy enforcement, behaviorally-scored trust weighting, Byzantine fault simulation, and audit-grade assurance reporting — all containerised and reproducible in a single command.

---

## 2. Overview

Project North Star is a research-grade federated learning pipeline designed to demonstrate that **security architecture**, not model accuracy, is the hard problem in production FL deployments. Three hospital clients train a shared model without ever exposing raw data; every participation attempt is authenticated via Keycloak JWT credentials and authorised by an OPA policy engine before any gradient update is admitted. A persistent trust scoring engine computes per-client behavioural reputation using exponential moving average (EMA) smoothing, and those scores directly re-weight the FedAvg aggregation so that low-trust clients contribute proportionally less to the global model. The pipeline concludes each run by generating a self-contained HTML assurance report that provides an auditable record of every identity decision, trust event, and compliance flag — making the system suitable for regulated environments where model provenance must be demonstrated.

> **Scope note.** Client-side "training" is mocked with numpy random weight perturbations. This is intentional: the contribution of this project is the end-to-end security and observability stack, not the ML model. All trust signals, anomaly detections, and aggregation weights are computed on real update norms derived from those perturbations.

---

## 3. Architecture

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

## 4. Phase Map

| Phase | Name | What Was Built | Status |
|-------|------|----------------|--------|
| **0** | Scaffold & Smoke Test | Docker Compose stack with Flower server, three hospital clients, Keycloak, and OPA wired into a `fl-net` bridge network with health checks. | ✅ Complete |
| **1** | End-to-End FL Pipeline | FedAvg training loop over 5 rounds using a mock numpy model with partitioned MNIST-like data; structured JSONL logging via `shared/logger.py`. | ✅ Complete |
| **2** | JWT Authentication | Keycloak 24.0 identity provider with realm import; `fl-middleware` verifies client JWTs via JWKS endpoint before proxying any FL participation request. | ✅ Complete |
| **3** | OPA Policy Enforcement | OPA Rego policy (`fl_policy.rego`) enforces `role==trainer` and revocation list; live client revocation via `PUT /v1/data/revoked_clients` without container restart. | ✅ Complete |
| **3.5** | HITL Gate | Human-in-the-Loop gate on `fl-server` that can pause training after each round for operator approval, rejection, or emergency stop via REST endpoints. | ✅ Complete |
| **4** | Trust Scoring Engine | Persistent SQLite-backed `TrustEngine` with EMA smoothing, per-client norm history, five scoring rules (dropout, policy warning, norm anomaly, low-loss bonus, participation bonus), and warmup guard. | ✅ Complete |
| **5** | Byzantine Attack Simulation | `malicious_client.py` with `noise` (10× Gaussian) and `sign_flip` modes; `TrustWeightedFedAvg` aggregation that down-weights attacker contributions to near zero by round 11; verified comparison runs. | ✅ Complete |
| **6** | Assurance Reporting | `GET /assurance/report` live JSON endpoint and `generate_report.py` offline HTML generator producing a self-contained dark/light-mode report with compliance flags, trust trajectory, and per-client cards. | ✅ Complete |

---

## 5. Security Architecture

### 5a. Zero Trust Admission (Keycloak + OPA)

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

### 5b. Trust Scoring Engine (EMA)

The `TrustEngine` class in `trust/scoring.py` maintains a persistent reputation score per client in SQLite.

**EMA formula:**
```
T_new = 0.3 × O_current + 0.7 × T_prev
```
where `O_current` is the observation score for the current round, computed by applying the five rules below to `T_prev` as a starting point.

**Scoring rules:**

| Rule | Signal | Δ Score | Trigger Condition |
|------|--------|---------|-------------------|
| 1 | Dropout penalty | −0.10 | Client did not submit an update this round |
| 2 | Policy warning | −0.20 | OPA `policy_warning` flag set by middleware |
| 3 | Norm anomaly | −0.15 | `update_norm > 2× client's rolling 5-round mean` (post-warmup) |
| 4 | Low-loss bonus | +0.03 | `train_loss < LOW_LOSS_THRESHOLD` (default 0.3) and no dropout |
| 5 | Participation bonus | +0.05 | Client present every round so far and zero lifetime anomalies |

Additional guards:
- **Anomaly floor**: after 3+ lifetime anomalies, `O_current` is capped at 0.6, preventing EMA recovery for persistently malicious clients.
- **Score clamp**: `T_new ∈ [0.1, 1.0]` — a client can never be fully expelled or fully trusted by score alone.
- **Warmup guard**: during rounds 1–`WARMUP_ROUNDS` (default 3), `get_score()` returns the neutral baseline 0.8 regardless of DB state, so aggregation weighting only kicks in once a genuine behavioural history exists.

**Per-client norm history — design rationale and bug fix:**

> **⚠️ Implementation note: why per-client baselines matter**
>
> The naive approach — maintaining a single *shared* `baseline_norm` averaged across all clients — was the first implementation and introduced a concrete, reproducible bug. When `malicious_client` began submitting high-norm updates (10× the honest clients' norms), those values inflated the shared running mean. After a few rounds, the shared baseline had risen far enough that even *legitimate* hospital updates appeared to exceed the `2× baseline` anomaly threshold, triggering Rule 3 penalties against clients that were behaving perfectly honestly. This produced false-positive anomaly flags on `hospital_a`, `hospital_b`, and `hospital_c` — exactly the failure mode a Byzantine attacker would want to induce.
>
> **The fix** (`self._norm_history: dict[str, list[float]]`) gives each client an independent in-memory deque of its own last five update norms. Rule 3 compares a client's current norm against *its own* rolling mean only. A malicious client's escalating norms cannot touch any other client's anomaly threshold.
>
> **Why this matters beyond this project:** shared global baselines are a common unstated assumption in trust-scoring FL literature — papers describe "the baseline norm" without specifying whether it is per-client or global. This is a concrete, reproducible failure mode with a one-line fix (`self._norm_history.setdefault(client_id, [])`). Reviewers of FL security systems should treat this as a checklist item.

### 5c. Trust-Weighted Aggregation (TrustWeightedFedAvg)

The custom Flower strategy in `server/server.py` replaces FedAvg's uniform weighting with trust-scaled effective sample counts:

```
w_eff_i = (n_i × T_i) / Σ_j (n_j × T_j)
```

where `n_i` is the number of examples reported by client `i` and `T_i` is its current trust score. A client with `T = 0.4` contributes half as much weight as an identical client with `T = 0.8`. As an attacker's trust decays, its influence on the global model asymptotically approaches zero.

**Fallback:** set `TRUST_WEIGHTING=false` in the environment to revert to uniform FedAvg with no code changes, enabling clean A/B comparisons.

---

## 6. Attack Simulation

The attack profile is gated behind a Docker Compose profile so it never starts by accident:

```bash
docker compose --profile attack up malicious_client
```

**Attack modes** (set via `ATTACK_MODE` environment variable):

| Mode | Mechanism | Detection Signal |
|------|-----------|-----------------|
| `noise` | Adds Gaussian noise at **10× the normal update scale** to all weight tensors | `update_norm` spikes 10× above client's rolling mean; triggers Rule 3 from round 4 |
| `sign_flip` | Multiplies every weight by **−1**, pushing the global model in the opposite gradient direction | Large negative-direction norm; triggers Rule 3 and rapid trust decay |

**Verified results — run `runB_11-40-11_defended` (15 rounds, `noise` mode):**

| Metric | Value |
|--------|-------|
| Malicious client initial trust | 0.800 |
| Malicious client final trust | 0.368 |
| Honest hospital final trust | 0.860 |
| Anomalies flagged (malicious) | 12 of 15 rounds |
| False positives (honest clients) | 0 (after per-client norm fix) |
| Attacker aggregation weight | < 1% of total by round 11 |

---

## 7. Assurance Reporting

### Live JSON endpoint

Available while `fl-server` is running:

```bash
curl http://localhost:9081/assurance/report
# optional: ?run_id=2026-05-03_12-13-53
```

Returns structured JSON covering run metadata, identity statistics, trust state per client, round events, gate decisions, and compliance flags.

### Offline HTML report

```bash
python3 experiments/generate_report.py logs/run_<id>/
# output: logs/run_<id>/report.html
```

The HTML file is fully self-contained (all CSS and JS inlined), renders correctly from `file://`, and supports system dark/light mode via `prefers-color-scheme`.

**Report sections:**

| Section | Contents |
|---------|----------|
| Run Header | Run ID, timestamp, number of rounds, attack profile, trust weighting enabled |
| Compliance Summary | Total flags, breakdown by type, pass/warn/fail badge |
| Identity & Policy | Admission attempts, allowed vs. denied counts, policy errors |
| Trust Trajectory | Per-client trust score across all rounds (tabular) |
| Per-Client Cards | Final trust score, anomaly count, rounds participated |
| Round Summary | Loss and accuracy per round, gate decision |
| Scope Note | Reminder that training is mocked; security architecture is the contribution |

**Compliance flag types:**

| Flag Type | Trigger |
|-----------|---------|
| `POLICY_DENIAL` | OPA rejected an admission attempt |
| `TRUST_ANOMALY` | `is_anomaly=true` in a `trust_updated` event |
| `OPERATOR_REJECT` | Human operator rejected a round via HITL gate |
| `OPERATOR_STOP` | Human operator issued emergency stop |

---

## 8. Quick Start

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker + Docker Compose v2 | `docker compose version` to verify |
| Python 3.10+ | For offline report generation only |
| 8 GB RAM recommended | Keycloak alone needs ~1.5 GB; all containers together ~4 GB |

### Steps

**1. Clone and enter the project:**
```bash
git clone <repo-url> NorthStar
cd NorthStar/federated-secure-fl
```

**2. Create your environment file:**
```bash
cp .env.example infra/.env
# Edit infra/.env if you need non-default ports or credentials
```

**3. Run a normal experiment (automated, no attack):**
```bash
export HITL_ENABLED=false
./run_experiment.sh
# Builds all images, tears down any previous stack, runs 5 rounds,
# and generates logs/run_<timestamp>/report.html automatically.
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
cd infra
docker compose down -v
docker compose --profile attack up --build
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

**7. Generate an assurance report for a completed run:**
```bash
python3 experiments/generate_report.py logs/run_<timestamp>/
# Output: logs/run_<timestamp>/report.html
```

**8. Query the live assurance endpoint (while server is running):**
```bash
curl http://localhost:9081/assurance/report | python3 -m json.tool
```

---

## 9. Project Structure

```
federated-secure-fl/
│
├── server/                        # FL server + middleware
│   ├── server.py                  # Flower server, TrustWeightedFedAvg strategy, HITL wiring
│   ├── middleware.py              # FastAPI: JWT verification, OPA admission, request logging
│   ├── assurance.py              # Assurance reporting router (GET /assurance/report)
│   ├── gate.py                    # HITL gate state machine (approve / reject / stop)
│   ├── trust_db.py               # SQLAlchemy session factory (used by middleware)
│   ├── input_handler.py          # Stdin reader for interactive gate in Docker TTY
│   ├── requirements.txt          # flwr, fastapi, uvicorn, python-jose, httpx, SQLAlchemy
│   └── Dockerfile                # Single image used for both fl-server and fl-middleware
│
├── client/                        # Federated learning clients
│   ├── client.py                  # Flower NumPy client: fit() and evaluate() with JSONL logging
│   ├── mock_model.py             # Numpy mock model (random weight perturbations, no PyTorch)
│   ├── data.py                    # Deterministic data partitioning by CLIENT_ID index
│   ├── requirements.txt          # flwr, numpy
│   └── Dockerfile
│
├── trust/                         # Trust scoring engine
│   ├── scoring.py                 # TrustEngine: EMA formula, 5 scoring rules, per-client norm history
│   ├── schema.sql                 # SQLite DDL for client_trust table
│   └── __init__.py
│
├── experiments/                   # Attack simulation and analysis tooling
│   ├── malicious_client.py       # Byzantine attacker: noise and sign_flip attack modes
│   ├── generate_report.py        # Offline HTML report generator (fully self-contained output)
│   ├── verify.py                  # Quick sanity-check script for log structure
│   ├── analyze_runs.py           # Cross-run comparison and CSV export
│   └── run_attack_comparison.sh  # Orchestrates back-to-back baseline vs. defended runs
│
├── policy/                        # OPA policy files
│   ├── fl_policy.rego             # Rego: allow if role==trainer and client not revoked
│   └── revoked_clients.json      # Initial revocation list (empty by default)
│
├── shared/                        # Cross-container shared library (mounted read-only)
│   ├── logger.py                  # get_logger(), log_event(), Timer context manager
│   └── __init__.py
│
├── infra/                         # Infrastructure
│   ├── docker-compose.yml        # All services, health checks, profiles, volume mounts
│   └── keycloak/                  # Keycloak realm export (auto-imported on start-dev)
│
├── logs/                          # Runtime output (git-ignored except .gitkeep)
│   └── run_<timestamp>/
│       ├── _manifest.json        # Run metadata: ID, rounds, clients, attack profile
│       ├── server.jsonl          # Aggregation, round, gate, and trust-weighting events
│       ├── middleware.jsonl      # Admission decisions and policy errors
│       ├── trust.jsonl           # Per-client trust_updated events (every round)
│       ├── hospital_{a,b,c}.jsonl # Client-side fit and evaluate events
│       └── report.html           # Generated assurance report
│
├── run_experiment.sh             # Top-level orchestrator: down → up → generate_report
├── .env.example                  # Environment variable template
└── README.md                      # This file
```

---

## 10. Configuration Reference

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
| `KEYCLOAK_URL` | `http://keycloak:8080` | Keycloak base URL (used by middleware for JWKS) |
| `OPA_URL` | `http://opa:8181` | OPA policy decision endpoint |
| `KC_ADMIN` | `admin` | Keycloak admin username |
| `KC_ADMIN_PASSWORD` | `admin` | Keycloak admin password |
| `ATTACK_MODE` | `noise` | Attack type for malicious client: `noise` or `sign_flip` |
| `RUN_ID` | `default` | Injected by `run_experiment.sh`; scopes log filenames |
| `LOG_DIR` | `/app/logs` | Log directory inside containers (mounted from `./logs`) |

---

## 11. Scope Note

This project is a **security architecture demonstrator**, not a production FL system. The following are intentional simplifications:

- **Mock training:** `client/mock_model.py` generates random numpy weight tensors. No real neural network or dataset is used. Update norms are real and drive the trust engine.
- **SQLite trust DB:** sufficient for single-node research. A production deployment would use PostgreSQL — the Docker Compose `volumes` block already includes a `pgdata` volume ready for migration.
- **No differential privacy:** DP-SGD gradient clipping/noise is not implemented; this is an admission control and trust-scoring study.
- **Keycloak in dev mode:** `start-dev` with a realm auto-imported from `infra/keycloak/`. Production requires TLS and an HA Keycloak cluster.

---

## 12. Extensibility

The architecture is designed for minimal coupling. Key extension points:

| What to extend | Where to change | Notes |
|----------------|-----------------|-------|
| Real ML model | `client/mock_model.py` + `client/client.py` | Replace `MockModel` with a PyTorch/TF `NumPyClient`; the server aggregation is model-agnostic |
| Additional scoring rules | `trust/scoring.py` → `update_score()` | Rules 1–5 are clearly delimited; add Rule 6+ after the Rule 5 block |
| PostgreSQL trust DB | `DB_URL` env var + `trust/schema.sql` | Schema uses ANSI SQL; swap `sqlite3` calls for SQLAlchemy sessions |
| Additional OPA policies | `policy/fl_policy.rego` | OPA bundles support multiple policy files; add data-quality or geographic checks |
| New compliance flag types | `server/assurance.py` → `_build_report()` | Add a list comprehension in the `flags` builder |
| Differential privacy | Wrap `aggregate_fit()` in `server/server.py` | Insert DP noise/clipping before `TrustWeightedFedAvg` returns weights |
| Real-time dashboard | Mount `logs/` into Grafana + Loki | JSONL logs are structured; no code changes required |

---

## 13. Academic References

The design of Project North Star draws on the following literature. References are particularly relevant for situating the per-client norm history fix (§5b) and trust-weighted aggregation (§5c) in the broader FL security literature.

1. **McMahan, H. B., et al. (2017).** Communication-Efficient Learning of Deep Networks from Decentralized Data. *AISTATS 2017.* — Original FedAvg algorithm.

2. **Blanchard, P., et al. (2017).** Machine Learning with Adversaries: Byzantine Tolerant Gradient Descent. *NeurIPS 2017.* — Foundational Byzantine fault tolerance in distributed ML; motivates norm-based anomaly detection.

3. **Fung, C., et al. (2020).** The Limitations of Federated Learning in Sybil Settings. *RAID 2020.* — Demonstrates that contribution-based defences can be gamed; motivates the anomaly floor and Rule 5 design.

4. **Cao, X., et al. (2021).** FLTrust: Byzantine-Robust Federated Learning via Trust Bootstrapping. *NDSS 2021.* — Closest prior work to this project's EMA scoring; requires a server-held clean dataset, which this project avoids.

5. **Mothukuri, V., et al. (2021).** A Survey on Security and Privacy of Federated Learning. *Future Generation Computer Systems, 115.* — Taxonomy of FL attack surfaces; §3.3 covers norm-based detection and shared-baseline pitfalls.

6. **Open Policy Agent Documentation.** https://www.openpolicyagent.org/docs/ — Rego language reference; `fl_policy.rego` follows OPA's recommended admission control pattern.

---

*Project North Star — internal research use only.*

