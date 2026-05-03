"""
Malicious Client Simulation — Phase 0 (Mocked)
Attack simulation stub with noise and sign_flip modes.
Uses mocked training (numpy only) for fast builds.

!!! Phase 5 — do not enable until Phase 4 complete !!!
This client is gated behind Docker Compose profiles: ["attack"]
and will NOT start unless explicitly requested with:
    docker compose --profile attack up malicious_client
"""

import os
import random
import time
import sys
from typing import Dict, List, Tuple
import httpx

import flwr as fl
from flwr.common import Scalar
import numpy as np
from dotenv import load_dotenv

from mock_model import get_initial_weights, compute_update_norm
from shared.logger import get_logger, log_event

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "fl-server:9080")
CLIENT_ID = os.getenv("CLIENT_ID", "malicious_client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
DATA_PARTITION = int(os.getenv("DATA_PARTITION", "0"))
NUM_PARTITIONS = int(os.getenv("NUM_PARTITIONS", "3"))
ATTACK_MODE = os.getenv("ATTACK_MODE", "noise")  # "noise" | "sign_flip"
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
MIDDLEWARE_URL = os.getenv("MIDDLEWARE_URL", "http://fl-middleware:8000")

# ───────────────────────── Logging ───────────────────────────────
log = get_logger(CLIENT_ID)

NUM_TRAIN_SAMPLES = 20000


# ───────────────────────── Attack Functions ──────────────────────

def apply_noise_attack(parameters: List[np.ndarray]) -> List[np.ndarray]:
    """
    Noise attack: adds Gaussian noise scaled to 10x the mean update norm.
    This injects large random perturbations to corrupt the global model.
    """
    mean_norm = float(np.mean([np.linalg.norm(p) for p in parameters]))
    noise_scale = 10.0 * mean_norm
    log.warning(f"[ATTACK:noise] Injecting noise with scale={noise_scale:.4f}")
    return [
        p + np.random.normal(0, noise_scale, size=p.shape).astype(np.float32)
        for p in parameters
    ]


def apply_sign_flip_attack(parameters: List[np.ndarray]) -> List[np.ndarray]:
    """
    Sign-flip attack: multiplies all weights by -1.
    This reverses the direction of the gradient update.
    """
    log.warning("[ATTACK:sign_flip] Flipping all parameter signs")
    return [-1.0 * p for p in parameters]


def apply_attack(parameters: List[np.ndarray], mode: str) -> List[np.ndarray]:
    """Apply the specified attack to model parameters."""
    if mode == "noise":
        return apply_noise_attack(parameters)
    elif mode == "sign_flip":
        return apply_sign_flip_attack(parameters)
    else:
        log.error(f"Unknown attack mode: {mode}. Returning unmodified params.")
        return parameters


# ───────────────────────── Malicious Flower Client ───────────────

class MaliciousClient(fl.client.NumPyClient):
    """
    Flower NumPyClient that applies an attack after mock training.
    Phase 5 — do not enable until Phase 4 complete.
    """

    def __init__(self, attack_mode: str) -> None:
        self.params = get_initial_weights()
        self.attack_mode = attack_mode
        self.round_num = 0

    def get_parameters(self, config: Dict[str, Scalar]) -> List[np.ndarray]:
        return self.params

    def set_parameters(self, parameters: List[np.ndarray]) -> None:
        self.params = parameters

    def fit(
        self, parameters: List[np.ndarray], config: Dict[str, Scalar]
    ) -> Tuple[List[np.ndarray], int, Dict[str, Scalar]]:
        """Mock train honestly, then apply attack to the returned parameters."""
        self.set_parameters(parameters)
        self.round_num += 1

        # Simulate honest training perturbation
        honest_params = [
            p + np.random.randn(*p.shape).astype(np.float32) * 0.001
            for p in self.params
        ]

        # Apply attack
        malicious_params = apply_attack(honest_params, self.attack_mode)

        # Fake metrics (look normal to evade simple detection)
        fake_loss = max(0.1, 2.5 - 0.3 * self.round_num + random.gauss(0, 0.1))
        fake_acc = min(0.98, 0.4 + 0.08 * self.round_num + random.gauss(0, 0.02))

        time.sleep(random.uniform(0.5, 1.0))

        update_norm = compute_update_norm(self.params, malicious_params)

        log.warning(
            f"[{CLIENT_ID}] fit (MALICIOUS) round={self.round_num}: "
            f"mode={self.attack_mode}, loss={fake_loss:.4f}, acc={fake_acc:.4f}"
        )

        log_event(log, "attack_applied",
            round=config.get("server_round", self.round_num),
            attack_mode=ATTACK_MODE,
            update_norm=update_norm,
            client_id=CLIENT_ID,
        )

        return malicious_params, NUM_TRAIN_SAMPLES, {
            "loss": float(fake_loss),
            "accuracy": float(fake_acc),
            "client_id": CLIENT_ID,
            "update_norm": update_norm,
            "train_loss": float(fake_loss),
            "attack_mode": self.attack_mode,
        }

    def evaluate(
        self, parameters: List[np.ndarray], config: Dict[str, Scalar]
    ) -> Tuple[float, int, Dict[str, Scalar]]:
        """Evaluate honestly (no attack on evaluation)."""
        self.set_parameters(parameters)
        eval_loss = max(0.05, 2.0 - 0.25 * self.round_num + random.gauss(0, 0.08))
        eval_acc = min(0.99, 0.45 + 0.07 * self.round_num + random.gauss(0, 0.015))
        num_examples = NUM_TRAIN_SAMPLES // 5

        log.info(f"[{CLIENT_ID}] eval: loss={eval_loss:.4f}, acc={eval_acc:.4f}")
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
    """Start the malicious Flower client."""
    MAX_RETRIES = 10
    RETRY_DELAY = 5

    for attempt in range(MAX_RETRIES):
        try:
            token = get_keycloak_token()
            admitted = request_admission(token)
            if admitted:
                break
        except Exception as e:
            time.sleep(RETRY_DELAY)
    else:
        sys.exit(1)

    log_event(log, "malicious_client_start",
        client_id=CLIENT_ID,
        attack_mode=ATTACK_MODE)

    log.warning(
        f"⚠ Starting MALICIOUS client {CLIENT_ID}, "
        f"attack_mode={ATTACK_MODE}, partition={DATA_PARTITION}"
    )
    client = MaliciousClient(attack_mode=ATTACK_MODE)
    fl.client.start_client(
        server_address=SERVER_ADDRESS,
        client=client.to_client(),
    )


if __name__ == "__main__":
    main()
