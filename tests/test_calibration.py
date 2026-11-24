import numpy as np
import pandas as pd
import pytest

from ml_pipeline.calibration import apply_platt_scaling, fit_platt_scaling, temporal_split


def test_temporal_split_keeps_timestamps_separate():
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=30, freq="h").repeat(2),
        "target": [0, 1] * 30,
    })

    train, calibration, test = temporal_split(df)

    assert train["timestamp"].max() < calibration["timestamp"].min()
    assert calibration["timestamp"].max() < test["timestamp"].min()


def test_temporal_split_requires_timestamps():
    with pytest.raises(ValueError, match="timestamp"):
        temporal_split(pd.DataFrame({"target": [0, 1]}))


def test_platt_calibration_produces_bounded_probability():
    raw = np.linspace(0.01, 0.99, 100)
    labels = (raw > 0.5).astype(int)

    calibration = fit_platt_scaling(raw, labels)
    probability = apply_platt_scaling(0.7, calibration)

    assert 0 < probability < 1
    assert apply_platt_scaling(0.7, {"method": "other"}) is None
