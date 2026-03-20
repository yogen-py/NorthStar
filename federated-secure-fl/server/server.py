"""
Flower Federated Learning Server — Phase 0
Uses FedAvg strategy with structured JSON logging via shared/logger.py.
"""

import os
import uuid
from typing import Dict, List, Optional, Tuple

import flwr as fl
from flwr.common import Metrics, Parameters, Scalar
from flwr.server.client_proxy import ClientProxy
from flwr.common import FitRes, EvaluateRes
import numpy as np
from dotenv import load_dotenv

from shared.logger import get_logger, log_event, Timer
from gate import RoundGate
from input_handler import start_input_listener

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "0.0.0.0:9080")
NUM_ROUNDS = int(os.getenv("FLOWER_NUM_ROUNDS", "5"))

# ───────────────────────── Logging ───────────────────────────────
log = get_logger("server")

HITL_ENABLED = os.getenv("HITL_ENABLED", "true").lower() == "true"
gate = RoundGate(enabled=HITL_ENABLED)


# ───────────────────────── Strategy callbacks ────────────────────

def fit_metrics_aggregation(metrics: List[Tuple[int, Metrics]]) -> Metrics:
    """Aggregate fit metrics from all clients."""
    total_examples = sum(num for num, _ in metrics)
    aggregated: Metrics = {}
    if total_examples > 0:
        aggregated["loss"] = sum(
            num * m.get("loss", 0.0) for num, m in metrics
        ) / total_examples
    return aggregated


def evaluate_metrics_aggregation(metrics: List[Tuple[int, Metrics]]) -> Metrics:
    """Aggregate evaluation metrics from all clients."""
    total_examples = sum(num for num, _ in metrics)
    aggregated: Metrics = {}
    if total_examples > 0:
        aggregated["accuracy"] = sum(
            num * m.get("accuracy", 0.0) for num, m in metrics
        ) / total_examples
    return aggregated


class LoggingFedAvg(fl.server.strategy.FedAvg):
    """FedAvg with per-round structured JSON logging via shared logger."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._round_clients = []

    def aggregate_fit(
        self,
        server_round: int,
        results: List[Tuple[ClientProxy, FitRes]],
        failures: List[Tuple[ClientProxy, FitRes] | BaseException],
    ) -> Tuple[Optional[Parameters], Dict[str, Scalar]]:
        """Aggregate and log fit results."""
        cid = str(uuid.uuid4())

        log_event(log, "round_start",
            correlation_id=cid,
            round=server_round,
            num_clients_selected=len(results),
            num_failures=len(failures),
        )

        self._round_clients = []
        for _, fit_res in results:
            log_event(log, "weights_received",
                correlation_id=cid,
                round=server_round,
                client_id=fit_res.metrics.get("client_id"),
                num_examples=fit_res.num_examples,
                update_norm=fit_res.metrics.get("update_norm"),
                train_loss=fit_res.metrics.get("train_loss"),
            )
            self._round_clients.append({
                "client_id":   fit_res.metrics.get("client_id", "unknown"),
                "update_norm": round(fit_res.metrics.get("update_norm", 0.0), 4),
                "train_loss":  round(fit_res.metrics.get("train_loss", 0.0), 4),
                "trust_score": 0.8,
                # TODO Phase 4 — replace with TrustEngine.get_score(client_id)
            })

        for failure in failures:
            log_event(log, "client_failure",
                correlation_id=cid,
                round=server_round,
                reason=str(failure),
            )

        with Timer() as t:
            result = super().aggregate_fit(server_round, results, failures)

        log_event(log, "aggregation_complete",
            correlation_id=cid,
            round=server_round,
            duration_ms=t.duration_ms,
            num_clients=len(results),
        )
        return result

    def aggregate_evaluate(
        self,
        server_round: int,
        results: List[Tuple[ClientProxy, EvaluateRes]],
        failures: List[Tuple[ClientProxy, EvaluateRes] | BaseException],
    ) -> Tuple[Optional[float], Dict[str, Scalar]]:
        """Aggregate and log evaluation results."""
        cid = str(uuid.uuid4())
        with Timer() as t:
            aggregated = super().aggregate_evaluate(server_round, results, failures)

        if aggregated:
            loss, metrics = aggregated
            log_event(log, "round_complete",
                correlation_id=cid,
                round=server_round,
                aggregated_loss=round(loss, 6),
                num_clients=len(results),
                num_failures=len(failures),
                duration_ms=t.duration_ms,
            )

            summary = {
                "round":           server_round,
                "aggregated_loss": round(loss, 6),
                "num_clients":     len(results),
                "clients":         self._round_clients,
            }
            decision = gate.wait_for_approval(summary)

            log_event(log, "round_gate_decision",
                round=server_round,
                decision=decision,
                aggregated_loss=summary["aggregated_loss"],
            )

            if decision == "stop":
                log_event(log, "experiment_stopped",
                    round=server_round,
                    reason="operator_halt")
                raise SystemExit("Experiment stopped by operator.")

            if decision == "reject":
                log_event(log, "round_rejected",
                    round=server_round,
                    reason="operator_rejected")
                return None, {}

        return aggregated


# ───────────────────────── Main ─────────────────────────────────

def create_strategy() -> LoggingFedAvg:
    """Create and return the FL strategy."""
    return LoggingFedAvg(
        min_fit_clients=3,
        min_evaluate_clients=3,
        min_available_clients=3,
        fit_metrics_aggregation_fn=fit_metrics_aggregation,
        evaluate_metrics_aggregation_fn=evaluate_metrics_aggregation,
    )


def main() -> None:
    """Start the Flower server."""
    strategy = create_strategy()
    log_event(log, "server_start",
        address="0.0.0.0:9080",
        num_rounds=int(os.getenv("FLOWER_NUM_ROUNDS", "5")),
    )
    gate.start_http_server()
    fl.server.start_server(
        server_address=SERVER_ADDRESS,
        config=fl.server.ServerConfig(num_rounds=NUM_ROUNDS),
        strategy=strategy,
    )


if __name__ == "__main__":
    main()
