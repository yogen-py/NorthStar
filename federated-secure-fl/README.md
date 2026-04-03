# 🌟 Project North Star

**Secure Federated Learning Pipeline** — privacy-preserving ML across distributed hospital nodes with dynamic trust scoring, policy-based access control, and Byzantine fault tolerance.

## Architecture

```
┌─────────────┐     gRPC      ┌──────────────┐
│ Hospital A  │◄──────────────►│              │
│ Hospital B  │◄──────────────►│  FL Server   │──► Trust DB (SQLite/Postgres)
│ Hospital C  │◄──────────────►│  (Flower)    │
└─────────────┘               └──────┬───────┘
                                     │
                              ┌──────┴───────┐
                              │  Middleware   │
                              │  (FastAPI)    │
                              └──────┬───────┘
                                     │
                     ┌───────────────┼───────────────┐
                     │               │               │
               ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐
               │  Keycloak  │  │    OPA    │  │ PostgreSQL│
               │  (AuthN)   │  │  (AuthZ)  │  │  (Trust)  │
               └────────────┘  └───────────┘  └───────────┘
```

## Phase Roadmap

| Phase | Objective | Status |
|-------|-----------|--------|
| **0** | Scaffold & smoke test | ✅ Current |
| **1** | End-to-end FL pipeline (FedAvg on MNIST) | ⬜ |
| **2** | JWT authentication via Keycloak | ⬜ |
| **3** | OPA policy enforcement + live client revocation | ✅ Current |
| **4** | Trust scoring engine integration | ⬜ |
| **5** | Byzantine attack simulation & defense | ⬜ |
| **6** | Dashboard, monitoring & final hardening | ⬜ |

## Quickstart

### Prerequisites
- Docker & Docker Compose v2+
- ~4 GB free RAM (PyTorch + Keycloak)

### Run

```bash
cd infra
docker compose up --build
```

This starts: `fl-server`, `fl-middleware`, 3 hospital clients, Keycloak, OPA, and PostgreSQL.

### Smoke Tests

```bash
# 1. Build all images
docker compose build

# 2. Start core services (server + 3 clients)
docker compose up fl-server fl-middleware hospital_a hospital_b hospital_c

# 3. Health check (in another terminal)
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# 4. Check server logs for round completion
docker compose logs fl-server | grep '"round"'
```

### Attack Simulation (Phase 5+)

```bash
# Start malicious client alongside honest clients
docker compose --profile attack up malicious_client
```

## Project Structure

```
federated-secure-fl/
├── server/           # Flower FL server + FastAPI middleware
├── client/           # Flower client with MNIST CNN
├── trust/            # Trust score engine + DB schema
├── policy/           # OPA Rego policies
├── experiments/      # Attack simulations (gated)
├── infra/            # Docker Compose + Keycloak config
├── logs/             # Runtime logs
├── .env.example      # Environment template
└── README.md
```

## Configuration

Copy `.env.example` to `infra/.env` and customize:

```bash
cp .env.example infra/.env
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `FLOWER_NUM_ROUNDS` | `5` | Number of FL training rounds |
| `SERVER_ADDRESS` | `fl-server:9080` | Flower gRPC address |
| `DB_URL` | `sqlite:///./trust.db` | Trust database URL |
| `KC_ADMIN` | `admin` | Keycloak admin username |
| `ATTACK_MODE` | `noise` | Attack type: `noise` or `sign_flip` |

## License

Private — internal use only.
