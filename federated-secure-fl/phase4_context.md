# PROJECT NORTH STAR — PHASE 4 CONTEXT FILE
# This file is the single source of truth for the coding agent.
# Read this entire file before writing any code.
# All decisions about formulas, penalties, bonuses, thresholds,
# and data flow are defined here. Do not infer anything not written here.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART A — WHAT ALREADY EXISTS IN THE CODEBASE


The following files EXIST and must NOT be rebuilt or redesigned.
Only the gaps listed in PART C are to be filled.

FILE: shared/logger.py
  PURPOSE: Structured JSON logging to trust.jsonl.
  KEY FUNCTION:
    log_event(event_type: str, payload: dict) -> None
    Writes one JSON line per call to logs/<run>/trust.jsonl.
  RULE: Every new event in Phase 4 MUST call log_event().
        Never use print() for events.

FILE: trust/schema.sql
  PURPOSE: Defines the SQLite table for trust score persistence.
  EXACT DDL (do not alter this):
    CREATE TABLE IF NOT EXISTS client_trust (
        client_id            TEXT PRIMARY KEY,
        trust_score          REAL    DEFAULT 0.8,
        anomaly_count        INTEGER DEFAULT 0,
        rounds_participated  INTEGER DEFAULT 0,
        baseline_norm        REAL    DEFAULT 0.0,
        last_update          TIMESTAMP
    );

FILE: trust/scoring.py
  PURPOSE: Houses the TrustEngine class.
  CURRENT STATE: Class exists with stubs or partial implementations.
  EXISTING METHOD SIGNATURES (do not rename or remove):
    __init__(self, db_url: str)
    init_db(self)
    get_score(self, client_id: str)                    ← needs patching
    update_score(self, client_id: str, observation: dict)  ← needs patching

FILE: server/server.py
  PURPOSE: Flower FL server + HITL HTTP gate.
  RELEVANT CLASSES AND METHODS:
    class LoggingFedAvg(fl.server.strategy.FedAvg):
      aggregate_fit(self, server_round, results, failures)
        - Already iterates over results (client_proxy, fit_res) pairs
        - Already computes update_norm per client
        - Already emits weights_received log_event per client
        - Has self._round_clients list with hardcoded trust_score=0.8
          (this is the Phase 4 replacement target)
      aggregate_evaluate(self, server_round, results, failures)
        - Already feeds round summary to HITL gate (do not change)
  HTTP SERVER: Flask app already running on port 9081 (HITL gate).
    Existing routes handle operator approve/reject/stop.
    One NEW route will be added in Phase 4 (see PART E).

FILE: middleware.py
  PURPOSE: OPA policy enforcement + Keycloak JWT verification.
  RELEVANT BEHAVIOUR:
    When a client is denied by OPA, middleware already calls:
      log_event("admit_decision", {
          "result": "rejected",
          "rejection_reason": "policy_denied",
          "client_id": <client_id>
      })
    After Phase 4, one non-blocking HTTP POST will be added
    immediately after this log_event call (see PART E).


PART B — CORE FORMULAS (EXACT, MECHANICAL, NO AMBIGUITY)

B1. OBSERVATION SCORE — INTUITION
  The observation_score is a temporary, single-round signal.
  It is NOT persisted. It feeds into EMA and is then discarded.
  Starting from T_prev means: neutral behaviour = no score change.
  Only deviations (penalties/bonuses) move the score.

B2. EMA — INTUITION
  With alpha=0.3, each new observation contributes only 30% to T_new.
  The remaining 70% is the client's historical reputation (T_prev).
  This means:
    - A single bad round barely moves the score (by 0.3 × penalty × 0.3)
    - A client needs ~8 consecutive bad rounds to go from 0.8 to near 0.1
    - A client needs ~5 consecutive good rounds to recover from 0.4 to 0.7
  This is intentional: trust is hard to lose and slow to recover.

  Worked example (policy_warning fires, T_prev=0.8):
    observation_score = 0.8 - 0.20 = 0.60  (clamped: still 0.60)
    T_new = (0.3 × 0.60) + (0.7 × 0.80)
          = 0.18 + 0.56
          = 0.74
  One denial drops trust from 0.80 → 0.74, not to 0.60.
  This is correct behaviour, not a bug.

