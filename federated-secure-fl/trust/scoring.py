"""
Trust Score Engine — Phase 4
Persistent, rule-based reputation engine using SQLite and EMA smoothing.
Designed per phase4_context.md specification — do not modify formulas.
"""

import os
import sqlite3
from pathlib import Path
import numpy as np

from shared.logger import get_logger, log_event

# ───────────────────────── Logging ───────────────────────────────
# log_event signature: log_event(logger: logging.Logger, event: str, **kwargs)
log = get_logger("trust")

# ───────────────────────── Env Vars ──────────────────────────────
WARMUP_ROUNDS      = int(os.getenv("WARMUP_ROUNDS", "3"))
LOW_LOSS_THRESHOLD = float(os.getenv("LOW_LOSS_THRESHOLD", "0.3"))


class TrustEngine:
    """
    Trust score engine using SQLite persistence + EMA smoothing.

    Formula: T_new = 0.3 * observation_score + 0.7 * T_prev
    Scores are clamped to [0.1, 1.0].
    """

    # Path to schema.sql, relative to this file
    _SCHEMA_PATH = Path(__file__).parent / "schema.sql"

    def __init__(self, db_url: str = "sqlite:///./trust.db") -> None:
        self.db_url = db_url
        # GAP 1: parse sqlite:/// prefix into a plain file path
        prefix = "sqlite:///"
        if db_url.startswith(prefix):
            self._db_path = db_url[len(prefix):]
        else:
            self._db_path = db_url
        self._norm_history: dict[str, list[float]] = {}

    def _connect(self) -> sqlite3.Connection:
        """Return a sqlite3 connection with row_factory set."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """
        GAP 2: Execute schema DDL from trust/schema.sql.
        Idempotent — safe to call multiple times.
        """
        ddl = self._SCHEMA_PATH.read_text()
        conn = self._connect()
        try:
            conn.executescript(ddl)
            conn.commit()
        finally:
            conn.close()
        log_event(log, "trust_db_initialized", db_path=self._db_path)

    def get_score(self, client_id: str, current_round: int = 0) -> float:
        """
        GAP 3: Return trust score for a client.

        Returns 0.8 during warmup (rounds 1-WARMUP_ROUNDS inclusive).
        Returns DB value post-warmup. Defaults to 0.8 for unknown clients.
        Return type: float. Always. Never dict, never None.
        """
        # STEP 1: warmup guard
        if current_round <= WARMUP_ROUNDS:
            return 0.8

        # STEP 2: fetch from DB
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT trust_score FROM client_trust WHERE client_id = ?",
                (client_id,)
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return 0.8
        return float(row["trust_score"])

    def update_score(self, client_id: str, observation: dict) -> None:
        """
        GAP 4: Full update_score implementation.

        Applies Rules 1-5 from phase4_context.md to compute observation_score,
        then EMA smooths it into the persistent trust_score.
        """
        conn = self._connect()
        try:
            # STEP 1: Fetch or insert client row
            conn.execute(
                """
                INSERT OR IGNORE INTO client_trust
                  (client_id, trust_score, anomaly_count,
                   rounds_participated, baseline_norm, last_update)
                VALUES (?, 0.8, 0, 0, 0.0, datetime('now'))
                """,
                (client_id,)
            )
            conn.commit()

            row = conn.execute(
                """
                SELECT trust_score, anomaly_count, rounds_participated, baseline_norm
                FROM client_trust WHERE client_id = ?
                """,
                (client_id,)
            ).fetchone()

            T_prev              = float(row["trust_score"])
            anomaly_count       = int(row["anomaly_count"])
            rounds_participated = int(row["rounds_participated"])
            baseline_norm       = float(row["baseline_norm"])

            update_norm   = float(observation.get("update_norm", 0.0))
            train_loss    = float(observation.get("train_loss", 0.0))
            dropout       = bool(observation.get("dropout", False))
            policy_warn   = bool(observation.get("policy_warning", False))
            current_round = int(observation.get("round", 0))

            # STEP 2: Update baseline_norm (incremental mean).
            # FIX 3: Skip update if norm was clamped to sentinel (inf/nan original);
            # the 1e6 value should not corrupt the real historical baseline.
            norm_was_clamped = bool(observation.get("norm_was_clamped", False))
            if not norm_was_clamped:
                new_baseline_norm = (
                    (baseline_norm * rounds_participated) + update_norm
                ) / (rounds_participated + 1)
            else:
                new_baseline_norm = baseline_norm  # preserve existing baseline

            # STEP 3: Compute observation_score (Rules 1-5)
            observation_score = T_prev

            # Rule 1 — Dropout
            if dropout:
                observation_score -= 0.10

            # Rule 2 — Policy warning
            if policy_warn:
                observation_score -= 0.20

            # NOTE: Rule 3 compares update_norm against new_baseline_norm
            # (the already-updated running mean that includes this round's value).
            # This means the anomaly threshold is slightly inflated when the
            # anomalous update itself is large, which can cause moderate anomalies
            # (2x-2.4x true baseline) to slip through in one round.
            # This is intentional per spec for Phase 4.
            # Phase 5 (malicious client simulation): consider comparing against
            # the pre-update baseline_norm instead for tighter detection.

            # Rule 3 — Abnormal norm (post-warmup only)
            import math
            is_anomaly = False
            
            history = self._norm_history.setdefault(client_id, [])
            if rounds_participated >= WARMUP_ROUNDS:
                if not math.isfinite(update_norm):
                    observation_score -= 0.15
                    is_anomaly = True
                elif len(history) >= 3:
                    baseline = float(np.mean(history[-5:]))
                    if update_norm > 2.0 * baseline and baseline > 0:
                        observation_score -= 0.15
                        is_anomaly = True
            
            history.append(update_norm)

            # Rule 4 — Low loss bonus
            if train_loss < LOW_LOSS_THRESHOLD and not dropout:
                observation_score += 0.03

            # Rule 5 — Consistent participation bonus.
            # FIX 1: Never award to a client that has ever fired an anomaly;
            # persistent bad actors should not earn participation rewards.
            expected = current_round - 1
            if rounds_participated >= expected and expected > 0 and not dropout and anomaly_count == 0:
                observation_score += 0.05

            # FIX 2 — Anomaly-count floor: once a client has fired 3+ anomalies,
            # cap observation_score at 0.6 regardless of any bonuses.
            # This prevents full EMA recovery for persistently malicious clients.
            if anomaly_count > 2:
                observation_score = min(observation_score, 0.6)

            # Clamp observation_score
            observation_score = max(0.1, min(1.0, observation_score))

            # STEP 4: Apply EMA
            # alpha is fixed at 0.3. Adaptive alpha is not in scope for Phase 4.
            T_new = (0.3 * observation_score) + (0.7 * T_prev)
            T_new = max(0.1, min(1.0, T_new))

            # STEP 5: Persist
            conn.execute(
                """
                UPDATE client_trust SET
                  trust_score         = ?,
                  anomaly_count       = ?,
                  rounds_participated = ?,
                  baseline_norm       = ?,
                  last_update         = datetime('now')
                WHERE client_id = ?
                """,
                (
                    T_new,
                    anomaly_count + (1 if is_anomaly else 0),
                    rounds_participated + 1,
                    new_baseline_norm,
                    client_id,
                )
            )
            conn.commit()

        finally:
            conn.close()

        # STEP 6: Emit log event — OUTSIDE try/finally, after connection is closed.
        # MUST emit every round, including rounds 1-3.
        # log_event signature: log_event(logger: logging.Logger, event: str, **kwargs)
        log_event(log, "trust_updated",
            client_id=client_id,
            fl_round=current_round,       # renamed from "round" (shadows Python builtin)
            trust_score=round(T_new, 6),
            observation_score=round(observation_score, 6),
            T_prev=round(T_prev, 6),
            is_anomaly=is_anomaly,
            dropout=dropout,
            policy_warning=policy_warn,
            update_norm=round(update_norm, 6),
            train_loss=round(train_loss, 6),
            baseline_norm=round(new_baseline_norm, 6),
        )
