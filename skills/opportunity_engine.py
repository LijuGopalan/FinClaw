"""
FinClaw Opportunity Engine
==========================
Ranks watchlist tickers for pre-market, intraday scalp, swing, and
long-term opportunity workflows. The functions in this module are designed
to be called both by the Flask API and by the OpenClaw agent.
"""

import math
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

import yaml

try:
    from schwab_client import schwab_available
except ImportError:
    from .schwab_client import schwab_available

try:
    from financial_skills import (
        get_economic_indicators,
        get_fundamentals,
        get_insider_activity,
        get_news,
        get_options_chain,
        get_sector_rotation,
        get_stock_quote,
        get_technical_analysis,
        get_price_history,
    )
except ImportError:
    from .financial_skills import (
        get_economic_indicators,
        get_fundamentals,
        get_insider_activity,
        get_news,
        get_options_chain,
        get_sector_rotation,
        get_stock_quote,
        get_technical_analysis,
        get_price_history,
    )

try:
    from smart_money_skills import get_latest_ark_trades, get_latest_congressional_trades
except ImportError:
    from .smart_money_skills import get_latest_ark_trades, get_latest_congressional_trades

try:
    from vcp_skills import detect_vcp_setup
except ImportError:
    from .vcp_skills import detect_vcp_setup

try:
    from advanced_screeners import detect_episodic_pivot, detect_mean_reversion, calculate_gamma_walls, detect_block_trades
    from portfolio_manager import calculate_trailing_stop
except ImportError:
    from .advanced_screeners import detect_episodic_pivot, detect_mean_reversion, calculate_gamma_walls, detect_block_trades
    from .portfolio_manager import calculate_trailing_stop


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "openclaw.config.yml")
ET = ZoneInfo("America/New_York")

# ── ML Model Integration (MLX-first, XGBoost fallback) ──────────────────────
_ML_MODEL  = None
_ML_LOADED = False
_ML_MODEL_KIND = None
_ML_CALIBRATION = None

class _MLXModelAdapter:
    """
    Wraps a trained MLX FinClawMLP so it exposes the same
    predict_proba(features_df) interface previously used by XGBoost.

    This lets the scoring block (lines ~570–597) remain completely unchanged:
        prob = float(model.predict_proba(features)[0][1])
    """

    def __init__(self, mlx_model, norm_mean, norm_std):
        self._model    = mlx_model
        self._mean     = norm_mean   # np.ndarray shape (5,)
        self._std      = norm_std    # np.ndarray shape (5,)

    def predict_proba(self, features_df):
        """
        Parameters
        ----------
        features_df : pd.DataFrame with columns
                      [rsi, macd_hist, atr_pct, rvol, vwap_dist]

        Returns
        -------
        np.ndarray shape (n_samples, 2) — columns: [P(0), P(1)]
        Matches the XGBoost predict_proba contract.
        """
        import numpy as np
        import mlx.core as mx

        x_raw = features_df.values.astype(np.float32)          # (N, 5)
        x_norm = (x_raw - self._mean) / self._std              # z-score
        x_mx   = mx.array(x_norm, dtype=mx.float32)

        logits = self._model(x_mx).squeeze(-1)                 # (N,)
        mx.eval(logits)

        probs_pos = 1.0 / (1.0 + np.exp(-np.array(logits)))   # sigmoid (N,)
        probs_neg = 1.0 - probs_pos

        return np.stack([probs_neg, probs_pos], axis=1)        # (N, 2)


def get_ml_model():
    """
    Load only a model with a matching, checksum-verified calibration artifact.
    """
    global _ML_MODEL, _ML_LOADED, _ML_MODEL_KIND, _ML_CALIBRATION
    if _ML_LOADED:
        return _ML_MODEL
    _ML_LOADED = True

    models_dir = os.path.join(BASE_DIR, "models")
    expected_features = ["rsi", "macd_hist", "atr_pct", "rvol", "vwap_dist"]
    try:
        from ml_pipeline.calibration import sha256_file
    except ImportError:
        from calibration import sha256_file

    for model_kind in ("mlx", "xgboost"):
        model_path = os.path.join(
            models_dir,
            "finclaw_mlx.npz" if model_kind == "mlx" else "finclaw_xgb.json",
        )
        calibration_path = os.path.join(
            models_dir,
            f"finclaw_{model_kind}_calibration.json",
        )
        try:
            import json
            with open(calibration_path) as f:
                calibration = json.load(f)
            if (
                not os.path.exists(model_path)
                or calibration.get("model_kind") != model_kind
                or calibration.get("method") != "platt"
                or calibration.get("model_sha256") != sha256_file(model_path)
                or calibration.get("feature_names") != expected_features
                or calibration.get("sample_count", 0) < 50
            ):
                print(f"Skipping {model_kind}: matching calibration artifact unavailable.")
                continue

            if model_kind == "mlx":
                import numpy as np
                import sys
                import mlx.core as mx

                config_path = os.path.join(models_dir, "finclaw_mlx_config.json")
                with open(config_path) as f:
                    cfg = json.load(f)
                ml_pipeline_dir = os.path.join(BASE_DIR, "ml_pipeline")
                if ml_pipeline_dir not in sys.path:
                    sys.path.insert(0, ml_pipeline_dir)
                from train_model_mlx import FinClawMLP

                model = FinClawMLP(
                    input_dim=cfg["input_dim"],
                    hidden_dims=cfg["hidden_dims"],
                    dropout_p=cfg["dropout_p"],
                )
                model.load_weights(model_path)
                model.eval()
                _ML_MODEL = _MLXModelAdapter(
                    model,
                    np.array(cfg["norm_mean"], dtype=np.float32),
                    np.array(cfg["norm_std"], dtype=np.float32),
                )
            else:
                import xgboost as xgb
                _ML_MODEL = xgb.XGBClassifier()
                _ML_MODEL.load_model(model_path)

            _ML_MODEL_KIND = model_kind
            _ML_CALIBRATION = calibration
            print(f"🧠 Loaded calibrated FinClaw {model_kind} model.")
            break
        except Exception as e:
            print(f"Warning: Failed to load calibrated {model_kind} model ({e}).")

    return _ML_MODEL


