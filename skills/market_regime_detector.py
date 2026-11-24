"""
FinClaw Market Regime Detector & Portfolio Defense System
=========================================================
Proactive market correction detection with automatic sell/cash alerts.
Uses multiple indicators to detect regime changes and protect capital.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger("finclaw.market_regime")

try:
    from skills.financial_skills import get_stock_quote, get_technical_analysis, get_price_history
    from skills.llm import ask_json
except ImportError:
    from financial_skills import get_stock_quote, get_technical_analysis, get_price_history
    from llm import ask_json


_ACTION_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reasoning", "immediate_actions", "what_to_watch", "reentry_signals"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [
                "SELL ALL & GO TO CASH", "REDUCE EXPOSURE 50%", "STAY DEFENSIVE",
                "HOLD CURRENT", "BUY THE DIP",
            ],
        },
        "reasoning": {"type": "string"},
        "immediate_actions": {"type": "array", "items": {"type": "string"}},
        "what_to_watch": {"type": "array", "items": {"type": "string"}},
        "reentry_signals": {"type": "array", "items": {"type": "string"}},
    },
}


def get_market_indices() -> Dict:
    """Fetch key market indices for regime analysis."""
    indices = {
        "SPY": "S&P 500",
        "QQQ": "NASDAQ",
        "IWM": "Russell 2000",
        "DIA": "Dow Jones",
    }
    
    data = {}
    for ticker, name in indices.items():
        try:
            quote = get_stock_quote(ticker)
            tech = get_technical_analysis(ticker)
            hist = get_price_history(ticker, period="3mo", interval="1d")
            
            if quote and tech and hist is not None and not hist.empty:
                # Calculate key metrics
                price = quote.get("price", 0)
                sma_20 = tech.get("sma_20", 0)
                sma_50 = tech.get("sma_50", 0)
                sma_200 = tech.get("sma_200", 0)
                
                # Distance from moving averages
                dist_20 = ((price - sma_20) / sma_20 * 100) if sma_20 else 0
                dist_50 = ((price - sma_50) / sma_50 * 100) if sma_50 else 0
                dist_200 = ((price - sma_200) / sma_200 * 100) if sma_200 else 0
                
                # Trend strength
                above_20 = price > sma_20 if sma_20 else False
                above_50 = price > sma_50 if sma_50 else False
                above_200 = price > sma_200 if sma_200 else False
                
                # Recent drawdown
                high_52w = hist["High"].max()
                drawdown = ((price - high_52w) / high_52w * 100) if high_52w else 0
                
                data[ticker] = {
                    "name": name,
                    "price": price,
                    "change_pct": quote.get("change_pct", 0),
                    "sma_20": sma_20,
                    "sma_50": sma_50,
                    "sma_200": sma_200,
                    "dist_20": dist_20,
                    "dist_50": dist_50,
                    "dist_200": dist_200,
                    "above_20": above_20,
                    "above_50": above_50,
                    "above_200": above_200,
                    "rsi": tech.get("rsi_14", 50),
                    "macd_hist": tech.get("macd_histogram", 0),
                    "drawdown_pct": drawdown,
                }
        except Exception as e:
            logger.error(f"Failed to fetch {ticker}: {e}")
    
    return data


def get_volatility_index() -> Dict:
    """Fetch VIX for fear gauge."""
    try:
        vix_quote = get_stock_quote("VIX")
        if vix_quote:
            vix_level = vix_quote.get("price", 0)
            vix_change = vix_quote.get("change_pct", 0)
            
            # VIX interpretation
            if vix_level < 15:
                regime = "COMPLACENT"
                risk = "LOW"
            elif vix_level < 20:
                regime = "NORMAL"
                risk = "MODERATE"
            elif vix_level < 30:
                regime = "ELEVATED"
                risk = "HIGH"
            else:
                regime = "PANIC"
                risk = "EXTREME"
            
            return {
                "level": vix_level,
                "change_pct": vix_change,
                "regime": regime,
                "risk": risk,
            }
    except Exception as e:
        logger.error(f"Failed to fetch VIX: {e}")
    
    return {"level": 0, "regime": "UNKNOWN", "risk": "UNKNOWN"}


def calculate_market_breadth(watchlist: List[str]) -> Dict:
    """
    Calculate market breadth across your watchlist.
    Returns % of stocks above key moving averages.
    """
    total = len(watchlist)
    above_20 = 0
    above_50 = 0
    above_200 = 0
    advancing = 0
    
    for ticker in watchlist[:50]:  # Sample to avoid timeout
        try:
            quote = get_stock_quote(ticker)
            tech = get_technical_analysis(ticker)
            
            if quote and tech:
                price = quote.get("price", 0)
                if price > tech.get("sma_20", 0):
                    above_20 += 1
                if price > tech.get("sma_50", 0):
                    above_50 += 1
                if price > tech.get("sma_200", 0):
                    above_200 += 1
                if quote.get("change_pct", 0) > 0:
                    advancing += 1
        except Exception:
            continue
    
    sampled = min(50, total)
    return {
        "above_20_pct": (above_20 / sampled * 100) if sampled else 0,
        "above_50_pct": (above_50 / sampled * 100) if sampled else 0,
        "above_200_pct": (above_200 / sampled * 100) if sampled else 0,
        "advancing_pct": (advancing / sampled * 100) if sampled else 0,
        "sampled": sampled,
    }


def detect_market_regime(
    indices: Dict,
    vix: Dict,
    breadth: Dict,
    portfolio_drawdown: float = 0
) -> Tuple[str, int, List[str]]:
    """
    Detect current market regime and assign risk score.
    
    Returns:
        (regime, risk_score, warning_flags)
        
    Regimes:
        BULL_STRONG - Strong uptrend, low risk
        BULL_WEAK - Uptrend showing cracks
        NEUTRAL - Sideways, mixed signals
        CORRECTION - Short-term pullback (5-10%)
        BEAR_MARKET - Sustained downtrend (>10%)
        CRISIS - Severe decline (>20%)
    """
    risk_score = 0
    warnings = []
    
    spy = indices.get("SPY", {})
    qqq = indices.get("QQQ", {})
    
    # --- CHECK 1: Price vs Moving Averages ---
    if not spy.get("above_200", False):
        risk_score += 25
        warnings.append("🚨 SPY below 200-day MA (long-term bearish)")
    
    if not spy.get("above_50", False):
        risk_score += 15
        warnings.append("⚠️ SPY below 50-day MA (intermediate bearish)")
    
    if not spy.get("above_20", False):
        risk_score += 10
        warnings.append("⚠️ SPY below 20-day MA (short-term weakness)")
    
    # --- CHECK 2: Drawdown from Highs ---
    spy_dd = spy.get("drawdown_pct", 0)
    if spy_dd < -20:
        risk_score += 30
        warnings.append(f"🔴 SPY down {spy_dd:.1f}% from highs (BEAR MARKET)")
    elif spy_dd < -10:
        risk_score += 20
        warnings.append(f"🟠 SPY down {spy_dd:.1f}% from highs (CORRECTION)")
    elif spy_dd < -5:
        risk_score += 10
        warnings.append(f"🟡 SPY down {spy_dd:.1f}% from highs (Pullback)")
    
    # --- CHECK 3: VIX Fear Gauge ---
    vix_level = vix.get("level", 0)
    if vix_level > 30:
        risk_score += 25
        warnings.append(f"🚨 VIX at {vix_level:.1f} (PANIC mode)")
    elif vix_level > 20:
        risk_score += 15
        warnings.append(f"⚠️ VIX at {vix_level:.1f} (Elevated fear)")
    
    # --- CHECK 4: Market Breadth ---
    breadth_200 = breadth.get("above_200_pct", 0)
    if breadth_200 < 30:
        risk_score += 20
        warnings.append(f"🔴 Only {breadth_200:.0f}% of stocks above 200-day (WEAK breadth)")
    elif breadth_200 < 50:
        risk_score += 10
        warnings.append(f"🟠 Only {breadth_200:.0f}% of stocks above 200-day (Deteriorating)")
    
    # --- CHECK 5: Tech (QQQ) Underperformance ---
    if qqq.get("change_pct", 0) < -2 and spy.get("change_pct", 0) > -1:
        risk_score += 10
        warnings.append("⚠️ Tech underperforming (risk-off rotation)")
    
    # --- CHECK 6: Portfolio Drawdown ---
    if portfolio_drawdown < -15:
        risk_score += 20
        warnings.append(f"🚨 Your portfolio down {portfolio_drawdown:.1f}% (Critical)")
    elif portfolio_drawdown < -8:
        risk_score += 10
        warnings.append(f"⚠️ Your portfolio down {portfolio_drawdown:.1f}% (Warning)")
    
    # --- DETERMINE REGIME ---
    if risk_score >= 80:
        regime = "CRISIS"
    elif risk_score >= 60:
        regime = "BEAR_MARKET"
    elif risk_score >= 40:
        regime = "CORRECTION"
    elif risk_score >= 25:
        regime = "BULL_WEAK"
    elif risk_score >= 10:
        regime = "NEUTRAL"
    else:
        regime = "BULL_STRONG"
    
    return regime, risk_score, warnings


def generate_action_plan(
    regime: str,
    risk_score: int,
    warnings: List[str],
    indices: Dict,
    vix: Dict,
    breadth: Dict,
    portfolio_drawdown: float = 0,
) -> Dict:
    """
    Use Qwen 2.5 to generate actionable trading plan based on market regime.
    """
    spy = indices.get("SPY", {})
    qqq = indices.get("QQQ", {})
    
    # Format data for LLM
    warnings_text = "\n".join([f"  • {w}" for w in warnings])
    
    prompt = f"""MARKET REGIME ANALYSIS — IMMEDIATE ACTION REQUIRED

