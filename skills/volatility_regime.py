"""
Volatility Regime Detection & Strategy Adjustment
================================================
Detects market volatility regimes and adjusts trading strategy accordingly.
"""

import os
import sys
import json
import logging
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from skills.financial_skills import get_stock_quote, get_price_history
except ImportError:
    def get_stock_quote(ticker):
        return {}
    def get_price_history(ticker, **kwargs):
        return None

from skills.llm import ask_json

logger = logging.getLogger("finclaw.volatility")
REGIME_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "current_regime.json")

_REGIME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "regime", "regime_changed", "position_sizing", "preferred_timeframe",
        "stop_loss_multiplier", "cash_allocation_pct", "min_opportunity_score",
        "universe_limit", "strategy_summary", "reasoning",
    ],
    "properties": {
        "regime": {"type": "string", "enum": ["low_vol", "normal", "high_vol", "extreme"]},
        "regime_changed": {"type": "boolean"},
        "position_sizing": {"type": "string", "enum": ["aggressive", "normal", "defensive"]},
        "preferred_timeframe": {"type": "string", "enum": ["auto", "scalp", "swing", "long"]},
        "stop_loss_multiplier": {"type": "number", "minimum": 1.0, "maximum": 2.0},
        "cash_allocation_pct": {"type": "integer", "minimum": 0, "maximum": 50},
        "min_opportunity_score": {"type": "integer", "minimum": 50, "maximum": 80},
        "universe_limit": {"type": "integer", "minimum": 20, "maximum": 80},
        "strategy_summary": {"type": "string"},
        "reasoning": {"type": "string"},
    },
}


def _default_regime_settings():
    return {
        "regime": "normal",
        "regime_changed": False,
        "position_sizing": "normal",
        "preferred_timeframe": "auto",
        "stop_loss_multiplier": 1.0,
        "cash_allocation_pct": 20,
        "min_opportunity_score": 58,
        "universe_limit": 40,
        "strategy_summary": "",
        "reasoning": "",
    }


def _validate_regime_settings(data):
    """Validate model and persisted settings against deterministic limits."""
    if not isinstance(data, dict):
        raise ValueError("Regime settings must be a JSON object")
    defaults = _default_regime_settings()
    result = {}
    for key, default in defaults.items():
        value = data.get(key, default)
        if key == "regime":
            value = {
                "ultra_low": "low_vol",
                "low": "low_vol",
                "neutral": "normal",
                "high": "high_vol",
            }.get(value, value)
            valid = {"low_vol", "normal", "high_vol", "extreme"}
        elif key == "position_sizing":
            valid = {"aggressive", "normal", "defensive"}
        elif key == "preferred_timeframe":
            valid = {"auto", "scalp", "swing", "long"}
        else:
            valid = None
        if valid is not None:
            if not isinstance(value, str) or value not in valid:
                raise ValueError(f"Invalid regime setting {key}: {value!r}")
        elif key == "regime_changed":
            if not isinstance(value, bool):
                raise ValueError("regime_changed must be a boolean")
        elif key == "stop_loss_multiplier":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1.0 <= value <= 2.0:
                raise ValueError("stop_loss_multiplier must be between 1.0 and 2.0")
            value = float(value)
        elif key in ("cash_allocation_pct", "min_opportunity_score", "universe_limit"):
            bounds = {
                "cash_allocation_pct": (0, 50),
                "min_opportunity_score": (50, 80),
                "universe_limit": (20, 80),
            }[key]
            if isinstance(value, bool) or not isinstance(value, int) or not bounds[0] <= value <= bounds[1]:
                raise ValueError(f"{key} must be an integer between {bounds[0]} and {bounds[1]}")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        result[key] = value
    return result


