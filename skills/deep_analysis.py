"""
FinClaw Deep Analysis & Red Team Trade Validation Engine
========================================================
Combines real-time market data (Schwab, technicals, fundamentals, options flow, news)
with local Qwen 2.5 reasoning to provide:
  1. Red Team Trade Validator: Adversarial risk review to kill bull traps & false breakouts
  2. Institutional Deep-Dive Memo: Multi-dimensional equity research reports (/analyze)
"""

import logging
import os
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("finclaw.deep_analysis")

try:
    from skills.llm import ask
    from skills.financial_skills import (
        get_stock_quote,
        get_technical_analysis,
        get_fundamentals,
        get_options_chain,
        get_news,
        get_insider_activity,
    )
except ImportError:
    from llm import ask
    from financial_skills import (
        get_stock_quote,
        get_technical_analysis,
        get_fundamentals,
        get_options_chain,
        get_news,
        get_insider_activity,
    )

RED_TEAM_SYSTEM_PROMPT = """You are FinClaw Red Team, an institutional hedge fund Risk Officer.
Your primary fiduciary duty is CAPITAL PRESERVATION.
Your job is to find the hidden failure modes, traps, and fatal flaws in candidate trade setups.
Do not be nice. Do not cheerlead. Be skeptical, rigorous, and direct.
Analyze the live market data and news provided and identify exactly why this trade could fail.
"""

INSTITUTIONAL_STRATEGIST_SYSTEM_PROMPT = """You are the Senior Equity Strategist at FinClaw Capital.
Write an institutional-grade investment & trade execution memo grounded strictly in the live market data provided.
Never fabricate numbers. Be concise, mathematically grounded, and decisive.
Format clearly with distinct sections and bullet points.
"""


def _gather_ticker_intelligence(ticker: str) -> dict:
    """Gather multi-dimensional market data for a ticker across all FinClaw tools."""
    ticker = ticker.upper().strip()
    
    quote = get_stock_quote(ticker) or {}
    technicals = get_technical_analysis(ticker) or {}
    fundamentals = get_fundamentals(ticker) or {}
    news = get_news(ticker=ticker, limit=5) or {}
    insiders = get_insider_activity(ticker) or {}
    options = get_options_chain(ticker) or {}

    return {
        "ticker": ticker,
        "quote": quote,
        "technicals": technicals,
        "fundamentals": fundamentals,
        "news": news.get("articles", []) if isinstance(news, dict) else [],
        "insiders": insiders,
        "options": options,
    }


