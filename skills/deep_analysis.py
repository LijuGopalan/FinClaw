"""
FinClaw Deep Analysis & Red Team Trade Validation Engine
========================================================
Combines real-time market data (Schwab, technicals, fundamentals, options flow, news)
with local Qwen 2.5 reasoning to provide:
  1. Red Team Trade Validator: Adversarial risk review to kill bull traps & false breakouts
  2. Institutional Deep-Dive Memo: Multi-dimensional equity research reports (/analyze)
"""

import logging
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("finclaw.deep_analysis")

try:
    from skills.llm import ask_json
    from skills.financial_skills import (
        get_stock_quote,
        get_technical_analysis,
        get_fundamentals,
        get_options_chain,
        get_news,
        get_insider_activity,
    )
except ImportError:
    from llm import ask_json
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

_RED_TEAM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "risk_score", "failure_modes", "key_invalidation", "inference", "recommendation"],
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "CAUTION", "REJECT"]},
        "risk_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "failure_modes": {"type": "array", "items": {"type": "string"}},
        "key_invalidation": {"type": "string"},
        "inference": {"type": "string"},
        "recommendation": {"type": "string"},
    },
}

_RESEARCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "technical_structure", "fundamental_quality", "risk_analysis",
        "inferences", "recommendation",
    ],
    "properties": {
        "technical_structure": {"type": "string"},
        "fundamental_quality": {"type": "string"},
        "risk_analysis": {"type": "string"},
        "inferences": {"type": "array", "items": {"type": "string"}},
        "recommendation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["state", "conviction", "primary_catalyst", "action_plan"],
            "properties": {
                "state": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                "conviction": {"type": "integer", "minimum": 1, "maximum": 10},
                "primary_catalyst": {"type": "string"},
                "action_plan": {"type": "string"},
            },
        },
    },
}


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
    change_pct = q.get("change_pct", 0) or 0
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

Return a structured risk assessment. Keep it under 200 words. Do not invent prices;
the invalidation must use the supplied stop or a non-price trigger. Separate your
interpretation from the supplied market facts.
"""

    result = ask_json(
        prompt,
        schema=_RED_TEAM_SCHEMA,
        system=RED_TEAM_SYSTEM_PROMPT,
        max_tokens=1500,
        task="risk",
    )
    if (
        result.get("verdict") not in {"PASS", "CAUTION", "REJECT"}
        or isinstance(result.get("risk_score"), bool)
        or not isinstance(result.get("risk_score"), int)
        or not 1 <= result["risk_score"] <= 10
        or not isinstance(result.get("failure_modes"), list)
        or not all(isinstance(item, str) for item in result["failure_modes"])
        or not isinstance(result.get("key_invalidation"), str)
        or not isinstance(result.get("inference"), str)
        or not isinstance(result.get("recommendation"), str)
    ):
        raise ValueError("Red-team response failed schema validation")

    evidence = {
        "quote": q,
        "technicals": tech,
        "fundamentals": fund,
        "headlines": [item.get("title") for item in news_items[:4] if item.get("title")],
    }

    return {
        "ticker": ticker,
        "verdict": result["verdict"],
        "risk_score": result["risk_score"],
        "failure_modes": result["failure_modes"][:3],
        "key_invalidation": result["key_invalidation"],
        "evidence": evidence,
        "inference": result["inference"],
        "recommendation": result["recommendation"],
        "raw_critique": json.dumps(result, indent=2),
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
Use only the supplied data. Separate observed evidence from inference. Do not invent
support, resistance, prices, catalysts, or financial metrics. Return fields matching
the requested response schema; action_plan must not introduce prices absent above.
"""

    analysis = ask_json(
        prompt,
        schema=_RESEARCH_SCHEMA,
        system=INSTITUTIONAL_STRATEGIST_SYSTEM_PROMPT,
        max_tokens=3000,
        task="research",
    )
    recommendation = analysis["recommendation"]
    if (
        not isinstance(recommendation, dict)
        or recommendation.get("state") not in {"BULLISH", "BEARISH", "NEUTRAL"}
        or isinstance(recommendation.get("conviction"), bool)
        or not isinstance(recommendation.get("conviction"), int)
        or not 1 <= recommendation["conviction"] <= 10
        or not all(isinstance(analysis.get(key), str) for key in (
            "technical_structure", "fundamental_quality", "risk_analysis",
        ))
        or not isinstance(analysis.get("inferences"), list)
        or not all(isinstance(item, str) for item in analysis["inferences"])
    ):
        raise ValueError("Institutional report failed schema validation")

    evidence = {
        "quote": {
            key: q.get(key)
            for key in ("price", "change_pct", "volume", "source", "timestamp")
        },
        "technicals": tech,
        "fundamentals": fund,
        "news": news[:5],
        "insider_signals": insider_sig[:10],
        "options_summary": {
            key: options.get(key)
            for key in (
                "source", "expiry", "put_call_ratio", "unusual_activity",
                "top_call_strikes", "top_put_strikes",
            )
            if isinstance(options, dict) and key in options
        },
        "red_team": red_team.get("evidence"),
    }
    memo_lines = [
        "🏛️ **EXECUTIVE VERDICT**",
        f"State: {recommendation['state']} | Conviction: {recommendation['conviction']}/10 | "
        f"Primary Catalyst: {recommendation['primary_catalyst']}",
        "",
        "📚 **OBSERVED EVIDENCE**",
        f"- Quote: {q.get('price')} ({q.get('source', 'source unavailable')}; {q.get('timestamp', 'timestamp unavailable')})",
        f"- Technical data: RSI {tech.get('rsi_14', 'N/A')}, ATR {tech.get('atr_14', 'N/A')}, "
        f"SMA-20/50/200 {tech.get('sma_20', 'N/A')}/{tech.get('sma_50', 'N/A')}/{tech.get('sma_200', 'N/A')}",
        f"- Fundamentals: market cap {fund.get('market_cap_fmt', 'N/A')}, "
        f"P/E {fund.get('valuation', {}).get('pe_trailing', 'N/A')}",
        f"- News: {news_txt.replace(chr(10), '; ')}",
        f"- Insider activity: {insider_txt}",
        "",
        "🧠 **INFERENCE**",
        *[f"- {item}" for item in analysis["inferences"]],
        "",
        "📊 **TECHNICAL STRUCTURE**",
        analysis["technical_structure"],
        "",
        "🏢 **FUNDAMENTAL QUALITY**",
        analysis["fundamental_quality"],
        "",
        "🛡️ **RISK ANALYSIS**",
        analysis["risk_analysis"],
        f"- Red-team verdict: {red_team.get('verdict')} (risk {red_team.get('risk_score')}/10)",
        f"- Failure modes: {'; '.join(red_team.get('failure_modes', []))}",
        "",
        "🎯 **RECOMMENDATION**",
        f"- Action plan: {recommendation['action_plan']}",
        f"- Red-team recommendation: {red_team.get('recommendation')}",
    ]
    report_text = "\n".join(memo_lines)

    return {
        "ticker": ticker,
        "price": q.get("price"),
        "change_pct": q.get("change_pct"),
        "red_team": red_team,
        "evidence": evidence,
        "inference": analysis["inferences"],
        "recommendation": recommendation,
        "memo": report_text,
        "generated_at": datetime.utcnow().isoformat(),
    }