B3. BASELINE NORM — INTUITION
  During warmup (rounds 1-3), baseline_norm is being established.
  If a mock client's update_norm is consistently ~1.4,
  then baseline_norm stabilises around 1.4 by round 3.
  The anomaly threshold is then: 1.4 × 2.0 = 2.8.
  Any round where update_norm > 2.8 triggers the -0.15 penalty.
  For mocked numpy arrays with fixed magnitude, this will rarely
  fire unless you deliberately inject noise (Phase 5 malicious client).

B4. WARMUP — INTUITION
  get_score() returns 0.8 during rounds 1-3 because baseline_norm
  is still being computed. Using a volatile early score would skew
  aggregation before there is enough history to trust the signal.
  update_score() still runs so that by round 4, baseline_norm is
  already a 3-round average — ready for anomaly detection immediately.



B1. OBSERVATION SCORE CALCULATION


An observation_score is computed fresh each round from the incoming
observation dict. It represents what the trust score WOULD be if we
applied all signals from this round only, before EMA smoothing.

  Start: observation_score = T_prev (the client's current trust score)

  Apply these 5 rules IN ORDER. Multiple rules can fire in one call.

  RULE 1 — Dropout:
    IF observation["dropout"] == True:
      observation_score -= 0.10

  RULE 2 — Policy warning:
    IF observation.get("policy_warning", False) == True:
      observation_score -= 0.20

  RULE 3 — Abnormal norm (post-warmup only):
    This rule fires ONLY when ALL THREE conditions are true:
      a) observation["update_norm"] > (2.0 * baseline_norm)
      b) baseline_norm > 0.0
      c) rounds_participated >= WARMUP_ROUNDS
    IF all three are true:
      observation_score -= 0.15
      set is_anomaly = True
    ELSE:
      set is_anomaly = False

  RULE 4 — Low loss bonus:
    IF observation["train_loss"] < LOW_LOSS_THRESHOLD
    AND observation["dropout"] == False:
      observation_score += 0.03

  RULE 5 — Consistent participation bonus:
    expected = observation["round"] - 1
    IF rounds_participated >= expected
    AND expected > 0
    AND observation["dropout"] == False:
      observation_score += 0.05

  CLAMP observation_score to [0.1, 1.0]:
    observation_score = max(0.1, min(1.0, observation_score))


B2. EMA FORMULA


  T_new = (0.3 * observation_score) + (0.7 * T_prev)

  alpha = 0.3 is FIXED. It is NOT configurable. It is NOT adaptive.
  Add this comment wherever EMA is implemented:
    # alpha is fixed at 0.3. Adaptive alpha is not in scope for Phase 4.

  After EMA, clamp T_new to [0.1, 1.0]:
    T_new = max(0.1, min(1.0, T_new))

  Clamping to 0.1 (not 0.0) is intentional.
  A client with trust_score = 0.1 still contributes minimally.
  A client is never completely zeroed out by the trust engine.


B3. BASELINE NORM (RUNNING MEAN)


  baseline_norm tracks the average update_norm across all rounds
  a client has participated in, including warmup rounds.

  Formula (incremental mean, runs every round including warmup):
    new_baseline_norm = (
        (baseline_norm * rounds_participated) + observation["update_norm"]
    ) / (rounds_participated + 1)

  If observation["dropout"] == True, update_norm = 0.0.
  This is intentional — it lowers the baseline, reflecting real history.

  The abnormal_norm check (Rule 3 above) compares:
    observation["update_norm"] > 2.0 * new_baseline_norm
  But it only fires if rounds_participated >= WARMUP_ROUNDS.


B4. WARMUP GUARD


  WARMUP_ROUNDS = int(os.getenv("WARMUP_ROUNDS", "3"))

  During rounds 1, 2, 3 (i.e., current_round <= WARMUP_ROUNDS):
    - update_score() STILL RUNS. Scores are computed. DB is written.
    - get_score() RETURNS 0.8 regardless of what is in the DB.
    - The aggregation loop therefore uses 0.8 for all clients in round 1-3.
    - This prevents skewed aggregation before baseline_norm is established.

  From round 4 onwards (current_round > WARMUP_ROUNDS):
    - get_score() RETURNS the actual trust_score from DB.


B5. PHASE 5 AGGREGATION FORMULA (for context — implement in Phase 5 only)


  This formula is NOT implemented in Phase 4.
  It is documented here so Phase 4 outputs are correctly shaped for it.

  Given clients [c1, c2, c3] with trust scores [T1, T2, T3]
  and sample counts [n1, n2, n3]:

    denom         = (n1*T1) + (n2*T2) + (n3*T3)
    weight_ci     = (ni * Ti) / denom

  The aggregated model update = sum(weight_ci * update_ci)

  Phase 4 MUST ensure get_score() returns a bare float.
  Phase 5 will call get_score() and pass the result directly into
  this formula. No unwrapping, no dict access.


