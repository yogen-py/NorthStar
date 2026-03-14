import numpy as np
from typing import List

# Shared model shape across all containers — mimics a small CNN
# (no torch required — pure numpy representation)
MODEL_SHAPE = [
    (32, 1, 3, 3),    # conv1 weights
    (32,),             # conv1 bias
    (64, 32, 3, 3),   # conv2 weights
    (64,),             # conv2 bias
    (128, 1600),       # fc1 weights
    (128,),            # fc1 bias
    (10, 128),         # fc2 weights
    (10,),             # fc2 bias
]

def get_initial_weights() -> List[np.ndarray]:
    """Returns randomly initialized weights matching MODEL_SHAPE."""
    return [
        np.random.normal(0, 0.01, shape).astype(np.float32)
        for shape in MODEL_SHAPE
    ]

def compute_update_norm(
    old_weights: List[np.ndarray],
    new_weights: List[np.ndarray]
) -> float:
    """L2 norm of weight delta — primary signal for trust scoring."""
    deltas = [n - o for n, o in zip(new_weights, old_weights)]
    return float(np.sqrt(sum(np.sum(d ** 2) for d in deltas)))

if __name__ == "__main__":
    weights = get_initial_weights()
    print(f"Shapes: {[w.shape for w in weights]}")
    perturbed = [w + np.random.normal(0, 0.01, w.shape) for w in weights]
    print(f"Update norm: {compute_update_norm(weights, perturbed):.6f}")
