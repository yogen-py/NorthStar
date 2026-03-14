"""
Flower Federated Learning Client — Phase 0 (Mocked)
NumPyClient with mocked training to test pipeline + trust scoring.
No PyTorch dependency — uses numpy arrays as fake model weights.
"""

import os
import random
import time
import sys
import uuid
from typing import Dict, List, Tuple
import httpx

import flwr as fl
from flwr.common import Scalar
import numpy as np
from dotenv import load_dotenv
from mock_model import get_initial_weights, compute_update_norm
from shared.logger import get_logger, log_event, Timer

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "fl-server:9080")
CLIENT_ID = os.getenv("CLIENT_ID", "default_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
DATA_PARTITION = int(os.getenv("DATA_PARTITION", "0"))
NUM_PARTITIONS = int(os.getenv("NUM_PARTITIONS", "3"))
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
MIDDLEWARE_URL = os.getenv("MIDDLEWARE_URL", "http://fl-middleware:8000")

# ───────────────────────── Logging ───────────────────────────────
log = get_logger(os.getenv("CLIENT_ID", "client"))

NUM_TRAIN_SAMPLES = 20000  # fake dataset size per partition


# ───────────────────────── Flower Client ─────────────────────────

class MockMNISTClient(fl.client.NumPyClient):
    """
    Flower NumPyClient with mocked training.
    Returns realistic-looking metrics for trust scoring validation.
    """

    def __init__(self) -> None:
        self.params = get_initial_weights()
        self.round_num = 0

    def get_parameters(self, config: Dict[str, Scalar]) -> List[np.ndarray]:
        """Return current model parameters."""
        return self.params

    def set_parameters(self, parameters: List[np.ndarray]) -> None:
        """Set model parameters from server."""
        self.params = parameters

    def fit(
        self, parameters: List[np.ndarray], config: Dict[str, Scalar]
    ) -> Tuple[List[np.ndarray], int, Dict[str, Scalar]]:
        """Mock training — applies small random perturbations to params."""
        cid = str(uuid.uuid4())
        self.set_parameters(parameters)
        self.round_num += 1

        log_event(log, "fit_start",
            correlation_id=cid,
            round=config.get("server_round"),
            client_id=CLIENT_ID,
            data_partition=int(os.getenv("DATA_PARTITION", 0)),
            quality=float(os.getenv("CLIENT_QUALITY", 0.85)),
            parameters_received=len(parameters),
        )

        with Timer() as t:
            # Save old weights before mutation
            old_params = [p.copy() for p in self.params]

            # Simulate training: small perturbation to weights
            self.params = [
                p + np.random.randn(*p.shape).astype(np.float32) * 0.001
                for p in self.params
            ]

            # Simulate improving metrics over rounds
            base_loss = max(0.1, 2.5 - 0.3 * self.round_num + random.gauss(0, 0.1))
            base_acc = min(0.98, 0.4 + 0.08 * self.round_num + random.gauss(0, 0.02))
            noise_scale = float(os.getenv("NOISE_SCALE", 0.001))

            # Simulate brief training delay
            time.sleep(random.uniform(0.5, 1.5))

        update_norm = compute_update_norm(old_params, self.params)
        num_examples = NUM_TRAIN_SAMPLES

        log_event(log, "fit_complete",
            correlation_id=cid,
            round=config.get("server_round"),
            client_id=CLIENT_ID,
            update_norm=update_norm,
            train_loss=base_loss,
            noise_scale=noise_scale,
            num_examples=num_examples,
            duration_ms=t.duration_ms,
        )

        return self.get_parameters(config={}), num_examples, {
            "loss": float(base_loss),
            "accuracy": float(base_acc),
            "client_id": CLIENT_ID,
            "update_norm": update_norm,
            "train_loss": base_loss,
        }

    def evaluate(
        self, parameters: List[np.ndarray], config: Dict[str, Scalar]
    ) -> Tuple[float, int, Dict[str, Scalar]]:
        """Mock evaluation — returns realistic metrics."""
        cid = str(uuid.uuid4())
        self.set_parameters(parameters)

        with Timer() as t:
            eval_loss = max(0.05, 2.0 - 0.25 * self.round_num + random.gauss(0, 0.08))
            eval_acc = min(0.99, 0.45 + 0.07 * self.round_num + random.gauss(0, 0.015))
            num_examples = NUM_TRAIN_SAMPLES // 5  # test set is ~20% of train

        log_event(log, "evaluate_complete",
            correlation_id=cid,
            round=config.get("server_round"),
            client_id=CLIENT_ID,
            accuracy=round(float(eval_acc), 4),
            loss=round(float(eval_loss), 4),
            data_partition=int(os.getenv("DATA_PARTITION", 0)),
            quality=float(os.getenv("CLIENT_QUALITY", 0.85)),
            duration_ms=t.duration_ms,
        )

        return float(eval_loss), num_examples, {"accuracy": float(eval_acc)}

# ───────────────────────── Admission ────────────────────────────

def get_keycloak_token() -> str:
    """Fetch JWT from Keycloak using client_credentials grant."""
    response = httpx.post(
        f"{KEYCLOAK_URL}/realms/fl-realm/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=10.0
    )
    response.raise_for_status()
    return response.json()["access_token"]


def request_admission(token: str) -> bool:
    """Request admission via the FastAPI middleware."""
    response = httpx.post(
        f"{MIDDLEWARE_URL}/admit",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0
    )
    response.raise_for_status()
    data = response.json()
    return data.get("allowed") is True

# ───────────────────────── Main ─────────────────────────────────

def main() -> None:
    """Start the Flower client."""
    MAX_RETRIES = 10
    RETRY_DELAY = 5  # seconds

    for attempt in range(MAX_RETRIES):
        try:
            token = get_keycloak_token()
            admitted = request_admission(token)
            if admitted:
                log_event(log, "admission_success",
                    client_id=CLIENT_ID,
                    token_snippet=token[:10] + "...")
                break
        except Exception as e:
            log_event(log, "admission_retry",
                attempt=attempt + 1,
                error=str(e))
            time.sleep(RETRY_DELAY)
    else:
        log_event(log, "admission_failed",
            client_id=CLIENT_ID,
            reason="max retries exceeded")
        sys.exit(1)

    log_event(log, "client_start",
        client_id=CLIENT_ID,
        data_partition=DATA_PARTITION,
        server_address=SERVER_ADDRESS,
    )
    client = MockMNISTClient()
    fl.client.start_client(
        server_address=SERVER_ADDRESS,
        client=client.to_client(),
    )


if __name__ == "__main__":
    main()
