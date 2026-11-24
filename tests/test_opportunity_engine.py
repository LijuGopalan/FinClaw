from datetime import datetime, timezone

from skills import opportunity_engine as oe
from skills import volatility_regime as vr


def test_detect_market_session_boundaries():
    et = oe.ET
    assert oe.detect_market_session(datetime(2026, 6, 15, 8, 0, tzinfo=et)) == "premarket"
    assert oe.detect_market_session(datetime(2026, 6, 15, 10, 0, tzinfo=et)) == "regular"
    assert oe.detect_market_session(datetime(2026, 6, 15, 17, 0, tzinfo=et)) == "postmarket"
    assert oe.detect_market_session(datetime(2026, 6, 15, 21, 0, tzinfo=et)) == "closed"
    assert oe.detect_market_session(datetime(2026, 6, 14, 10, 0, tzinfo=et)) == "closed"


def test_score_ticker_opportunity_combines_catalysts(monkeypatch):
    monkeypatch.setattr(oe, "get_stock_quote", lambda ticker: {
        "ticker": ticker,
        "price": 100,
        "change_pct": 3.2,
        "volume": 3_000_000,
        "avg_volume": 1_000_000,
        "source": "test quote",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    monkeypatch.setattr(oe, "get_technical_analysis", lambda ticker: {
        "ticker": ticker,
        "current_price": 100,
        "rsi_14": 62,
        "macd_histogram": 0.55,
        "volume_ratio": 2.2,
        "vwap": 98,
        "atr_14": 2,
        "support": 96,
        "resistance": 108,
        "timestamp": "2026-06-15T14:00:00",
    })
    monkeypatch.setattr(oe, "get_intraday_snapshot", lambda ticker: {
        "ticker": ticker,
        "relative_volume": 2.5,
        "vwap_distance_pct": 1.2,
    })
    monkeypatch.setattr(oe, "get_fundamentals", lambda ticker: {
        "growth": {"revenue_growth_pct": 24},
        "valuation": {"pe_forward": 28},
        "analyst_consensus": {"recommendation": "buy", "target_mean": 125},
    })
    monkeypatch.setattr(oe, "get_options_chain", lambda ticker: {
        "put_call_ratio": 0.45,
        "unusual_activity": [{"premium": 600_000}],
        "top_call_strikes": [{"volume": 4000}],
        "top_put_strikes": [{"volume": 500}],
        "source": "test options",
    })
    monkeypatch.setattr(oe, "get_news", lambda ticker=None, query=None, limit=5: {
        "articles": [{"title": "Analyst upgrade raises target after earnings", "description": ""}],
        "source": "test news",
    })
    monkeypatch.setattr(oe, "get_insider_activity", lambda ticker: {
        "summary": {
            "buy_count": 3,
            "sell_count": 0,
            "buy_value": 1_500_000,
            "sell_value": 0,
        },
        "signals": ["Net insider buying"],
        "source": "test insider",
    })
    monkeypatch.setattr(oe, "_score_macro_context", lambda: (4, ["Risk-on sector rotation"], {}))

    result = oe.score_ticker_opportunity("TEST", session="premarket", horizon="swing")

    assert result["ticker"] == "TEST"
    assert result["score"] >= 70
    assert result["action"] == "BUY WATCH"
    assert result["entry_low"] < result["entry_high"]
    assert result["target_price"] > result["price"]
    assert result["stop_loss"] < result["price"]
    assert result["risk_reward"] is not None
    assert result["risk_gate"]["passed"] is True
    assert "Upgrade" in result["catalyst_flags"]
    assert "Net insider buying" in result["smart_money_flags"]


def test_get_opportunities_ranks_and_limits(monkeypatch):
    monkeypatch.setattr(oe, "load_opportunity_watchlist", lambda limit=80: ["AAA", "BBB", "CCC"][:limit])

    scores = {"AAA": 40, "BBB": 82, "CCC": 65}

    def fake_score(ticker, session="auto", horizon="auto", include_options=True, **kwargs):
        return {
            "ticker": ticker,
            "score": scores[ticker],
            "volume_ratio": 1,
            "change_pct": 0,
            "action": "WATCH",
            "price": 100,
        }

    monkeypatch.setattr(oe, "score_ticker_opportunity", fake_score)

    result = oe.get_opportunities(session="regular", horizon="scalp", limit=2, min_score=50)

    assert result["session"] == "regular"
    assert result["horizon"] == "scalp"
    assert [item["ticker"] for item in result["opportunities"]] == ["BBB", "CCC"]


def test_build_opportunity_brief_handles_empty_and_ranked_results():
    empty = {"session": "regular", "horizon_label": "Intraday Scalp", "opportunities": []}
    assert "no qualifying opportunities" in oe.build_opportunity_brief(empty)

    scan = {
        "session": "premarket",
        "horizon_label": "Swing Trade",
        "opportunities": [{
            "ticker": "AAA",
            "action": "ACTIVE WATCH",
            "score": 66,
            "price": 100,
            "entry_low": 98,
            "entry_high": 101,
            "target_price": 110,
            "stop_loss": 94,
            "risk_reward": 1.7,
            "thesis": "Volume and catalyst alignment.",
        }],
    }
    brief = oe.build_opportunity_brief(scan)
    assert "AAA" in brief
    assert "score 66" in brief
    assert "Not financial advice" in brief


def test_risk_gate_vetoes_stale_and_unofficial_intraday_quotes():
    fresh_quote = {
        "source": "Schwab",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    assert oe.evaluate_risk_gate(
        fresh_quote, 100, 99, 101, 105, 95, 2.0, "swing"
    )["passed"]

    stale_quote = {
        "source": "Schwab",
        "timestamp": "2020-01-01T00:00:00+00:00",
    }
    stale_gate = oe.evaluate_risk_gate(
        stale_quote, 100, 99, 101, 105, 95, 2.0, "swing"
    )
    assert stale_gate["passed"] is False
    assert "Market quote is stale" in stale_gate["vetoes"][0]

    delayed_quote = {
        "source": "yfinance (unofficial)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    delayed_gate = oe.evaluate_risk_gate(
        delayed_quote, 100, 99, 101, 105, 95, 2.0, "scalp"
    )
    assert delayed_gate["passed"] is False
    assert any("not eligible for intraday" in veto for veto in delayed_gate["vetoes"])


def test_get_opportunities_applies_validated_regime_settings(monkeypatch):
    settings = {
        "regime": "high_vol",
        "position_sizing": "defensive",
        "preferred_timeframe": "long",
        "stop_loss_multiplier": 1.5,
        "cash_allocation_pct": 35,
        "min_opportunity_score": 68,
        "universe_limit": 20,
    }
    monkeypatch.setattr(vr, "get_current_regime_settings", lambda: settings)
    monkeypatch.setattr(oe, "load_opportunity_watchlist", lambda limit=80: ["AAA", "BBB"])
    monkeypatch.setattr(oe, "get_smart_money_watchlist", lambda: [])
    received = {}

    def fake_score(ticker, session, horizon, include_options, stop_loss_multiplier):
        received.update({
            "horizon": horizon,
            "stop_loss_multiplier": stop_loss_multiplier,
        })
        return {"ticker": ticker, "score": 70, "price": 100}

    monkeypatch.setattr(oe, "score_ticker_opportunity", fake_score)
    result = oe.get_opportunities(session="regular", horizon="auto", limit=10)

    assert received == {"horizon": "long", "stop_loss_multiplier": 1.5}
    assert len(result["opportunities"]) == 2
    assert result["regime_settings"]["regime"] == "high_vol"
