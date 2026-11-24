from datetime import datetime

from skills import db
from skills.signal_resolver import resolve_open_signals


def test_scan_persists_signal_evidence_and_unrealized_observations(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "signals.db"))
    db.init_db()
    scan_id = db.save_scan("regular_scalp", {
        "generated_at": datetime.utcnow().isoformat(),
        "session": "regular",
        "horizon": "scalp",
        "regime_settings": {"regime": "high_vol"},
        "opportunities": [{
            "ticker": "TEST",
            "action": "BUY WATCH",
            "score": 75,
            "price": 100.0,
            "entry_low": 99.0,
            "entry_high": 101.0,
            "target_price": 105.0,
            "stop_loss": 97.0,
            "risk_gate": {"passed": True, "vetoes": []},
            "evidence": {"price": 100.0, "quote_source": "test"},
            "inference": "Momentum setup",
            "ml_probability": 0.63,
        }],
    })

    signal = db.get_signals(limit=1)[0]
    assert signal["scan_id"] == scan_id
    assert signal["evidence_json"]["quote_source"] == "test"
    assert signal["recommendation"] == "BUY WATCH"
    assert signal["entry_filled"] is None

    db.record_signal_observation(
        signal["id"],
        102.0,
        outcome="mark_to_market",
        outcome_return_pct=2.0,
    )
    with db.get_db() as conn:
        observation = conn.execute(
            "SELECT outcome_method FROM signal_observations WHERE signal_id=?",
            (signal["id"],),
        ).fetchone()
    assert observation["outcome_method"] == "mark_to_market"


def test_signal_resolver_never_marks_unfilled_signal_as_realized():
    observations = []
    signals = [{
        "id": 1,
        "ticker": "TEST",
        "entry_filled": None,
        "price_at_signal": 100,
        "target_price": 105,
        "stop_loss": 95,
        "created_at": datetime.utcnow().isoformat(),
    }]
    result = resolve_open_signals(
        get_stock_quote_fn=lambda ticker: {"price": 110},
        get_signals_fn=lambda **kwargs: signals,
        resolve_signal_fn=lambda *args: (_ for _ in ()).throw(AssertionError("must not resolve")),
        record_observation_fn=lambda *args, **kwargs: observations.append((args, kwargs)),
    )

    assert result["awaiting_fill"] == 1
    assert observations[0][1]["outcome"] == "awaiting_fill"