def _calibrate_ml_probability(probability):
    """Return a calibrated probability or None when no matching artifact exists."""
    if not _ML_CALIBRATION:
        return None
    try:
        from ml_pipeline.calibration import apply_platt_scaling
    except ImportError:
        from calibration import apply_platt_scaling
    return apply_platt_scaling(probability, _ML_CALIBRATION)




HORIZON_LABELS = {
    "scalp": "Intraday Scalp",
    "day": "Day Trade",
    "swing": "Swing Trade",
    "long": "Long-Term",
}


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _round(value, digits=2):
    value = _safe_float(value)
    return round(value, digits) if value is not None else None


def _dedupe_tickers(tickers, limit=60):
    seen = set()
    clean = []
    for raw in tickers or []:
        ticker = str(raw).strip().upper()
        if not ticker or ticker in seen:
            continue
        if len(ticker) > 12:
            continue
        seen.add(ticker)
        clean.append(ticker)
        if len(clean) >= limit:
            break
    return clean


def load_opportunity_watchlist(limit=1000):
    """
    Load tradeable tickers from data/universe.json if available, falling back
    to openclaw.config.yml monitoring.watchlists.
    This keeps OpenClaw, the API, and the dashboard on the same universe.
    """
    tickers = []
    
    # Check for local universe file first (high-frequency expansion)
    universe_path = os.path.join(BASE_DIR, "data", "universe.json")
    if os.path.exists(universe_path):
        try:
            import json
            with open(universe_path, "r") as f:
                tickers = json.load(f)
        except Exception as e:
            print(f"Error loading universe.json: {e}")

    # Fallback / merge with config watchlists
    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f) or {}
        watchlists = config.get("monitoring", {}).get("watchlists", {})
        for items in watchlists.values():
            tickers.extend(items or [])
    except Exception:
        pass

    # Inject active portfolio holdings so they are always monitored
    try:
        import json
        portfolio_path = os.path.join(BASE_DIR, "data", "portfolio.json")
        if os.path.exists(portfolio_path):
            with open(portfolio_path, "r") as f:
                port_data = json.load(f)
                for holding in port_data.get("holdings", []):
                    tickers.append(holding.get("ticker"))
    except Exception as e:
        print(f"Error loading portfolio.json into universe: {e}")

    if not tickers:
        tickers = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL"]

    return _dedupe_tickers(tickers, limit=limit)

def get_smart_money_watchlist():
    """Build a dynamic watchlist from recent ARK and Congressional buys."""
    smart_tickers = []
    try:
        ark_trades = get_latest_ark_trades(days_back=7)
        if isinstance(ark_trades, list):
            for t in ark_trades:
                if 'ticker' in t: smart_tickers.append(t['ticker'])
                
        congress_trades = get_latest_congressional_trades(days_back=14)
        if isinstance(congress_trades, list):
            for t in congress_trades:
                if t.get('type', '').upper() == 'BUY' and 'ticker' in t:
                    smart_tickers.append(t['ticker'])
    except Exception:
        pass
    return list(set(smart_tickers))


def detect_market_session(now=None):
    """Return premarket, regular, postmarket, or closed using US/Eastern market hours."""
    current = now or datetime.now(ET)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ET)
    else:
        current = current.astimezone(ET)

    if current.weekday() >= 5:
        return "closed"

    t = current.time()
    if time(4, 0) <= t < time(9, 30):
        return "premarket"
    if time(9, 30) <= t < time(16, 0):
        return "regular"
    if time(16, 0) <= t < time(20, 0):
        return "postmarket"
    return "closed"


def normalize_session(session=None):
    if not session or session == "auto":
        return detect_market_session()
    session = str(session).strip().lower()
    aliases = {
        "pre": "premarket",
        "pre-market": "premarket",
        "market": "regular",
        "intraday": "regular",
        "during": "regular",
        "after": "postmarket",
        "afterhours": "postmarket",
        "after-hours": "postmarket",
        "post": "postmarket",
        "post-market": "postmarket",
    }
    return aliases.get(session, session)


def normalize_horizon(horizon=None):
    if not horizon or horizon == "auto":
        session = detect_market_session()
        return "scalp" if session == "regular" else "swing"
    horizon = str(horizon).strip().lower()
    aliases = {
        "intraday": "scalp",
        "daytrade": "day",
        "day-trade": "day",
        "short": "swing",
        "short-term": "swing",
        "long-term": "long",
        "invest": "long",
        "investment": "long",
    }
    return aliases.get(horizon, horizon)


