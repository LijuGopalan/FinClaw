"""
Volatility Regime Detection & Strategy Adjustment
================================================
Detects market volatility regimes and adjusts trading strategy accordingly.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from skills.financial_skills import get_stock_quote, get_price_history
except ImportError:
    def get_stock_quote(ticker):
        return {}
    def get_price_history(ticker, **kwargs):
        return None

from skills.llm import ask

logger = logging.getLogger("finclaw.volatility")


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
    regime_file = os.path.join(
        os.path.dirname(__file__), "..", "data", "current_regime.json"
    )
    
    try:
        with open(regime_file, 'r') as f:
            previous_regime = json.load(f)
    except:
        previous_regime = {"regime": "unknown"}
    
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
    
    context += f"\n## Previous Regime\n"
    context += f"- {previous_regime.get('regime', 'Unknown').replace('_', ' ').title()}\n"
    
    # Ask Qwen to analyze and recommend strategy
    prompt = f"""{context}

YOUR TASK:
Analyze the volatility regime and provide:

1. **Current Regime Classification**
   - What is the overall market regime? (Low Vol / Normal / High Vol / Extreme)
   - Has the regime changed from before?

2. **Trading Strategy Adjustments**
   - Position sizing (increase/decrease/maintain)
   - Preferred timeframes (scalp/swing/position)
   - Risk management rules
   - Stop-loss widths (tighter/wider than normal)

3. **Sector/Style Preferences**
   - Growth vs. Value
   - Large cap vs. Small cap
   - Sector rotation to favor

4. **Specific Actions**
   - Raise cash? (what %)
   - Reduce leverage?
   - Focus on defensive stocks?
   - Opportunity to be aggressive?

5. **Alert Thresholds**
   - Should we raise/lower opportunity score thresholds?
   - Adjust universe_limit for scans?
   - Change min_score requirements?

Return your analysis in this JSON format (ONLY JSON, no markdown):
{{
  "regime": "low_vol" | "normal" | "high_vol" | "extreme",
  "regime_changed": true | false,
  "position_sizing": "aggressive" | "normal" | "defensive",
  "preferred_timeframe": "scalp" | "swing" | "long",
  "stop_loss_multiplier": 1.0-2.0,
  "cash_allocation_pct": 0-50,
  "min_opportunity_score": 50-80,
  "universe_limit": 20-80,
  "strategy_summary": "<2-3 sentence summary>",
  "reasoning": "<brief explanation>"
}}"""

    try:
        response = ask(prompt, max_tokens=1024)
        
        # Parse JSON response
        response = response.strip()
        if response.startswith("```"):
            lines = response.split('\n')
            response = '\n'.join([l for l in lines if not l.startswith('```')])
        
        regime_data = json.loads(response.strip())
        
        # Add metadata
        regime_data["timestamp"] = datetime.now().isoformat()
        regime_data["vix_level"] = vix_regime.get('vix_level') if vix_regime else None
        regime_data["market_breadth"] = breadth.get('breadth') if breadth else None
        
        # Save current regime
        with open(regime_file, 'w') as f:
            json.dump(regime_data, f, indent=2)
        
        # Check if regime changed
        if regime_data.get('regime_changed'):
            # Return alert message
            summary = regime_data.get('strategy_summary', '')
            return f"""⚠️ <b>Volatility Regime Change Detected</b>

<b>New Regime:</b> {regime_data['regime'].replace('_', ' ').title()}
<b>VIX:</b> {vix_regime['vix_level']:.2f}

<b>Strategy Adjustments:</b>
- Position Sizing: {regime_data['position_sizing'].title()}
- Timeframe: {regime_data['preferred_timeframe'].title()}
- Cash Allocation: {regime_data['cash_allocation_pct']}%
- Min Score: {regime_data['min_opportunity_score']}

{summary}

<i>{regime_data.get('reasoning', '')}</i>"""
        
        return None  # No alert if regime unchanged
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse regime JSON: {response}")
        # Save raw analysis anyway
        regime_data = {
            "regime": vix_regime.get('regime') if vix_regime else "unknown",
            "timestamp": datetime.now().isoformat(),
            "raw_analysis": response
        }
        with open(regime_file, 'w') as f:
            json.dump(regime_data, f, indent=2)
        return None
        
    except Exception as e:
        logger.error(f"Failed to detect regime: {e}")
        return None


def get_current_regime_settings():
    """
    Get current regime settings for use by opportunity engine
    """
    regime_file = os.path.join(
        os.path.dirname(__file__), "..", "data", "current_regime.json"
    )
    
    try:
        with open(regime_file, 'r') as f:
            return json.load(f)
    except:
        # Return default settings
        return {
            "regime": "normal",
            "position_sizing": "normal",
            "min_opportunity_score": 58,
            "universe_limit": 40,
            "stop_loss_multiplier": 1.0
        }


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