PART C — GAPS TO FILL IN trust/scoring.py


Fill exactly these 4 gaps. Do not change anything else.


GAP 1: __init__ — parse db_url into a file path


  Input:  self.db_url = "sqlite:///./trust.db"
  Output: self._db_path = "./trust.db"

  Rule: strip the "sqlite:///" prefix.
        If the prefix is absent, use db_url as-is.


GAP 2: init_db() — execute schema DDL


  Steps (in order):
    1. Open trust/schema.sql and read full contents into a string.
    2. Open sqlite3 connection to self._db_path.
    3. Call conn.executescript(ddl_string).
    4. Call conn.commit().
    5. Close connection.
    6. Call log_event("trust_db_initialized", {"db_path": self._db_path})

  This method must be idempotent (safe to call multiple times).
  The DDL uses CREATE TABLE IF NOT EXISTS so no special guard needed.


GAP 3: get_score() — add current_round param and warmup guard


  New signature:
    def get_score(self, client_id: str, current_round: int = 0) -> float:

  Decision tree (follow in order, return immediately on match):

    STEP 1: if current_round <= WARMUP_ROUNDS:
                return 0.8

    STEP 2: open sqlite3 connection to self._db_path
            SELECT trust_score FROM client_trust WHERE client_id = ?
            if no row found: return 0.8
            if row found:    return float(row["trust_score"])
            close connection

  Return type: float. Always. Never a dict, never None.


GAP 4: update_score() — full implementation


  Signature (unchanged):
    def update_score(self, client_id: str, observation: dict) -> None

  The observation dict contains:
    {
      "round":          int,    # current FL round, 1-indexed
      "update_norm":    float,  # L2 norm of client's weight update
      "train_loss":     float,  # client's reported training loss
      "dropout":        bool,   # True if client missed this round
      "policy_warning": bool,   # OPTIONAL key — treat absence as False
    }

  Steps (follow in strict order):

    STEP 1 — Fetch or insert client row:
      INSERT OR IGNORE INTO client_trust
        (client_id, trust_score, anomaly_count,
         rounds_participated, baseline_norm, last_update)
      VALUES (?, 0.8, 0, 0, 0.0, datetime('now'))

      Then SELECT trust_score, anomaly_count, rounds_participated,
                   baseline_norm
           FROM client_trust WHERE client_id = ?

      Assign: T_prev, anomaly_count, rounds_participated, baseline_norm

    STEP 2 — Update baseline_norm (always runs, every round):
      new_baseline_norm = (
          (baseline_norm * rounds_participated) + observation["update_norm"]
      ) / (rounds_participated + 1)

    STEP 3 — Compute observation_score:
      Apply Rules 1-5 from PART B1.
      Use: T_prev, new_baseline_norm, rounds_participated,
           WARMUP_ROUNDS, LOW_LOSS_THRESHOLD

    STEP 4 — Apply EMA:
      T_new = (0.3 * observation_score) + (0.7 * T_prev)
      T_new = max(0.1, min(1.0, T_new))

    STEP 5 — Persist:
      UPDATE client_trust SET
        trust_score         = T_new,
        anomaly_count       = anomaly_count + (1 if is_anomaly else 0),
        rounds_participated = rounds_participated + 1,
        baseline_norm       = new_baseline_norm,
        last_update         = datetime('now')
      WHERE client_id = ?
      Commit and close.

    STEP 6 — Emit log event:
      log_event("trust_updated", {
        "client_id":         client_id,
        "round":             observation["round"],
        "trust_score":       T_new,
        "observation_score": observation_score,
        "T_prev":            T_prev,
        "is_anomaly":        is_anomaly,
        "dropout":           observation["dropout"],
        "policy_warning":    observation.get("policy_warning", False),
        "update_norm":       observation["update_norm"],
        "train_loss":        observation["train_loss"],
        "baseline_norm":     new_baseline_norm,
      })

      This log event MUST emit every round, including rounds 1-3.


PART D — CHANGES TO server/server.py (3 INTEGRATION POINTS)



D1: Module-level setup (before fl.server.start_server())


  Add imports:
    from trust.scoring import TrustEngine
    import os

  Add module-level variable:
    current_round: int = 0   # updated each round, used by policy-warning route

  Add before start_server():
    trust_engine = TrustEngine(
        db_url=os.getenv("DB_URL", "sqlite:///./trust.db")
    )
    trust_engine.init_db()

  Change strategy instantiation to inject trust_engine:
    strategy = LoggingFedAvg(trust_engine=trust_engine, ...)