def get_intraday_snapshot(ticker, interval="5m", period="5d"):
    """
    Fetch compact intraday metrics for scalp/day-trade scoring.
    yfinance is delayed/unofficial; provider metadata is returned so the
    agent can cite freshness and limitations.
    """
    ticker = ticker.upper().strip()
    try:
        hist = get_price_history(ticker, period=period, interval=interval)
        if hist is None or hist.empty:
            return {"ticker": ticker, "error": "No intraday data available"}

        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            return {"ticker": ticker, "error": "No intraday close data available"}

        latest = hist.iloc[-1]
        current = _safe_float(latest.get("Close"))
        open_price = _safe_float(hist.iloc[0].get("Open"))
        prev_close = _safe_float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        high = _safe_float(hist["High"].tail(78).max())
        low = _safe_float(hist["Low"].tail(78).min())
        volume = _safe_int(latest.get("Volume"))

        avg_bar_volume = _safe_float(hist["Volume"].tail(40).mean(), 0) or 0
        relative_volume = volume / avg_bar_volume if avg_bar_volume > 0 else None

        typical = (hist["High"] + hist["Low"] + hist["Close"]) / 3
        cumulative_volume = hist["Volume"].replace(0, pd.NA).cumsum()
        vwap = (typical * hist["Volume"]).cumsum() / cumulative_volume
        vwap_value = _safe_float(vwap.iloc[-1])

        day_change_pct = ((current - open_price) / open_price * 100) if current and open_price else None
        bar_change_pct = ((current - prev_close) / prev_close * 100) if current and prev_close else None
        vwap_distance_pct = ((current - vwap_value) / vwap_value * 100) if current and vwap_value else None

        return {
            "ticker": ticker,
            "interval": interval,
            "current_price": _round(current),
            "session_open": _round(open_price),
            "session_high": _round(high),
            "session_low": _round(low),
            "day_change_pct": _round(day_change_pct),
            "bar_change_pct": _round(bar_change_pct),
            "relative_volume": _round(relative_volume),
            "vwap": _round(vwap_value),
            "vwap_distance_pct": _round(vwap_distance_pct),
            "latest_bar_volume": volume,
            "bar_count": len(hist),
            "source": "Charles Schwab" if schwab_available() else "yfinance intraday (unofficial/delayed)",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def _score_options(ticker):
    try:
        chain = get_options_chain(ticker)
    except Exception as e:
        return 0, [], {"error": str(e)}

    if chain.get("error"):
        return 0, [], chain

    unusual = chain.get("unusual_activity") or []
    top_calls = chain.get("top_call_strikes") or []
    top_puts = chain.get("top_put_strikes") or []
    put_call = _safe_float(chain.get("put_call_ratio"))
    score = 0
    flags = []

    premium_total = 0
    for item in unusual[:5]:
        premium_total += _safe_float(item.get("premium"), 0) or 0
    if unusual:
        score += min(18, len(unusual) * 5)
        flags.append(f"{len(unusual)} unusual option prints")
    if premium_total >= 250_000:
        score += 8
        flags.append(f"${premium_total/1_000_000:.1f}M unusual premium")

    call_volume = sum(_safe_int(c.get("volume")) for c in top_calls[:3])
    put_volume = sum(_safe_int(p.get("volume")) for p in top_puts[:3])
    if call_volume > 3000 and call_volume > put_volume * 1.5:
        score += 8
        flags.append("Call volume leadership")
    if put_call is not None and put_call < 0.65:
        score += 5
        flags.append(f"Low put/call ratio {put_call:.2f}")
    elif put_call is not None and put_call > 1.6:
        score -= 6
        flags.append(f"High put/call ratio {put_call:.2f}")

    return score, flags, {
        "put_call_ratio": put_call,
        "unusual_count": len(unusual),
        "top_call_volume": call_volume,
        "top_put_volume": put_volume,
        "source": chain.get("source"),
        "timestamp": chain.get("timestamp"),
    }


def _score_news(ticker, session):
    try:
        news = get_news(ticker=ticker, limit=5)
    except Exception as e:
        return 0, [], {"error": str(e)}

    articles = news.get("articles") or []
    score = 0
    flags = []
    catalyst_terms = {
        "upgrade": 8,
        "downgrade": -6,
        "raises target": 7,
        "price target": 5,
        "earnings": 5,
        "guidance": 5,
        "contract": 5,
        "partnership": 4,
        "sec": 3,
        "insider": 3,
        "ai": 3,
    }

    for article in articles[:5]:
        title = (article.get("title") or "").lower()
        description = (article.get("description") or "").lower()
        text = f"{title} {description}"
        for term, points in catalyst_terms.items():
            if term in text:
                score += points
                flags.append(term.title())
                break

    if session in ("premarket", "postmarket") and articles:
        score += 3

    return score, list(dict.fromkeys(flags))[:4], {
        "articles": articles[:3],
        "source": news.get("source"),
        "timestamp": news.get("timestamp"),
    }


def _score_insider(ticker):
    try:
        insider = get_insider_activity(ticker)
    except Exception as e:
        return 0, [], {"error": str(e)}

    summary = insider.get("summary") or {}
    buy_value = _safe_float(summary.get("buy_value"), 0) or 0
    sell_value = _safe_float(summary.get("sell_value"), 0) or 0
    buy_count = _safe_int(summary.get("buy_count"))
    sell_count = _safe_int(summary.get("sell_count"))
    score = 0
    flags = []

    if buy_count > sell_count:
        score += 7
        flags.append("Net insider buying")
    if buy_value >= 1_000_000:
        score += 8
        flags.append(f"${buy_value/1_000_000:.1f}M insider buys")
    if sell_count > max(1, buy_count * 2) and sell_value > buy_value:
        score -= 6
        flags.append("Heavy insider selling")

    return score, flags, {
        "summary": summary,
        "signals": insider.get("signals") or [],
        "source": insider.get("source"),
        "timestamp": insider.get("timestamp"),
    }


def _score_macro_context():
    score = 0
    flags = []
    try:
        econ = get_economic_indicators()
        spread = _safe_float(econ.get("yield_curve_spread"))
        if spread is not None and spread < 0:
            score -= 4
            flags.append("Inverted yield curve")
        commodities = econ.get("commodities") or {}
        oil_change = _safe_float((commodities.get("Crude Oil (WTI)") or {}).get("change_pct"))
        if oil_change is not None and oil_change > 3:
            score -= 3
            flags.append("Oil spike macro risk")
    except Exception:
        econ = {}

    try:
        sectors = get_sector_rotation()
        for signal in sectors.get("signals") or []:
            if "RISK-ON" in signal:
                score += 4
                flags.append("Risk-on sector rotation")
            elif "DEFENSIVE" in signal:
                score -= 3
                flags.append("Defensive rotation")
    except Exception:
        sectors = {}

    return score, flags, {"economic": econ, "sectors": sectors}


def _price_levels(price, atr, horizon, stop_loss_multiplier=1.0):
    if not price:
        return {"entry_low": None, "entry_high": None, "target_price": None, "stop_loss": None}

    atr = atr or price * 0.02
    stop_loss_multiplier = max(1.0, min(_safe_float(stop_loss_multiplier, 1.0), 2.0))
    if horizon == "scalp":
        entry_low = price - atr * 0.15
        entry_high = price + atr * 0.10
        target = price + atr * 0.55
        stop = price - atr * 0.35 * stop_loss_multiplier
    elif horizon == "day":
        entry_low = price - atr * 0.25
        entry_high = price + atr * 0.15
        target = price + atr * 0.90
        stop = price - atr * 0.55 * stop_loss_multiplier
    elif horizon == "long":
        entry_low = price * 0.96
        entry_high = price * 1.01
        target = price * 1.18
        stop = price * (1 - 0.10 * stop_loss_multiplier)
    else:
        entry_low = price * 0.98
        entry_high = price * 1.01
        target = price * 1.10
        stop = price * (1 - 0.06 * stop_loss_multiplier)

    return {
        "entry_low": _round(entry_low),
        "entry_high": _round(entry_high),
        "target_price": _round(target),
        "stop_loss": _round(stop),
    }


def _risk_reward(price, target, stop):
    if not all([price, target, stop]) or price <= stop:
        return None
    risk = price - stop
    reward = target - price
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def evaluate_risk_gate(quote, price, entry_low, entry_high, target, stop, risk_reward, horizon):
    """Apply non-LLM data-quality and trade-geometry vetoes to long setups."""
    vetoes = []
    quote_age_seconds = None
    price = _safe_float(price)
    entry_low = _safe_float(entry_low)
    entry_high = _safe_float(entry_high)
    target = _safe_float(target)
    stop = _safe_float(stop)
    risk_reward = _safe_float(risk_reward)

    if price is None or price <= 0:
        vetoes.append("Missing or invalid market price")
    if not quote.get("source"):
        vetoes.append("Market data source is missing")

    timestamp = quote.get("timestamp")
    if not timestamp:
        vetoes.append("Market quote timestamp is missing")
    else:
        try:
            quoted_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if quoted_at.tzinfo is None:
                quoted_at = quoted_at.replace(tzinfo=ZoneInfo("UTC"))
            quote_age_seconds = (datetime.now(ZoneInfo("UTC")) - quoted_at).total_seconds()
            if quote_age_seconds < -60 or quote_age_seconds > 300:
                vetoes.append("Market quote is stale or has an invalid timestamp")
        except (TypeError, ValueError):
            vetoes.append("Market quote timestamp is invalid")

    source = str(quote.get("source", "")).lower()
    if horizon in ("scalp", "day") and "yfinance" in source:
        vetoes.append("Unofficial yfinance data is not eligible for intraday setups")
    if price is not None and stop is not None and stop >= price:
        vetoes.append("Stop loss must be below the current price")
    if price is not None and target is not None and target <= price:
        vetoes.append("Target must be above the current price")
    if any(value is None for value in (entry_low, entry_high, target, stop)):
        vetoes.append("Entry, target, or stop levels are missing")
    elif entry_low <= 0 or entry_high < entry_low:
        vetoes.append("Entry range is invalid")
    if risk_reward is None or risk_reward < 1.2:
        vetoes.append("Risk/reward is below the 1.2:1 minimum")

    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    if bid and ask and ask >= bid and price:
        spread_pct = (ask - bid) / price * 100
        if horizon in ("scalp", "day") and spread_pct > 1.0:
            vetoes.append("Quoted spread exceeds the 1% intraday limit")

    return {
        "passed": not vetoes,
        "vetoes": vetoes,
        "quote_age_seconds": round(quote_age_seconds, 1) if quote_age_seconds is not None else None,
        "policy": "deterministic_v1",
    }


def score_ticker_opportunity(
    ticker,
    session="auto",
    horizon="auto",
    include_options=True,
    stop_loss_multiplier=1.0,
):
    """
    Score one ticker and return a structured opportunity candidate.
    The score is intentionally transparent: reasons and risk flags show
    exactly why a ticker ranked where it did.
    """
    ticker = ticker.upper().strip()
    session = normalize_session(session)
    horizon = normalize_horizon(horizon)

    score = 0
    reasons = []
    risk_flags = []
    catalyst_flags = []
    smart_money_flags = []
    source_notes = []

    quote = get_stock_quote(ticker)
    if quote.get("error"):
        return {"ticker": ticker, "score": 0, "error": quote.get("error")}

    ta = get_technical_analysis(ticker)
    if ta.get("error"):
        return {"ticker": ticker, "score": 0, "error": ta.get("error")}

    price = _safe_float(quote.get("price") or ta.get("current_price"))
    change_pct = _safe_float(quote.get("change_pct"), 0) or 0
    volume = _safe_float(quote.get("volume"), 0) or 0
    avg_volume = _safe_float(quote.get("avg_volume"), 0) or 0
    volume_ratio = _safe_float(ta.get("volume_ratio"), 1) or 1
    if avg_volume > 0 and volume > 0:
        volume_ratio = max(volume_ratio, volume / avg_volume)

    rsi = _safe_float(ta.get("rsi_14"), 50) or 50
    macd_hist = _safe_float(ta.get("macd_histogram"), 0) or 0
    atr = _safe_float(ta.get("atr_14"))
    vwap = _safe_float(ta.get("vwap"))
    support = _safe_float(ta.get("support"))
    resistance = _safe_float(ta.get("resistance"))

    intraday = {}
    if horizon in ("scalp", "day") or session in ("premarket", "regular", "postmarket"):
        intraday = get_intraday_snapshot(ticker)
        intraday_rvol = _safe_float(intraday.get("relative_volume"))
        intraday_vwap_distance = _safe_float(intraday.get("vwap_distance_pct"))
        if intraday_rvol is not None and intraday_rvol >= 1.8:
            score += 10
            reasons.append(f"Intraday relative volume {intraday_rvol:.1f}x")
        if intraday_vwap_distance is not None and intraday_vwap_distance > 0:
            score += 5
            reasons.append("Trading above intraday VWAP")
        elif intraday_vwap_distance is not None and intraday_vwap_distance < -1.5:
            score -= 5
            risk_flags.append("Below intraday VWAP")
            
    # ── ML Predictive Score (Hybrid) ──
    ml_prob = None
    try:
        model = get_ml_model()
        if model and price and atr:
            import pandas as pd
            atr_pct = (atr / price) * 100
            ml_vwap_dist = intraday_vwap_distance if intraday_vwap_distance is not None else (((price - vwap) / vwap * 100) if vwap else 0)
            ml_rvol = intraday_rvol if intraday_rvol is not None else volume_ratio
            
            features = pd.DataFrame([{
                'rsi': rsi,
                'macd_hist': macd_hist,
                'atr_pct': atr_pct,
                'rvol': ml_rvol,
                'vwap_dist': ml_vwap_dist
            }])
            
            raw_prob = float(model.predict_proba(features)[0][1])
            prob = _calibrate_ml_probability(raw_prob)
            if prob is None:
                risk_flags.append("ML probability unavailable: retrain with a matching calibration artifact")
            else:
                ml_prob = prob
            
            if prob is not None and prob > 0.65:
                bonus = int(prob * 40)
                score += bonus
                reasons.append(f"🤖 Calibrated ML probability: {prob:.1%} for a 1% upward move in 1 hour")
                catalyst_flags.append("🤖 Calibrated ML Breakout Probability")
            elif prob is not None and prob < 0.20:
                score -= 15
                risk_flags.append(f"🤖 Calibrated ML probability is low ({prob:.1%})")
    except Exception as e:
        logging.getLogger("finclaw.opportunity_engine").warning(
            "[%s] ML probability unavailable: %s", ticker, e
        )

    if abs(change_pct) >= 2:
        score += min(12, abs(change_pct) * 2)
        reasons.append(f"{change_pct:+.1f}% price move")
    if volume_ratio >= 1.5:
        score += min(12, volume_ratio * 4)
        reasons.append(f"{volume_ratio:.1f}x normal volume")

    if rsi < 35 and macd_hist > 0:
        score += 13
        reasons.append("Oversold reversal with improving MACD")
    elif rsi > 60 and macd_hist > 0:
        score += 9
        reasons.append("Momentum trend with bullish MACD")
    elif rsi > 74:
        score -= 6
        risk_flags.append("RSI overbought")
    elif rsi < 30:
        score += 6
        reasons.append("Deep oversold RSI")

    if price and vwap:
        if price > vwap:
            score += 4
            reasons.append("Above VWAP")
        else:
            score -= 3
            risk_flags.append("Below VWAP")

    if price and resistance and resistance > price:
        distance_to_resistance = (resistance - price) / price * 100
        if distance_to_resistance >= 3:
            score += 4
            reasons.append(f"{distance_to_resistance:.1f}% room to resistance")
        elif distance_to_resistance < 1:
            risk_flags.append("Near resistance")

    if price and support and price > support:
        distance_to_support = (price - support) / price * 100
        if distance_to_support <= 2:
            reasons.append("Near support")

    fund = {}
    if horizon in ("swing", "long"):
        fund = get_fundamentals(ticker)
        if not fund.get("error"):
            growth = fund.get("growth") or {}
            valuation = fund.get("valuation") or {}
            analyst = fund.get("analyst_consensus") or {}
            revenue_growth = _safe_float(growth.get("revenue_growth_pct"))
            pe_forward = _safe_float(valuation.get("pe_forward"))
            recommendation = str(analyst.get("recommendation") or "").lower()
            target_mean = _safe_float(analyst.get("target_mean"))

            if revenue_growth is not None and revenue_growth >= 12:
                score += 8
                reasons.append(f"Revenue growth {revenue_growth:.0f}%")
            if pe_forward is not None and 0 < pe_forward < 35:
                score += 4
                reasons.append(f"Forward P/E {pe_forward:.1f}")
            if "buy" in recommendation:
                score += 5
                reasons.append(f"Analyst consensus {recommendation}")
            if target_mean and price:
                upside = (target_mean - price) / price * 100
                if upside >= 12:
                    score += 8
                    reasons.append(f"Analyst target upside {upside:.0f}%")
                elif upside < 0:
                    score -= 5
                    risk_flags.append("Below analyst target upside")
        else:
            risk_flags.append("Fundamental data unavailable")

    if include_options:
        option_score, option_flags, options = _score_options(ticker)
        score += option_score
        smart_money_flags.extend(option_flags)
    else:
        options = {}

    news_score, news_flags, news = _score_news(ticker, session)
    score += news_score
    catalyst_flags.extend(news_flags)

    insider_score, insider_flags, insider = _score_insider(ticker)
    score += insider_score
    smart_money_flags.extend(insider_flags)

    # Smart Money Catalyst Check
    try:
        smart_list = get_smart_money_watchlist()
        if ticker in smart_list:
            score += 15
            reasons.append("Recent Smart Money Buy (ARK/Congress)")
            smart_money_flags.append("Smart Money Accumulation")
    except Exception:
        pass

    # VCP Screen Check
    vcp_buy_point = None
    try:
        vcp = detect_vcp_setup(ticker)
        if vcp and vcp.get("vcp_detected"):
            score += 25
            reasons.append(vcp.get("reason", "VCP breakout setup detected"))
            catalyst_flags.append("🚨 Minervini VCP Setup")
            vcp_buy_point = vcp.get("buy_point")
    except Exception:
        pass

    # Episodic Pivot (Gap & Go)
    try:
        ep = detect_episodic_pivot(ticker)
        if ep and ep.get("detected"):
            score += 30
            reasons.append(ep.get("reason"))
            catalyst_flags.append("🔥 Episodic Pivot Breakout")
    except Exception:
        pass

    # Mean Reversion (Rubber Band)
    try:
        mr = detect_mean_reversion(ticker)
        if mr and mr.get("detected"):
            score += 20
            reasons.append(mr.get("reason"))
            catalyst_flags.append("🧲 Mean Reversion Bounce")
    except Exception:
        pass
        
    # Dark Pool / Block Trade proxy
    try:
        dp = detect_block_trades(ticker)
        if dp and dp.get("detected"):
            score += 15
            reasons.append(dp.get("reason"))
            smart_money_flags.append("🐋 Massive Volume Block Detected")
    except Exception:
        pass

    # Gamma Walls (Options GEX)
    gamma_walls = None
    if include_options:
        try:
            gw = calculate_gamma_walls(ticker)
            if gw:
                gamma_walls = gw
                reasons.append(f"Gamma Support ${gw['support']} / Resistance ${gw['resistance']}")
        except Exception:
            pass

    macro_score, macro_flags, macro = _score_macro_context()
    score += macro_score
    risk_flags.extend([flag for flag in macro_flags if "risk" in flag.lower() or "defensive" in flag.lower() or "inverted" in flag.lower()])
    reasons.extend([flag for flag in macro_flags if flag not in risk_flags])

    if session == "premarket":
        if abs(change_pct) >= 1.5:
            score += 6
            reasons.append("Pre-market move worth planning")
        if not catalyst_flags and abs(change_pct) >= 3:
            risk_flags.append("Large move without identified catalyst")
    elif session == "regular" and horizon == "scalp":
        if volume_ratio < 0.8:
            score -= 6
            risk_flags.append("Light volume for scalp")
        if atr and price and atr / price < 0.01:
            score -= 4
            risk_flags.append("Low ATR for scalp")
    elif session == "postmarket":
        if catalyst_flags:
            score += 4
            reasons.append("Post-market catalyst watch")

    if quote.get("source"):
        source_notes.append(quote.get("source"))
    if ta.get("timestamp"):
        source_notes.append(f"technicals {ta.get('timestamp')}")

    score = int(max(0, min(100, round(score))))
    action = "WATCH"
    if score >= 72:
        action = "BUY WATCH"
    elif score >= 58:
        action = "ACTIVE WATCH"
    elif score < 35:
        action = "LOW PRIORITY"

    # PORTFOLIO DEFENSE ENGINE
    try:
        import json
        portfolio_path = os.path.join(BASE_DIR, "data", "portfolio.json")
        if os.path.exists(portfolio_path):
            with open(portfolio_path, "r") as f:
                port_data = json.load(f)
            for h in port_data.get("holdings", []):
                if h.get("ticker") == ticker:
                    avg_cost = h.get("avg_cost", 0)
                    if avg_cost > 0 and price:
                        profit_pct = (price - avg_cost) / avg_cost
                        
                        # Use ML probability to validate exit signals to avoid noise
                        is_ml_sell = ml_prob is not None and ml_prob < 0.35
                        
                        if rsi and rsi > 75 and profit_pct > 0.15 and is_ml_sell:
                            action = "PROFIT-TAKE"
                            score = 100
                            reasons.insert(0, f"Portfolio up {profit_pct*100:.1f}%; ML confirms reversal (prob {ml_prob:.1%})")
                        elif macd_hist and macd_hist < 0 and profit_pct < -0.05 and is_ml_sell:
                            action = "SELL/TRIM"
                            score = 100
                            risk_flags.insert(0, f"Portfolio down {profit_pct*100:.1f}%; ML confirms breakdown (prob {ml_prob:.1%})")
                        elif support and price < support and profit_pct < 0 and is_ml_sell:
                            action = "SELL/TRIM"
                            score = 100
                            risk_flags.insert(0, f"Support broken at ${support:.2f}; ML confirms breakdown (prob {ml_prob:.1%})")
    except Exception as e:
        pass

    levels = _price_levels(price, atr, horizon, stop_loss_multiplier)
    if vcp_buy_point:
        levels["entry_high"] = vcp_buy_point
        
    rr = _risk_reward(price, levels.get("target_price"), levels.get("stop_loss"))
    if rr is not None and rr < 1.2:
        risk_flags.append(f"Thin risk/reward {rr}:1")
    risk_gate = evaluate_risk_gate(
        quote,
        price,
        levels.get("entry_low"),
        levels.get("entry_high"),
        levels.get("target_price"),
        levels.get("stop_loss"),
        rr,
        horizon,
    )
    if "BUY" in action and not risk_gate["passed"]:
        action = "BLOCKED"
        risk_flags.extend(risk_gate["vetoes"])

    thesis_bits = []
    if reasons:
        thesis_bits.append("; ".join(reasons[:3]))
    if catalyst_flags:
        thesis_bits.append("Catalyst: " + ", ".join(catalyst_flags[:3]))
    if smart_money_flags:
        thesis_bits.append("Smart money: " + ", ".join(smart_money_flags[:3]))
    if not thesis_bits:
        thesis_bits.append("No high-conviction catalyst detected; keep on watchlist.")
    thesis = " ".join(thesis_bits)
    evidence = {
        "price": _round(price),
        "quote_source": quote.get("source"),
        "quote_timestamp": quote.get("timestamp"),
        "technical_indicators": {
            "rsi_14": _round(rsi),
            "macd_histogram": _round(macd_hist, 4),
            "atr_14": _round(atr),
            "vwap": _round(vwap),
            "support": _round(support),
            "resistance": _round(resistance),
        },
        "reasons": list(dict.fromkeys(reasons))[:8],
    }

    return {
        "ticker": ticker,
        "action": action,
        "session": session,
        "horizon": horizon,
        "horizon_label": HORIZON_LABELS.get(horizon, horizon.title()),
        "score": score,
        "confidence": score,
        "ml_probability": _round(ml_prob, 4),
        "price": _round(price),
        "change_pct": _round(change_pct),
        "volume_ratio": _round(volume_ratio),
        "rsi": _round(rsi),
        "macd_histogram": _round(macd_hist, 4),
        "atr": _round(atr),
        "support": _round(support),
        "resistance": _round(resistance),
        "entry_low": levels.get("entry_low"),
        "entry_high": levels.get("entry_high"),
        "target_price": levels.get("target_price"),
        "stop_loss": levels.get("stop_loss"),
        "risk_reward": rr,
        "risk_gate": risk_gate,
        "thesis": thesis,
        "evidence": evidence,
        "inference": thesis,
        "recommendation": action,
        "reasons": list(dict.fromkeys(reasons))[:8],
        "risk_flags": list(dict.fromkeys(risk_flags))[:8],
        "catalyst_flags": list(dict.fromkeys(catalyst_flags))[:8],
        "smart_money_flags": list(dict.fromkeys(smart_money_flags))[:8],
        "intraday": intraday,
        "options": options,
        "news": news,
        "insider": insider,
        "gamma_walls": gamma_walls,
        "fundamentals": fund,
        "macro": {
            "flags": macro_flags,
            "source": "get_economic_indicators + get_sector_rotation",
            "economic_timestamp": (macro.get("economic") or {}).get("timestamp"),
            "sector_timestamp": (macro.get("sectors") or {}).get("timestamp"),
        },
        "source": "FinClaw opportunity engine",
        "source_notes": source_notes,
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_opportunities(
    session="auto",
    horizon="auto",
    tickers=None,
    limit=12,
    include_options=True,
    min_score=None,
    universe_limit=None,
):
    """
    Rank opportunities across the configured OpenClaw watchlists.
    """
    try:
        from skills.volatility_regime import get_current_regime_settings
    except ImportError:
        from .volatility_regime import get_current_regime_settings
    regime_settings = get_current_regime_settings()

    session = normalize_session(session)
    if not horizon or str(horizon).strip().lower() == "auto":
        horizon = regime_settings.get("preferred_timeframe", "swing")
    horizon = normalize_horizon(horizon)
    limit = max(1, min(_safe_int(limit, 12), 50))
    regime_universe_limit = _safe_int(regime_settings.get("universe_limit"), 40)
    requested_universe_limit = (
        regime_universe_limit
        if universe_limit is None
        else min(regime_universe_limit, _safe_int(universe_limit, regime_universe_limit))
    )
    universe_limit = max(1, min(requested_universe_limit, 80))
    limit = min(limit, universe_limit)
    regime_min_score = _safe_int(regime_settings.get("min_opportunity_score"), 58)
    requested_min_score = max(0, min(_safe_int(min_score, 0), 100))
    min_score = max(regime_min_score, requested_min_score)
    stop_loss_multiplier = _safe_float(regime_settings.get("stop_loss_multiplier"), 1.0)
    
    if tickers:
        universe = _dedupe_tickers(tickers, limit=universe_limit)
    else:
        static_universe = load_opportunity_watchlist(limit=universe_limit)
        smart_universe = get_smart_money_watchlist()
        universe = _dedupe_tickers(static_universe + smart_universe, limit=universe_limit)

    candidates = []
    errors = []
    
    from concurrent.futures import ThreadPoolExecutor
    import logging
    
    def _score_worker(ticker):
        try:
            return score_ticker_opportunity(
                ticker=ticker,
                session=session,
                horizon=horizon,
                include_options=include_options,
                stop_loss_multiplier=stop_loss_multiplier,
            )
        except Exception as e:
            return {"error": str(e), "ticker": ticker}

    # Parallelism with bounded concurrency (max 6 workers to stay well under Schwab/Akamai rate limits)
    with ThreadPoolExecutor(max_workers=6) as executor:
        for result in executor.map(_score_worker, universe):
            if result.get("error"):
                errors.append({"ticker": result.get("ticker"), "error": result["error"]})
                continue
            if result.get("score", 0) >= min_score:
                candidates.append(result)

    candidates.sort(
        key=lambda item: (
            item.get("score", 0),
            item.get("volume_ratio") or 0,
            abs(item.get("change_pct") or 0),
        ),
        reverse=True,
    )

    top = candidates[:limit]
    return {
        "session": session,
        "horizon": horizon,
        "horizon_label": HORIZON_LABELS.get(horizon, horizon.title()),
        "regime_settings": regime_settings,
        "generated_at": datetime.utcnow().isoformat(),
        "universe_count": len(universe),
        "returned_count": len(top),
        "opportunities": top,
        "errors": errors[:10],
        "disclaimer": "Educational analysis only; not financial advice. Verify data independently before trading.",
    }


def build_opportunity_brief(scan_result, max_items=5, refresh_prices=True):
    """
    Compact text brief suitable for OpenClaw messages or notifications.
    
    Parameters:
        scan_result: dict - The scan result containing opportunities
        max_items: int - Maximum number of opportunities to include
        refresh_prices: bool - If True, refresh current prices before formatting alert
    """
    import logging
    logger = logging.getLogger("finclaw.opportunity_engine")
    
    session = scan_result.get("session", "market")
    horizon = scan_result.get("horizon_label", scan_result.get("horizon", "opportunities"))
    rows = scan_result.get("opportunities", [])[:max_items]
    # Filter for high-conviction scalps to avoid spam
    if "scalp" in horizon.lower():
        rows = [r for r in rows if r.get("score", 0) >= 58]

    if not rows:
        # Return None instead of a message to suppress noisy "no opportunities" alerts
        return None

    lines = [f"🎯 <b>FinClaw {session.title()} {horizon.title()} Opportunities</b>\n"]
    for item in rows:
        ticker = item.get("ticker", "")
        score = item.get("score", 0)
        action = item.get("action", "")
        rr = item.get("risk_reward")
        thesis = item.get("thesis", "")
        
        # Refresh current price before displaying alert
        original_price = item.get("price", 0)
        price = original_price
        
        if refresh_prices and ticker:
            try:
                logger.info(f"[{ticker}] Refreshing price for alert (original: ${original_price})")
                fresh_quote = get_stock_quote(ticker)
                if fresh_quote and not fresh_quote.get("error"):
                    fresh_price = _safe_float(fresh_quote.get("price"))
                    if fresh_price and fresh_price > 0:
                        price = fresh_price
                        price_change_pct = ((price - original_price) / original_price * 100) if original_price else 0
                        logger.info(f"[{ticker}] Price refreshed: ${price} ({price_change_pct:+.2f}% from scan)")
                        
                        # Recalculate price levels with fresh price
                        atr = item.get("atr")
                        horizon_key = item.get("horizon", horizon)
                        if atr:
                            fresh_levels = _price_levels(price, atr, horizon_key)
                            item.update(fresh_levels)
                            logger.info(f"[{ticker}] Levels recalculated: Entry {fresh_levels.get('entry_low')}-{fresh_levels.get('entry_high')}, Target {fresh_levels.get('target_price')}, Stop {fresh_levels.get('stop_loss')}")
                    else:
                        logger.warning(f"[{ticker}] Invalid fresh price: {fresh_price}, using original ${original_price}")
                else:
                    logger.warning(f"[{ticker}] Failed to refresh price: {fresh_quote.get('error')}, using original ${original_price}")
            except Exception as e:
                logger.error(f"[{ticker}] Error refreshing price: {e}, using original ${original_price}")
        
        # Visual cues for score
        score_emoji = "🔥" if score >= 80 else ("⚡" if score >= 60 else "📊")
        
        # Visual cues for action
        action_str = f"🟢 <b>{action}</b>" if "buy" in action.lower() or "watch" in action.lower() else f"🔴 <b>{action}</b>"
        
        levels = (
            f"Entry: <b>${item.get('entry_low')} - ${item.get('entry_high')}</b> | "
            f"Target: <b>${item.get('target_price')}</b> | Stop: <b>${item.get('stop_loss')}</b>"
        )
        gw = item.get("gamma_walls")
        if gw:
            levels += f"\n<i>Gamma: [{gw.get('support')} - {gw.get('resistance')}]</i>"
            
        rr_text = f" | R/R: <b>{rr}:1</b>" if rr is not None else ""
        
        lines.append(f"📈 <b>{ticker}</b> • {action_str} • Score: <b>{score}</b> {score_emoji}")
        lines.append(f"💵 Current Price: <b>${price}</b>")
        lines.append(f"🎯 {levels}{rr_text}")
        if thesis:
            lines.append(f"📝 <i>Thesis:</i> {thesis}")
        lines.append("──────────────") # Separator
        
    lines.append("<i>💡 Use /analyze &lt;ticker&gt; or /redteam &lt;ticker&gt; for Qwen 2.5 risk validation before entering.</i>")
    lines.append("<i>⚠️ Not financial advice. Verify current prices, liquidity, and catalysts before acting. Real-time data provided by Charles Schwab.</i>")
    return "\n".join(lines)
