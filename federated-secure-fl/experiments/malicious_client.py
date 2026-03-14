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
import logging
import random
import time
from typing import Dict, List, Tuple

import flwr as fl
from flwr.common import Scalar
import numpy as np
from dotenv import load_dotenv

# mock_model lives in client/ — add to path for cross-directory import
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "client"))
from mock_model import get_initial_weights, compute_update_norm

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "fl-server:9080")
CLIENT_ID = os.getenv("CLIENT_ID", "malicious_client")
DATA_PARTITION = int(os.getenv("DATA_PARTITION", "0"))
NUM_PARTITIONS = int(os.getenv("NUM_PARTITIONS", "3"))
ATTACK_MODE = os.getenv("ATTACK_MODE", "noise")  # "noise" | "sign_flip"

# ───────────────────────── Logging ───────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(f"malicious-{CLIENT_ID}")

NUM_TRAIN_SAMPLES = 20000


# ───────────────────────── Attack Functions ──────────────────────

def apply_noise_attack(parameters: List[np.ndarray]) -> List[np.ndarray]:
    """
    Noise attack: adds Gaussian noise scaled to 10x the mean update norm.
    This injects large random perturbations to corrupt the global model.
    """
    mean_norm = float(np.mean([np.linalg.norm(p) for p in parameters]))
    noise_scale = 10.0 * mean_norm
    logger.warning(f"[ATTACK:noise] Injecting noise with scale={noise_scale:.4f}")
    return [
        p + np.random.normal(0, noise_scale, size=p.shape).astype(np.float32)
        for p in parameters
    ]


def apply_sign_flip_attack(parameters: List[np.ndarray]) -> List[np.ndarray]:
    """
    Sign-flip attack: multiplies all weights by -1.
    This reverses the direction of the gradient update.
    """
    logger.warning("[ATTACK:sign_flip] Flipping all parameter signs")
    return [-1.0 * p for p in parameters]


def apply_attack(parameters: List[np.ndarray], mode: str) -> List[np.ndarray]:
    """Apply the specified attack to model parameters."""
    if mode == "noise":
        return apply_noise_attack(parameters)
    elif mode == "sign_flip":
        return apply_sign_flip_attack(parameters)
    else:
        logger.error(f"Unknown attack mode: {mode}. Returning unmodified params.")
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

        logger.warning(
            f"[{CLIENT_ID}] fit (MALICIOUS) round={self.round_num}: "
            f"mode={self.attack_mode}, loss={fake_loss:.4f}, acc={fake_acc:.4f}"
        )

        return malicious_params, NUM_TRAIN_SAMPLES, {
            "loss": float(fake_loss),
            "accuracy": float(fake_acc),
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

        logger.info(f"[{CLIENT_ID}] eval: loss={eval_loss:.4f}, acc={eval_acc:.4f}")
        return float(eval_loss), num_examples, {"accuracy": float(eval_acc)}


# ───────────────────────── Main ─────────────────────────────────

def main() -> None:
    """Start the malicious Flower client."""
    logger.warning(
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