D2: LoggingFedAvg.__init__()


  Change signature from:
    def __init__(self, **kwargs):
  To:
    def __init__(self, trust_engine: TrustEngine, **kwargs):

  Add to body:
    self.trust_engine = trust_engine
    self._previous_round_client_ids: set = set()


D3: Inside aggregate_fit()


  AFTER the existing weights_received log_event for each client,
  add this call (use the same client_id variable already in the loop):

    self.trust_engine.update_score(client_id, {
        "round":       server_round,
        "update_norm": update_norm,
        "train_loss":  fit_res.metrics.get("train_loss", 0.0),
        "dropout":     False,
    })

  AFTER the loop, add dropout detection:

    current_round_client_ids = {
        client_proxy.cid for client_proxy, _ in results
    }
    for dropped_id in (self._previous_round_client_ids
                       - current_round_client_ids):
        self.trust_engine.update_score(dropped_id, {
            "round":       server_round,
            "update_norm": 0.0,
            "train_loss":  0.0,
            "dropout":     True,
        })
    self._previous_round_client_ids = current_round_client_ids

    global current_round
    current_round = server_round

  REPLACE the self._round_clients hardcoded trust_score=0.8 with:

    self._round_clients = [
        {
            "client_id":   cid,
            "trust_score": self.trust_engine.get_score(
                               cid,
                               current_round=server_round
                           ),
        }
        for cid in current_round_client_ids
    ]


PART E — POLICY WARNING CROSS-CONTAINER SIGNAL


PROBLEM:
  middleware.py and server.py run in separate Docker containers.
  When OPA denies a client, the trust engine in server.py has no way
  to know. They cannot share Python objects.

SOLUTION:
  Add one new HTTP route to the EXISTING Flask app on port 9081.
  middleware.py POSTs to this route after a denial.
  No new Docker service. No new port.


E1: New route in server.py (add to existing Flask app)


  @app.route("/trust/policy-warning", methods=["POST"])
  def policy_warning_route():
      data = request.get_json(silent=True)
      if not data or "client_id" not in data:
          return jsonify({"error": "client_id required"}), 400

      client_id = data["client_id"]
      reason    = data.get("reason", "policy_denied")

      trust_engine.update_score(client_id, {
          "round":          current_round,
          "update_norm":    0.0,
          "train_loss":     0.0,
          "dropout":        False,
          "policy_warning": True,
      })

      log_event("policy_warning_applied", {
          "client_id": client_id,
          "reason":    reason,
          "round":     current_round,
      })

      return jsonify({"status": "ok", "client_id": client_id}), 200

  NOTE: trust_engine and current_round here are the module-level
  variables defined in D1.

─────────────────────────────
E2: Non-blocking POST in middleware.py
─────────────────────────────

  Find the existing admit_decision log_event call for rejections.
  IMMEDIATELY AFTER it, add:

    _server_host = os.getenv("SERVER_HOST", "server")
    try:
        requests.post(
            f"http://{_server_host}:9081/trust/policy-warning",
            json={"client_id": client_id, "reason": "policy_denied"},
            timeout=2,
        )
    except Exception:
        pass

  Rules:
    - try/except MUST catch bare Exception (all exceptions).
    - timeout MUST be 2 seconds.
    - On ANY failure: do nothing. No log. No retry. No raise.
    - Move imports (requests, os) to top of middleware.py if not there.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART F — ENVIRONMENT VARIABLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Add to docker-compose.yml, server service:
  environment:
    - DB_URL=sqlite:///./trust.db
    - WARMUP_ROUNDS=3
    - LOW_LOSS_THRESHOLD=0.3

Add to docker-compose.yml, middleware service:
  environment:
    - SERVER_HOST=server

Read in trust/scoring.py at module level:
  WARMUP_ROUNDS      = int(os.getenv("WARMUP_ROUNDS", "3"))
  LOW_LOSS_THRESHOLD = float(os.getenv("LOW_LOSS_THRESHOLD", "0.3"))

Read in server/server.py at module level:
  DB_URL        = os.getenv("DB_URL", "sqlite:///./trust.db")
  WARMUP_ROUNDS = int(os.getenv("WARMUP_ROUNDS", "3"))

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART G — COMPLETE DATA FLOW (EVERY ROUND)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is what happens each FL round after Phase 4 is complete:

