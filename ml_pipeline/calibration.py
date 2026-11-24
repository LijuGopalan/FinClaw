"""Temporal splitting and Platt calibration shared by FinClaw model trainers."""

import hashlib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


def temporal_split(df, timestamp_column="timestamp"):
    """Split rows by unique timestamps so contemporaneous symbols stay together."""
    if timestamp_column not in df:
        raise ValueError(f"Dataset must contain {timestamp_column!r}; rebuild it before training")

    timestamps = pd.to_datetime(df[timestamp_column], utc=True, errors="coerce")
    valid = timestamps.notna()
    df = df.loc[valid].copy()
    timestamps = timestamps.loc[valid]
    unique = np.sort(timestamps.unique())
    if len(unique) < 10:
        raise ValueError("At least 10 distinct timestamps are required for temporal validation")

    train_end = max(1, int(len(unique) * 0.70))
    calibration_end = max(train_end + 1, int(len(unique) * 0.85))
    calibration_end = min(calibration_end, len(unique) - 1)
    train_times = set(unique[:train_end])
    calibration_times = set(unique[train_end:calibration_end])
    test_times = set(unique[calibration_end:])

    masks = (
        timestamps.isin(train_times),
        timestamps.isin(calibration_times),
        timestamps.isin(test_times),
    )
    return tuple(df.loc[mask].copy() for mask in masks)


def fit_platt_scaling(raw_probabilities, labels):
    """Fit a sigmoid calibration map over a disjoint temporal calibration set."""
    probabilities = np.clip(np.asarray(raw_probabilities, dtype=float), 1e-6, 1 - 1e-6)
    labels = np.asarray(labels, dtype=int)
    if len(probabilities) < 50 or len(np.unique(labels)) != 2:
        raise ValueError("Calibration requires at least 50 samples containing both classes")

    logits = np.log(probabilities / (1 - probabilities)).reshape(-1, 1)
    calibrator = LogisticRegression(solver="lbfgs", random_state=42)
    calibrator.fit(logits, labels)
    return {
        "method": "platt",
        "coefficient": float(calibrator.coef_[0, 0]),
        "intercept": float(calibrator.intercept_[0]),
        "sample_count": int(len(labels)),
    }


def apply_platt_scaling(probability, calibration):
    """Apply a saved Platt map; return None if its artifact is invalid."""
    try:
        coefficient = float(calibration["coefficient"])
        intercept = float(calibration["intercept"])
        probability = float(probability)
        if (
            calibration.get("method") != "platt"
            or not np.isfinite([coefficient, intercept, probability]).all()
            or not 0 <= probability <= 1
        ):
            return None
        clipped = np.clip(probability, 1e-6, 1 - 1e-6)
        logit = np.log(clipped / (1 - clipped))
        value = 1 / (1 + np.exp(-np.clip(coefficient * logit + intercept, -50, 50)))
        return float(value)
    except (KeyError, TypeError, ValueError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
