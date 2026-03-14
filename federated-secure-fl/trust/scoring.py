"""
Trust Score Engine — Phase 0
Computes and updates client trust scores using Exponential Moving Average (EMA).
"""

import time
from typing import Dict, Optional

from shared.logger import get_logger, log_event

# ───────────────────────── Logging ───────────────────────────────
log = get_logger("trust")

# ───────────────────────── Constants ─────────────────────────────
DEFAULT_SCORE = 0.8
MIN_SCORE = 0.1
MAX_SCORE = 1.0
EMA_ALPHA = 0.3  # weight for current observation

# Observation penalty/bonus values
OBSERVATION_WEIGHTS: Dict[str, float] = {
    # Penalties (lower is worse)
    "abnormal_norm": 0.2,
    "dropout": 0.3,
    "policy_warning": 0.4,
    # Bonuses (higher is better)
    "consistent_participation": 0.9,
}

_PENALTY_EVENTS = {"abnormal_norm", "dropout", "policy_warning"}
_BONUS_EVENTS   = {"consistent_participation"}


class TrustEngine:
    """
    Trust score engine using EMA (Exponential Moving Average).

    Formula: T_new = EMA_ALPHA * O_current + (1 - EMA_ALPHA) * T_prev
    Scores are clamped to [MIN_SCORE, MAX_SCORE].
    """

    def __init__(self) -> None:
        self._scores: Dict[str, float] = {}
        self._metadata: Dict[str, Dict] = {}

    def get_score(self, client_id: str) -> float:
        """
        Get the current trust score for a client.

        Args:
            client_id: Unique identifier for the client.

        Returns:
            Current trust score (defaults to DEFAULT_SCORE for new clients).
        """
        return self._scores.get(client_id, DEFAULT_SCORE)

    def update_score(self, client_id: str, observation: dict) -> float:
        """
        Update a client's trust score based on an observation.

        Args:
            client_id: Unique identifier for the client.
            observation: Dict with at least an 'event' key matching
                         one of the OBSERVATION_WEIGHTS keys.

        Returns:
            Updated trust score.
        """
        old_score = self.get_score(client_id)
        event = observation.get("event", "")

        if event not in OBSERVATION_WEIGHTS:
            log.warning(f"Unknown observation event: {event}")
            return old_score

        observation_value = OBSERVATION_WEIGHTS[event]

        # EMA formula: T_new = alpha * O_current + (1 - alpha) * T_prev
        new_score = EMA_ALPHA * observation_value + (1 - EMA_ALPHA) * old_score
        new_score = max(MIN_SCORE, min(MAX_SCORE, new_score))

        self._scores[client_id] = new_score

        # Track metadata
        if client_id not in self._metadata:
            self._metadata[client_id] = {
                "anomaly_count": 0,
                "rounds_participated": 0,
            }

        meta = self._metadata[client_id]
        meta["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if event in _PENALTY_EVENTS:
            meta["anomaly_count"] = meta.get("anomaly_count", 0) + 1

        if event in _BONUS_EVENTS:
            meta["rounds_participated"] = meta.get("rounds_participated", 0) + 1

        penalties = [event] if event in _PENALTY_EVENTS else []
        bonuses   = [event] if event in _BONUS_EVENTS   else []

        log_event(log, "trust_updated",
            client_id=client_id,
            round=observation.get("round"),
            old_score=round(old_score, 4),
            new_score=round(new_score, 4),
            delta=round(new_score - old_score, 4),
            penalties_applied=penalties,
            bonuses_applied=bonuses,
            anomaly_detected=len(penalties) > 0,
            update_norm=observation.get("update_norm"),
            clamped=new_score in (MIN_SCORE, MAX_SCORE),
        )

        return new_score

    def get_metadata(self, client_id: str) -> Optional[Dict]:
        """Get metadata for a client."""
        return self._metadata.get(client_id)

    def get_all_scores(self) -> Dict[str, float]:
        """Get all client trust scores."""
        return dict(self._scores)


# ───────────────────────── Main ─────────────────────────────────

if __name__ == "__main__":
    # Quick smoke test
    engine = TrustEngine()

    # New client starts at 0.8
    assert engine.get_score("test_client") == DEFAULT_SCORE

    # Consistent participation bonus
    score = engine.update_score("test_client", {"event": "consistent_participation"})
    log.info(f"After participation: {score}")

    # Abnormal norm penalty
    score = engine.update_score("test_client", {"event": "abnormal_norm"})
    log.info(f"After abnormal norm: {score}")

    # Score should be clamped
    assert MIN_SCORE <= score <= MAX_SCORE
    log.info("All trust engine smoke tests passed!")
