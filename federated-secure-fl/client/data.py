"""
Mock Data Loader — Phase 0
Placeholder for MNIST partition loader.
Real MNIST loading will be enabled in Phase 1 when PyTorch is added back.
"""

import logging
from typing import Tuple, Dict, Any

import numpy as np

# ───────────────────────── Logging ───────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data-loader")


def load_partition(
    partition_id: int,
    num_partitions: int = 3,
    num_train: int = 20000,
    num_test: int = 4000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Generate mock MNIST-like data for a partition.

    In Phase 0 this returns random numpy arrays.
    Phase 1 will replace this with real torchvision MNIST loading.

    Args:
        partition_id: Index of the partition (0-based).
        num_partitions: Total number of partitions.
        num_train: Number of mock training samples per partition.
        num_test: Number of mock test samples per partition.

    Returns:
        Tuple of (train_data, test_data) dicts with 'images' and 'labels' keys.
    """
    # Scale down per-partition
    train_per_part = num_train // num_partitions
    test_per_part = num_test // num_partitions

    # Generate random 28x28 grayscale "images" and labels 0-9
    rng = np.random.RandomState(seed=42 + partition_id)

    train_data = {
        "images": rng.randn(train_per_part, 1, 28, 28).astype(np.float32),
        "labels": rng.randint(0, 10, size=train_per_part),
    }
    test_data = {
        "images": rng.randn(test_per_part, 1, 28, 28).astype(np.float32),
        "labels": rng.randint(0, 10, size=test_per_part),
    }

    logger.info(
        f"Partition {partition_id}/{num_partitions}: "
        f"train={train_per_part} samples, test={test_per_part} samples (mock)"
    )

    return train_data, test_data


# ───────────────────────── Main ─────────────────────────────────

if __name__ == "__main__":
    train_data, test_data = load_partition(0, num_partitions=3)
    logger.info(
        f"Train images shape: {train_data['images'].shape}, "
        f"Test images shape: {test_data['images'].shape}"
    )