def calculate_vix_regime():
    """
    Calculate VIX regime and fear/greed state
    """
    try:
        # Get VIX quote
        vix_quote = get_stock_quote("^VIX")
        vix_current = vix_quote.get('price', 0)
        
        if not vix_current:
            return None
        
        # VIX regime classification
        if vix_current < 12:
            regime = "ultra_low"
            description = "Complacency - Low volatility, potential for mean reversion"
        elif vix_current < 15:
            regime = "low"
            description = "Normal - Healthy market conditions"
        elif vix_current < 20:
            regime = "neutral"
            description = "Elevated - Increased caution warranted"
        elif vix_current < 30:
            regime = "high"
            description = "Fear - High volatility, defensive positioning"
        else:
            regime = "extreme"
            description = "Panic - Extreme volatility, max risk-off"
        
        return {
            "vix_level": vix_current,
            "regime": regime,
            "description": description
        }
        
    except Exception as e:
        logger.error(f"Failed to calculate VIX regime: {e}")
        return None


def calculate_atr_regime(ticker: str, lookback: int = 20):
    """
    Calculate Average True Range regime for a stock
    """
    try:
        hist = get_price_history(ticker, period="3mo", interval="1d")
        
        if hist is None or hist.empty:
            return None
        
        # Calculate ATR
        high_low = hist['High'] - hist['Low']
        high_close = np.abs(hist['High'] - hist['Close'].shift())
        low_close = np.abs(hist['Low'] - hist['Close'].shift())
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=lookback).mean()
        
        current_atr = atr.iloc[-1]
        avg_atr = atr.mean()
        
        # ATR percentile (how extreme is current ATR?)
        atr_percentile = (atr < current_atr).sum() / len(atr) * 100
        
        if atr_percentile > 90:
            regime = "extreme_volatility"
        elif atr_percentile > 70:
            regime = "high_volatility"
        elif atr_percentile > 30:
            regime = "normal"
        else:
            regime = "low_volatility"
        
        return {
            "ticker": ticker,
            "current_atr": round(current_atr, 2),
            "avg_atr": round(avg_atr, 2),
            "atr_percentile": round(atr_percentile, 1),
            "regime": regime
        }
        
    except Exception as e:
        logger.warning(f"Failed to calculate ATR for {ticker}: {e}")
        return None


def calculate_market_breadth():
    """
    Calculate market breadth (SPY, QQQ, IWM correlation and divergence)
    """
    try:
        spy = get_stock_quote("SPY")
        qqq = get_stock_quote("QQQ")
        iwm = get_stock_quote("IWM")
        
        spy_change = spy.get('change_percent', 0)
        qqq_change = qqq.get('change_percent', 0)
        iwm_change = iwm.get('change_percent', 0)
        
        # Check for divergence
        all_positive = spy_change > 0 and qqq_change > 0 and iwm_change > 0
        all_negative = spy_change < 0 and qqq_change < 0 and iwm_change < 0
        
        if all_positive:
            breadth = "strong_bullish"
        elif all_negative:
            breadth = "strong_bearish"
        elif spy_change > 0 and (qqq_change < 0 or iwm_change < 0):
            breadth = "divergence_bearish"
        elif spy_change < 0 and (qqq_change > 0 or iwm_change > 0):
            breadth = "divergence_bullish"
        else:
            breadth = "mixed"
        
        return {
            "spy": spy_change,
            "qqq": qqq_change,
            "iwm": iwm_change,
            "breadth": breadth
        }
        
    except Exception as e:
        logger.error(f"Failed to calculate market breadth: {e}")
        return None


