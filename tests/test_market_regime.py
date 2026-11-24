import pytest

from skills import market_regime_detector as detector


def test_action_plan_uses_structured_json_and_preserves_evidence(monkeypatch):
    observed = {}

    def fake_ask_json(prompt, **kwargs):
        observed.update(kwargs)
        return {
            "verdict": "STAY DEFENSIVE",
            "reasoning": "VIX is elevated.",
            "immediate_actions": ["Review open positions."],
            "what_to_watch": ["VIX trend"],
            "reentry_signals": ["Breadth improves"],
        }

    monkeypatch.setattr(detector, "ask_json", fake_ask_json)
    indices = {"SPY": {"price": 500}, "QQQ": {"price": 400}}
    vix = {"level": 27}
    breadth = {"above_200_pct": 40}

    result = detector.generate_action_plan(
        "CORRECTION", 45, ["Elevated volatility"], indices, vix, breadth,
    )

    assert observed["schema"] is detector._ACTION_PLAN_SCHEMA
    assert observed["task"] == "regime"
    assert "**VERDICT:** STAY DEFENSIVE" in result["action_plan"]
    assert result["evidence"] == {
        "indices": indices,
        "vix": vix,
        "breadth": breadth,
        "portfolio_drawdown": 0,
    }
    assert result["inference"] == "VIX is elevated."
    assert result["recommendation"]["immediate_actions"] == ["Review open positions."]


def test_action_plan_rejects_invalid_structured_output(monkeypatch):
    monkeypatch.setattr(detector, "ask_json", lambda *args, **kwargs: {
        "verdict": "SELL EVERYTHING",
        "reasoning": "Invalid verdict.",
        "immediate_actions": [],
        "what_to_watch": [],
        "reentry_signals": [],
    })

    with pytest.raises(ValueError, match="schema validation"):
        detector.generate_action_plan("CRISIS", 90, [], {}, {}, {})