CURRENT MARKET STATE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Regime: {regime}
Risk Score: {risk_score}/100 (0=safe, 100=extreme)

WARNING FLAGS:
{warnings_text if warnings else "  • None — Market looks healthy"}

KEY INDICES:
  SPY (S&P 500):
    • Price: ${spy.get('price', 0):.2f} ({spy.get('change_pct', 0):+.2f}% today)
    • vs 20-day: {spy.get('dist_20', 0):+.1f}%
    • vs 50-day: {spy.get('dist_50', 0):+.1f}%
    • vs 200-day: {spy.get('dist_200', 0):+.1f}%
    • Drawdown from high: {spy.get('drawdown_pct', 0):.1f}%
  
  QQQ (Tech):
    • Price: ${qqq.get('price', 0):.2f} ({qqq.get('change_pct', 0):+.2f}% today)
    • Drawdown: {qqq.get('drawdown_pct', 0):.1f}%

FEAR GAUGE (VIX):
  • Level: {vix.get('level', 0):.1f}
  • Regime: {vix.get('regime', 'UNKNOWN')}
  • Risk: {vix.get('risk', 'UNKNOWN')}

MARKET BREADTH:
  • Above 200-day MA: {breadth.get('above_200_pct', 0):.0f}%
  • Above 50-day MA: {breadth.get('above_50_pct', 0):.0f}%
  • Advancing today: {breadth.get('advancing_pct', 0):.0f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are FinClaw Risk Officer. Based on this data, provide IMMEDIATE actionable guidance.

Return the constrained JSON object. Use only supplied facts, separate evidence-based
reasoning from suggested actions, and do not invent price levels."""

    system_prompt = """You are FinClaw Risk Officer, responsible for capital preservation.
Your job is to protect the user from severe drawdowns and market crashes.
Be proactive, decisive, and brutally honest about risk.
If the data shows danger, tell them to SELL and go to CASH.
If it's safe, tell them to HOLD or BUY.
Never be wishy-washy — give clear, actionable instructions."""

    result = ask_json(
        prompt,
        schema=_ACTION_PLAN_SCHEMA,
        system=system_prompt,
        max_tokens=2000,
        task="regime",
    )
    if (
        result.get("verdict") not in _ACTION_PLAN_SCHEMA["properties"]["verdict"]["enum"]
        or not isinstance(result.get("reasoning"), str)
        or not all(
            isinstance(result.get(key), list)
            and all(isinstance(item, str) for item in result[key])
            for key in ("immediate_actions", "what_to_watch", "reentry_signals")
        )
    ):
        raise ValueError("Market regime action plan failed schema validation")

    action_plan = "\n".join([
        f"**VERDICT:** {result['verdict']}",
        f"**REASONING:** {result['reasoning']}",
        "**IMMEDIATE ACTIONS:**",
        *[f"{i}. {item}" for i, item in enumerate(result["immediate_actions"], 1)],
        "**WHAT TO WATCH:**",
        *[f"• {item}" for item in result["what_to_watch"]],
        "**RE-ENTRY SIGNALS:**",
        *[f"• {item}" for item in result["reentry_signals"]],
    ])
    
    return {
        "regime": regime,
        "risk_score": risk_score,
        "warnings": warnings,
        "action_plan": action_plan,
        "evidence": {
            "indices": indices,
            "vix": vix,
            "breadth": breadth,
            "portfolio_drawdown": portfolio_drawdown,
        },
        "inference": result["reasoning"],
        "recommendation": result,
        "timestamp": datetime.utcnow().isoformat(),
    }


def check_market_regime_and_alert(
    watchlist: List[str],
    portfolio_drawdown: float = 0,
    send_alert: bool = True
) -> Dict:
    """
    Main function: Check market regime and generate alert if defensive action needed.
    
    Args:
        watchlist: Your ticker list
        portfolio_drawdown: Current portfolio drawdown % (negative)
        send_alert: Send Telegram alert if risk detected
    
    Returns:
        Full regime analysis with action plan
    """
    logger.info("🔍 Checking market regime...")
    
    # Gather data
    indices = get_market_indices()
    vix = get_volatility_index()
    breadth = calculate_market_breadth(watchlist)
    
    # Detect regime
    regime, risk_score, warnings = detect_market_regime(
        indices, vix, breadth, portfolio_drawdown
    )
    
    logger.info(f"Market Regime: {regime}, Risk Score: {risk_score}/100")
    
    # Generate action plan with Qwen
    result = generate_action_plan(
        regime, risk_score, warnings, indices, vix, breadth, portfolio_drawdown
    )
    
    # Send alert if defensive action needed
    if send_alert and risk_score >= 40:  # Correction or worse
        try:
            from skills.notifications import send_telegram
            
            verdict_line = result["action_plan"].split("\n")[0] if result["action_plan"] else ""
            
            alert_msg = f"""🚨 <b>MARKET REGIME ALERT</b> 🚨

<b>Regime:</b> {regime}
<b>Risk Score:</b> {risk_score}/100

<b>⚠️ WARNING FLAGS:</b>
{chr(10).join(warnings)}

<b>📊 ACTION PLAN:</b>
{result["action_plan"][:1500]}

━━━━━━━━━━━━━━━━━━━━
<i>⚡ Automatic regime detection by FinClaw Risk Officer</i>
<i>🤖 Powered by Qwen 2.5 (local)</i>"""
            
            send_telegram(alert_msg, parse_mode="HTML")
            logger.info("📱 Market regime alert sent to Telegram")
            
        except Exception as e:
            logger.error(f"Failed to send regime alert: {e}")
    
    return result


def format_regime_report(result: Dict) -> str:
    """Format regime analysis as readable text report."""
    regime = result.get("regime", "UNKNOWN")
    risk_score = result.get("risk_score", 0)
    warnings = result.get("warnings", [])
    action_plan = result.get("action_plan", "")
    
    # Emoji for regime
    regime_emoji = {
        "BULL_STRONG": "🟢",
        "BULL_WEAK": "🟡",
        "NEUTRAL": "⚪",
        "CORRECTION": "🟠",
        "BEAR_MARKET": "🔴",
        "CRISIS": "🚨"
    }.get(regime, "⚪")
    
    lines = [
        f"═══════════════════════════════════════",
        f"{regime_emoji} MARKET REGIME: {regime}",
        f"═══════════════════════════════════════",
        f"",
        f"Risk Score: {risk_score}/100",
        f"",
        f"⚠️ WARNING FLAGS:",
    ]
    
    if warnings:
        for w in warnings:
            lines.append(f"  {w}")
    else:
        lines.append("  None — Market looks healthy")
    
    lines.extend([
        f"",
        f"📋 ACTION PLAN:",
        f"",
        action_plan,
        f"",
        f"═══════════════════════════════════════",
    ])
    
    return "\n".join(lines)
