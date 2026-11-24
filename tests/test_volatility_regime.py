import json

import pytest

from skills import volatility_regime as vr


def _settings(**overrides):
    settings = {
        "regime": "high_vol",
        "regime_changed": True,
        "position_sizing": "defensive",
        "preferred_timeframe": "swing",
        "stop_loss_multiplier": 1.5,
        "cash_allocation_pct": 35,
        "min_opportunity_score": 68,
        "universe_limit": 30,
        "strategy_summary": "Reduce exposure.",
        "reasoning": "Volatility is elevated.",
    }
    settings.update(overrides)
    return settings


def test_regime_output_is_schema_validated_and_saved(monkeypatch, tmp_path):
    regime_file = tmp_path / "regime.json"
    monkeypatch.setattr(vr, "REGIME_FILE", str(regime_file))
    monkeypatch.setattr(vr, "calculate_vix_regime", lambda: {
        "vix_level": 27.1, "regime": "high", "description": "Elevated volatility",
    })
    monkeypatch.setattr(vr, "calculate_market_breadth", lambda: {
        "spy": -0.5, "qqq": -0.8, "iwm": -1.0, "breadth": "strong_bearish",
    })
    monkeypatch.setattr(vr, "calculate_atr_regime", lambda ticker: None)
    monkeypatch.setattr(vr, "ask_json", lambda *args, **kwargs: _settings())

    alert = vr.detect_volatility_regime()
    saved = json.loads(regime_file.read_text())

    assert "High Vol" in alert
    assert saved["min_opportunity_score"] == 68
    assert saved["stop_loss_multiplier"] == 1.5
    assert saved["position_sizing"] == "defensive"
    assert vr.get_current_regime_settings()["cash_allocation_pct"] == 35


def test_regime_validation_rejects_unsafe_values():
    with pytest.raises(ValueError, match="stop_loss_multiplier"):
        vr._validate_regime_settings(_settings(stop_loss_multiplier=3.0))

    with pytest.raises(ValueError, match="universe_limit"):
        vr._validate_regime_settings(_settings(universe_limit=100))