def red_team_validate(ticker: str, setup_data: dict = None) -> dict:
    """
    Adversarial Red Team validation for a candidate trade.
    Scrutinizes the technical pattern, news, valuation, and market posture to
    catch bull traps, impending binary event crashes, and low-conviction setups.
    """
    data = _gather_ticker_intelligence(ticker)
    q = data["quote"]
    tech = data["technicals"]
    fund = data["fundamentals"]
    news_items = data["news"]
    
    price = setup_data.get("price") if setup_data else q.get("price")
    change_pct = q.get("change_pct", 0)
    action = setup_data.get("action", "BUY WATCH") if setup_data else "BUY WATCH"
    entry_low = setup_data.get("entry_low", "N/A") if setup_data else "Market"
    entry_high = setup_data.get("entry_high", "N/A") if setup_data else "Market"
    target = setup_data.get("target_price", "N/A") if setup_data else "N/A"
    stop = setup_data.get("stop_loss", "N/A") if setup_data else "N/A"
    thesis = setup_data.get("thesis", "Algorithmic breakout candidate") if setup_data else "Momentum candidate"
    score = setup_data.get("score", 70) if setup_data else 70

    rsi = tech.get("rsi_14", "N/A")
    atr = tech.get("atr_14", "N/A")
    bb_pos = tech.get("bb_position_pct", "N/A")

    valuation = fund.get("valuation", {}) if isinstance(fund, dict) else {}
    health = fund.get("financial_health", {}) if isinstance(fund, dict) else {}
    pe = valuation.get("pe_trailing") or fund.get("pe_ratio") or "N/A"
    de = health.get("debt_to_equity") or fund.get("debt_to_equity") or "N/A"
    mcap = fund.get("market_cap_fmt") or "N/A"

    headlines = []
    for art in news_items[:4]:
        title = art.get("title", "")
        if title:
            headlines.append(f"- {title}")
    news_str = "\n".join(headlines) if headlines else "No major recent headlines flagged."

    prompt = f"""EVALUATE THIS TRADE CANDIDATE:
Ticker: {ticker}
Action: {action} | Current Price: ${price} | Change Today: {change_pct:+}%
Proposed Plan: Entry [{entry_low} - {entry_high}] | Target: ${target} | Stop: ${stop}
Algorithmic Score: {score} | Stated Thesis: {thesis}

LIVE MARKET METRICS:
• RSI-14: {rsi} | ATR-14: ${atr} | Bollinger Band Position: {bb_pos}%
• Valuation P/E: {pe} | Debt-to-Equity: {de}% | Market Cap: {mcap}

RECENT HEADLINES:
{news_str}

Respond in this exact structured format (keep under 200 words):
VERDICT: [PASS, CAUTION, or REJECT]
RISK_SCORE: [1 to 10, where 10 is an obvious trap/extreme risk]
FAILURE_MODES:
1. <Top failure mode>
2. <Second failure mode>
KEY_INVALIDATION: <Specific price level or trigger where the trade must be abandoned>
RED_TEAM_TAKE: <1-2 sharp sentences with the unvarnished truth>
"""

    response = ask(prompt, system=RED_TEAM_SYSTEM_PROMPT, max_tokens=1500)
    
    # Parse verdict
    verdict_match = re.search(r"VERDICT:\s*(\w+)", response, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else "CAUTION"
    if verdict not in ["PASS", "CAUTION", "REJECT"]:
        verdict = "CAUTION"

    # Parse risk score
    score_match = re.search(r"RISK_SCORE:\s*(\d+)", response)
    risk_score = int(score_match.group(1)) if score_match else 5

    # Extract failure modes
    failure_modes = []
    for line in response.split("\n"):
        line_clean = line.strip()
        if re.match(r"^(\d+\.|\-|\•)\s+", line_clean) and ("FAILURE" not in line_clean.upper()):
            failure_modes.append(re.sub(r"^(\d+\.|\-|\•)\s*", "", line_clean))

    # Extract invalidation
    inval_match = re.search(r"KEY_INVALIDATION:\s*(.+)", response, re.IGNORECASE)
    invalidation = inval_match.group(1).strip() if inval_match else f"Breach below stop loss ${stop}"

    return {
        "ticker": ticker,
        "verdict": verdict,
        "risk_score": risk_score,
        "failure_modes": failure_modes[:3],
        "key_invalidation": invalidation,
        "raw_critique": response,
        "timestamp": datetime.utcnow().isoformat(),
    }


def generate_institutional_report(ticker: str) -> dict:
    """
    Generate an exhaustive institutional research memo on a ticker (/analyze command).
    Integrates technical levels, valuation, options/smart money, and Red Team risks.
    """
    intel = _gather_ticker_intelligence(ticker)
    q = intel["quote"]
    tech = intel["technicals"]
    fund = intel["fundamentals"]
    news = intel["news"]
    insiders = intel["insiders"]
    options = intel["options"]

    # Also run Red Team check
    red_team = red_team_validate(ticker)

    # Format news
    news_lines = [f"• {n.get('title')}" for n in news[:4] if n.get("title")]
    news_txt = "\n".join(news_lines) if news_lines else "No recent high-impact headlines."

    # Format insider trades
    insider_sig = insiders.get("signals", []) if isinstance(insiders, dict) else []
    insider_txt = "; ".join(insider_sig) if insider_sig else "Neutral / No unusual insider filings."

    prompt = f"""INSTITUTIONAL RESEARCH BRIEFING FOR ${ticker}:

[LIVE MARKET DATA]
• Price: ${q.get('price')} (Day Change: {q.get('change_pct', 0):+}%)
• 52-Week Range: ${q.get('low_52w')} - ${q.get('high_52w')}
• Volume: {q.get('volume', 0):,} (Data Source: {q.get('source', 'Schwab/yfinance')})

[TECHNICALS]
• RSI-14: {tech.get('rsi_14', 'N/A')}
• ATR-14: ${tech.get('atr_14', 'N/A')}
• Moving Averages: SMA-20=${tech.get('sma_20', 'N/A')} | SMA-50=${tech.get('sma_50', 'N/A')} | SMA-200=${tech.get('sma_200', 'N/A')}
• MACD: Line={tech.get('macd', 'N/A')}, Signal={tech.get('macd_signal', 'N/A')}

[FUNDAMENTALS & VALUATION]
• Market Cap: {fund.get('market_cap_fmt', 'N/A')}
• P/E: {fund.get('valuation', {}).get('pe_trailing', 'N/A')} | Forward P/E: {fund.get('valuation', {}).get('pe_forward', 'N/A')}
• Gross Margin: {fund.get('profitability', {}).get('gross_margin_pct', 'N/A')}% | Profit Margin: {fund.get('profitability', {}).get('profit_margin_pct', 'N/A')}%
• Debt-to-Equity: {fund.get('financial_health', {}).get('debt_to_equity', 'N/A')}% | Current Ratio: {fund.get('financial_health', {}).get('current_ratio', 'N/A')}

[SMART MONEY & NEWS]
• Insider Activity: {insider_txt}
• Recent News:
{news_txt}

[RED TEAM ADVERSARIAL RISK AUDIT]
• Initial Verdict: {red_team.get('verdict')} (Risk Score: {red_team.get('risk_score')}/10)
• Failure Modes: {"; ".join(red_team.get('failure_modes', []))}
• Invalidation Condition: {red_team.get('key_invalidation')}

TASK:
Synthesize this into a high-conviction institutional trade memo. Format with these exact markdown headers:
🏛️ **EXECUTIVE VERDICT**
(State: BULLISH / BEARISH / NEUTRAL | Conviction: X/10 | Primary Catalyst)

📊 **TECHNICAL STRUCTURE & KEY LEVELS**
(Support, Resistance, Trend state, Momentum)

🏢 **FUNDAMENTAL QUALITY**
(Valuation check, Balance sheet safety, Margin strength)

🛡️ **RED TEAM RISK & FAILURE MODES**
(Why this trade could blow up, key risks to monitor)

🎯 **ACTIONABLE EXECUTION PLAN**
(Entry Corridor, Hard Stop Loss, Target 1, Target 2, Risk/Reward Ratio)
"""

    report_text = ask(prompt, system=INSTITUTIONAL_STRATEGIST_SYSTEM_PROMPT, max_tokens=3000)

    return {
        "ticker": ticker,
        "price": q.get("price"),
        "change_pct": q.get("change_pct"),
        "red_team": red_team,
        "memo": report_text,
        "generated_at": datetime.utcnow().isoformat(),
    }