NORMAL ROUND (no denial):
  1. Flower calls aggregate_fit(server_round, results, failures)
  2. For each (client_proxy, fit_res) in results:
       a. Compute update_norm           [existing logic, unchanged]
       b. Emit weights_received event   [existing logic, unchanged]
       c. Call trust_engine.update_score(client_id, {...})
            → Computes observation_score via Rules 1-5
            → Applies EMA → T_new
            → Writes T_new to trust.db
            → Emits trust_updated to trust.jsonl
  3. Detect dropouts:
       Any client in _previous_round_client_ids but NOT in this round
       → Call trust_engine.update_score(dropped_id, {"dropout": True, ...})
  4. Build self._round_clients:
       trust_engine.get_score(cid, current_round=server_round)
       → Returns 0.8 for rounds 1-3
       → Returns DB value for rounds 4+
  5. HITL gate uses self._round_clients for display

DENIAL ROUND (OPA rejects a client):
  1. middleware.py detects policy violation
  2. middleware.py logs admit_decision result="rejected"
  3. middleware.py POSTs to http://server:9081/trust/policy-warning
  4. server.py route calls trust_engine.update_score(policy_warning=True)
       → Applies -0.20 penalty via Rule 2
       → EMA applied → T_new written to trust.db
       → policy_warning_applied event emitted to trust.jsonl
  5. That client does not appear in results for this round
       → No update_score call from aggregate_fit
       → Dropout detection may fire if they were in the previous round

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART H — HARD CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DO NOT:
  ✗ Add PyTorch or real ML training
  ✗ Rebuild or redesign TrustEngine — fill only the 4 gaps in PART C
  ✗ Add new Docker services or new ports
  ✗ Make alpha configurable or adaptive (it is fixed at 0.3)
  ✗ Switch SQLite to any other database
  ✗ Modify shared/logger.py
  ✗ Change existing Flower strategy behaviour
  ✗ Change existing HITL gate routes (/approve, /reject, /stop)
  ✗ Return a dict from get_score() — return type is always float

MUST:
  ✓ update_score() runs every round including rounds 1, 2, 3
  ✓ get_score() returns exactly 0.8 for rounds 1, 2, 3
  ✓ trust.jsonl receives trust_updated events from round 1
  ✓ Every new log_event() payload includes "round" key
  ✓ get_score() return type is float
  ✓ policy-warning POST in middleware is non-blocking (bare except + pass)
  ✓ WARMUP_ROUNDS is read from env var, default 3

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART I — VERIFICATION CHECKLIST (run after implementation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

V1 — trust.jsonl has events from round 1:
  Command: grep '"event_type": "trust_updated"' logs/<run>/trust.jsonl | head -5
  PASS: Lines exist with "round": 1
  FAIL: No lines, or earliest round > 1

V2 — HITL shows 0.8 during warmup:
  Command: curl http://localhost:9081/status   (during round 1, 2, or 3)
  PASS: All clients show "trust_score": 0.8
  FAIL: Any client shows trust_score != 0.8 during rounds 1-3

V3 — Live scores appear after warmup:
  Command: curl http://localhost:9081/status   (during round 4+)
  PASS: At least one client shows trust_score != 0.8
  FAIL: All clients still show 0.8 after round 4

V4 — SQLite populated correctly:
  Command: sqlite3 trust.db
    "SELECT client_id, trust_score, rounds_participated,
            baseline_norm, anomaly_count FROM client_trust;"
  PASS after 5 rounds:
    - One row per mock client
    - rounds_participated = 5
    - baseline_norm > 0.0
    - trust_score in [0.1, 1.0]
  FAIL: No rows, or rounds_participated = 0, or baseline_norm = 0.0

V5 — Policy warning endpoint works:
  Command:
    curl -s -X POST http://localhost:9081/trust/policy-warning \
         -H "Content-Type: application/json" \
         -d '{"client_id": "mock-client-1", "reason": "policy_denied"}'
  PASS: Response is {"status": "ok", "client_id": "mock-client-1"}
        AND trust.jsonl has a policy_warning_applied event
        AND trust.db shows a lower trust_score for mock-client-1
  FAIL: 400/404, no log event, or score unchanged

V6 — Dropout detection works:
  Action: Comment out one mock client's fit() response for one round.
  Command: grep '"dropout": true' logs/<run>/trust.jsonl
  PASS: One line for the silenced client with dropout=true
        AND trust_score is lower than previous round
  FAIL: No dropout=true line

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
END OF CONTEXT FILE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