def detect_volatility_regime():
    """
    Comprehensive volatility regime detection
    Runs every 4 hours (24/7)
    """
    logger.info("Detecting volatility regime...")
    
    # Get VIX regime
    vix_regime = calculate_vix_regime()
    
    # Get market breadth
    breadth = calculate_market_breadth()
    
    # Get ATR for key indices
    spy_atr = calculate_atr_regime("SPY")
    qqq_atr = calculate_atr_regime("QQQ")
    
    # Load current regime from file
    regime_file = REGIME_FILE
    previous_regime = get_current_regime_settings()
    
    # Build context
    context = f"""# Volatility Regime Analysis
{datetime.now().strftime("%Y-%m-%d %I:%M %p")}

## VIX Analysis
"""
    
    if vix_regime:
        context += f"- VIX Level: {vix_regime['vix_level']:.2f}\n"
        context += f"- Regime: {vix_regime['regime'].replace('_', ' ').title()}\n"
        context += f"- {vix_regime['description']}\n"
    
    context += "\n## Market Breadth\n"
    
    if breadth:
        context += f"- SPY: {breadth['spy']:+.2f}%\n"
        context += f"- QQQ: {breadth['qqq']:+.2f}%\n"
        context += f"- IWM: {breadth['iwm']:+.2f}%\n"
        context += f"- Breadth: {breadth['breadth'].replace('_', ' ').title()}\n"
    
    context += "\n## Index Volatility\n"
    
    if spy_atr:
        context += f"- SPY ATR: {spy_atr['current_atr']:.2f} ({spy_atr['regime'].replace('_', ' ').title()})\n"
    
    if qqq_atr:
        context += f"- QQQ ATR: {qqq_atr['current_atr']:.2f} ({qqq_atr['regime'].replace('_', ' ').title()})\n"
    
    context += "\n## Previous Regime\n"
    context += f"- {previous_regime.get('regime', 'Unknown').replace('_', ' ').title()}\n"
    
    # Ask Qwen to analyze and recommend strategy
    prompt = f"""{context}

Classify the current market regime using only the supplied observations. Choose conservative,
bounded scan and risk settings. These settings are advisory inputs to deterministic FinClaw
limits; never recommend removing a limit. Return only an object matching the supplied schema.
"""

    try:
        regime_data = ask_json(
            prompt,
            schema=_REGIME_SCHEMA,
            max_tokens=1024,
            task="regime",
        )
        regime_data = _validate_regime_settings(regime_data)
        regime_data["regime_changed"] = regime_data["regime"] != previous_regime.get("regime")
        regime_data["timestamp"] = datetime.now().isoformat()
        regime_data["vix_level"] = vix_regime.get("vix_level") if vix_regime else None
        regime_data["market_breadth"] = breadth.get("breadth") if breadth else None

        with open(regime_file, "w") as f:
            json.dump(regime_data, f, indent=2)

        if not regime_data["regime_changed"]:
            return None

        vix_text = f"{vix_regime['vix_level']:.2f}" if vix_regime else "unavailable"
        return f"""⚠️ <b>Volatility Regime Change Detected</b>

<b>New Regime:</b> {regime_data['regime'].replace('_', ' ').title()}
<b>VIX:</b> {vix_text}

<b>Strategy Adjustments:</b>
- Position Sizing: {regime_data['position_sizing'].title()}
- Timeframe: {regime_data['preferred_timeframe'].title()}
- Cash Allocation: {regime_data['cash_allocation_pct']}%
- Min Score: {regime_data['min_opportunity_score']}

{regime_data['strategy_summary']}

<i>{regime_data['reasoning']}</i>"""

    except Exception as e:
        logger.error("Failed to generate valid volatility regime settings: %s", e)
        return None


def get_current_regime_settings():
    """
    Get validated current regime settings for use by opportunity and execution engines.
    """
    try:
        with open(REGIME_FILE, 'r') as f:
            data = json.load(f)
        settings = _validate_regime_settings(data)
        timestamp = data.get("timestamp")
        if not timestamp:
            raise ValueError("Regime settings have no timestamp")
        updated_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        now = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
        age_seconds = (now - updated_at).total_seconds()
        if age_seconds < -300 or age_seconds > 24 * 60 * 60:
            raise ValueError("Regime settings are stale or have a future timestamp")
        for key in ("timestamp", "vix_level", "market_breadth"):
            if key in data:
                settings[key] = data[key]
        return settings
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning("Using default regime settings: %s", e)
        return _default_regime_settings()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("="*60)
    print("VOLATILITY REGIME DETECTION TEST")
    print("="*60)
    
    alert = detect_volatility_regime()
    
    if alert:
        print(alert)
    else:
        print("No regime change detected")
    
    print("\n" + "="*60)
    print("CURRENT REGIME SETTINGS")
    print("="*60)
    print(json.dumps(get_current_regime_settings(), indent=2))
