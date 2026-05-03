"""
Flower Federated Learning Server — Phase 4
Uses FedAvg strategy with structured JSON logging and Trust Engine integration.
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
from trust.scoring import TrustEngine

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "0.0.0.0:9080")
NUM_ROUNDS     = int(os.getenv("FLOWER_NUM_ROUNDS", "5"))
DB_URL         = os.getenv("DB_URL", "sqlite:///./trust.db")
WARMUP_ROUNDS  = int(os.getenv("WARMUP_ROUNDS", "3"))
TRUST_WEIGHTING = os.getenv("TRUST_WEIGHTING", "true").lower() == "true"

# ───────────────────────── Logging ───────────────────────────────
log = get_logger("server")

HITL_ENABLED = os.getenv("HITL_ENABLED", "true").lower() == "true"
gate = RoundGate(enabled=HITL_ENABLED)

# ───────────────────────── Trust Engine (D1) ─────────────────────
# Module-level; shared across strategy and Flask route.
current_round: int = 0
trust_engine = TrustEngine(db_url=DB_URL)


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
    """FedAvg with per-round structured JSON logging and Trust Engine (Phase 4)."""

    def __init__(self, trust_engine: TrustEngine, **kwargs):
        super().__init__(**kwargs)
        self._round_clients = []
        # D2: inject TrustEngine and track previous round participants for dropout
        self.trust_engine = trust_engine
        self._previous_round_client_ids: set = set()

    def _apply_trust_weights(self, server_round, results):
        """
        Replaces num_examples with trust-weighted effective count.
        effective_weight_i = n_i * T_i
        Normalised so sum of effective weights = sum of original n_i
        (preserves scale for aggregation stability).
        """
        if not TRUST_WEIGHTING or server_round <= WARMUP_ROUNDS:
            return results

        raw_weights = []
        for _, fit_res in results:
            cid    = fit_res.metrics.get("client_id", "unknown")
            n_i    = fit_res.num_examples
            T_i    = self.trust_engine.get_score(cid, current_round=server_round)
            raw_weights.append(n_i * T_i)

        total_raw   = sum(raw_weights)
        total_n     = sum(r.num_examples for _, r in results)
        scale       = total_n / total_raw if total_raw > 0 else 1.0

        patched = []
        for i, (proxy, fit_res) in enumerate(results):
            effective_n = int(raw_weights[i] * scale)
            effective_n = max(effective_n, 1)   # never zero
            fit_res.num_examples = effective_n
            patched.append((proxy, fit_res))

        return patched

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

        # D3: track clients in this round for dropout detection
        current_round_client_ids: set = set()

        # D4: Collect metrics for each client to display in HITL gate
        client_metrics = {}

        self._round_clients = []
        for client_proxy, fit_res in results:
            client_id  = str(fit_res.metrics.get("client_id") or client_proxy.cid)
            update_norm = float(fit_res.metrics.get("update_norm", 0.0))
            train_loss  = float(fit_res.metrics.get("train_loss", 0.0))
            client_metrics[client_id] = {"update_norm": update_norm, "train_loss": train_loss}

            current_round_client_ids.add(client_id)

            log_event(log, "weights_received",
                correlation_id=cid,
                round=server_round,
                client_id=client_id,
                num_examples=fit_res.num_examples,
                update_norm=update_norm,
                train_loss=train_loss,
            )

            # D3: update trust score immediately after processing weights
            # Detect whether this norm was already clamped by the client
            # (i.e. the raw value was inf/nan and the client returned 1e6 sentinel).
            norm_was_clamped = (update_norm >= 1e6)
            self.trust_engine.update_score(client_id, {
                "round":           server_round,
                "update_norm":     update_norm,
                "train_loss":      train_loss,
                "dropout":         False,
                "norm_was_clamped": norm_was_clamped,
            })

        # D3: Dropout detection — clients in previous round but not this one
        for dropped_id in (self._previous_round_client_ids - current_round_client_ids):
            self.trust_engine.update_score(dropped_id, {
                "round":       server_round,
                "update_norm": 0.0,
                "train_loss":  0.0,
                "dropout":     True,
            })
        self._previous_round_client_ids = current_round_client_ids

        # D3: Update module-level round counter (used by policy-warning route)
        global current_round
        current_round = server_round

        # D3: Build _round_clients with live trust scores (0.8 during warmup)
        self._round_clients = [
            {
                "client_id":   cid_,
                "update_norm": client_metrics[cid_]["update_norm"],
                "train_loss":  client_metrics[cid_]["train_loss"],
                "trust_score": self.trust_engine.get_score(
                    cid_, current_round=server_round
                ),
            }
            for cid_ in current_round_client_ids
        ]

        for failure in failures:
            log_event(log, "client_failure",
                correlation_id=cid,
                round=server_round,
                reason=str(failure),
            )

        original_n_map = {str(r.metrics.get("client_id") or p.cid): r.num_examples for p, r in results}

        results = self._apply_trust_weights(server_round, results)

        log_event(log, "trust_weighting_applied",
            round=server_round,
            enabled=TRUST_WEIGHTING,
            clients=[{
                "client_id": str(r.metrics.get("client_id") or p.cid),
                "original_n": original_n_map.get(str(r.metrics.get("client_id") or p.cid)),
                "effective_n": r.num_examples,
                "trust_score": self.trust_engine.get_score(
                    str(r.metrics.get("client_id") or p.cid), current_round=server_round),
            } for p, r in results],
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
    """Create and return the FL strategy with Trust Engine injected."""
    return LoggingFedAvg(
        trust_engine=trust_engine,
        min_fit_clients=3,
        min_evaluate_clients=3,
        min_available_clients=3,
        fit_metrics_aggregation_fn=fit_metrics_aggregation,
        evaluate_metrics_aggregation_fn=evaluate_metrics_aggregation,
    )


def main() -> None:
    """Start the Flower server."""
    # D1: init Trust Engine DB before starting the server
    trust_engine.init_db()

    strategy = create_strategy()
    log_event(log, "server_start",
        address="0.0.0.0:9080",
        num_rounds=int(os.getenv("FLOWER_NUM_ROUNDS", "5")),
    )

    # E1: Register /trust/policy-warning route on the existing FastAPI gate app
    from fastapi import Request as FRequest
    from fastapi.responses import JSONResponse

    @gate._app.post("/trust/policy-warning")
    async def policy_warning_route(req: FRequest):
        data = await req.json()
        if not data or "client_id" not in data:
            return JSONResponse({"error": "client_id required"}, status_code=400)

        cw_client_id = data["client_id"]
        reason       = data.get("reason", "policy_denied")

        trust_engine.update_score(cw_client_id, {
            "round":          current_round,
            "update_norm":    0.0,
            "train_loss":     0.0,
            "dropout":        False,
            "policy_warning": True,
        })

        log_event(log, "policy_warning_applied",
            client_id=cw_client_id,
            reason=reason,
            round=current_round,
        )

        return JSONResponse({"status": "ok", "client_id": cw_client_id})

    # Phase 6: mount assurance reporting router on the existing gate app
    from assurance import router as assurance_router
    gate._app.include_router(assurance_router)

    gate.start_http_server()
    fl.server.start_server(
        server_address=SERVER_ADDRESS,
        config=fl.server.ServerConfig(num_rounds=NUM_ROUNDS),
        strategy=strategy,
    )


if __name__ == "__main__":
    main()
