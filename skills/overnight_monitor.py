"""
Overnight Market Monitoring — 24/7 Qwen Intelligence
====================================================
Monitors global markets, news, and catalysts while US markets are closed.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
import pytz

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import with graceful handling of optional dependencies
try:
    from skills.financial_skills import get_news, get_stock_quote
except ImportError as e:
    # Fallback for missing dependencies - define stub functions
    logging.warning(f"Some dependencies missing: {e}")
    def get_news(ticker, limit=3):
        return {"articles": []}
    def get_stock_quote(ticker):
        return {}

from skills.llm import ask

logger = logging.getLogger("finclaw.overnight")


def get_watchlist_tickers():
    """Load tickers from universe.json"""
    universe_path = os.path.join(os.path.dirname(__file__), "..", "data", "universe.json")
    try:
        with open(universe_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return []


def overnight_news_digest():
    """
    2:00 AM CST: Scan overnight news for watchlist stocks
    """
    logger.info("Starting overnight news digest...")
    
    tickers = get_watchlist_tickers()
    if not tickers:
        return "No watchlist tickers found."
    
    # Collect news for all watchlist stocks
    news_by_ticker = {}
    for ticker in tickers[:20]:  # Limit to top 20 to avoid rate limits
        try:
            news = get_news(ticker, limit=3)
            articles = news.get("articles", [])
            if articles:
                news_by_ticker[ticker] = articles[:2]  # Top 2 articles per ticker
        except Exception as e:
            logger.warning(f"Failed to get news for {ticker}: {e}")
    
    if not news_by_ticker:
        return "No significant overnight news found."
    
    # Build context for Qwen
    context = "# Overnight News Digest — " + datetime.now().strftime("%Y-%m-%d %I:%M %p CST") + "\n\n"
    context += "## Watchlist News Summary\n\n"
    
    for ticker, articles in news_by_ticker.items():
        context += f"### ${ticker}\n"
        for article in articles:
            context += f"- **{article.get('title', 'N/A')}**\n"
            context += f"  Source: {article.get('source', {}).get('name', 'Unknown')} | "
            context += f"{article.get('publishedAt', 'Unknown')}\n"
            if article.get('description'):
                context += f"  {article.get('description')}\n"
        context += "\n"
    
    # Ask Qwen to synthesize
    prompt = f"""{context}

YOUR TASK:
Analyze the overnight news and provide:
1. **Most Important Headlines**: Top 3 stories that could move the market today
2. **Sector Trends**: Any patterns (tech bullish, energy bearish, etc.)
3. **Risk Alerts**: Any negative catalysts (lawsuits, guidance cuts, regulatory issues)
4. **Trading Implications**: Which stocks to watch at market open

Keep it under 400 words. Be sharp and actionable."""

    try:
        analysis = ask(prompt, max_tokens=2048)
        return analysis
    except Exception as e:
        logger.error(f"Qwen analysis failed: {e}")
        return context  # Return raw context as fallback


def premarket_catalyst_scan():
    """
    6:00 AM CST: Scan for pre-market catalysts
    """
    logger.info("Starting pre-market catalyst scan...")
    
    tickers = get_watchlist_tickers()
    if not tickers:
        return "No watchlist tickers found."
    
    # Get pre-market movers (stocks with significant overnight price changes)
    movers = []
    for ticker in tickers:
        try:
            quote = get_stock_quote(ticker)
            price = quote.get("price", 0)
            prev_close = quote.get("previous_close", 0)
            
            if price and prev_close and prev_close > 0:
                change_pct = ((price - prev_close) / prev_close) * 100
                
                # Flag significant pre-market moves (>2%)
                if abs(change_pct) > 2.0:
                    movers.append({
                        "ticker": ticker,
                        "price": price,
                        "prev_close": prev_close,
                        "change_pct": round(change_pct, 2),
                        "volume": quote.get("volume", 0)
                    })
        except Exception as e:
            logger.warning(f"Failed to check {ticker}: {e}")
    
    if not movers:
        return "No significant pre-market movers detected."
    
    # Sort by absolute change
    movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    
    # Build context
    context = "# Pre-Market Catalyst Scan — " + datetime.now().strftime("%Y-%m-%d %I:%M %p CST") + "\n\n"
    context += "## Pre-Market Movers\n\n"
    
    for mover in movers[:10]:  # Top 10 movers
        direction = "🟢" if mover["change_pct"] > 0 else "🔴"
        context += f"{direction} **${mover['ticker']}**: ${mover['price']} ({mover['change_pct']:+.2f}%)\n"
        context += f"   Previous Close: ${mover['prev_close']} | Volume: {mover['volume']:,}\n\n"
    
    # Ask Qwen for analysis
    prompt = f"""{context}

YOUR TASK:
Analyze these pre-market movers and provide:
1. **Biggest Catalysts**: What's driving these moves? (Check if earnings, news, sector rotation)
2. **Trading Opportunities**: Which moves are likely to continue vs. fade?
3. **Risk Assessment**: Any gap-ups that might reverse at open?
4. **Action Items**: Specific entry/exit levels to watch

Keep it under 350 words."""

    try:
        analysis = ask(prompt, max_tokens=2048)
        return analysis
    except Exception as e:
        logger.error(f"Qwen analysis failed: {e}")
        return context


def afterhours_monitoring():
    """
    Monitor after-hours price action and breaking news
    """
    logger.info("Starting after-hours monitoring...")
    
    tickers = get_watchlist_tickers()
    
    # Check for after-hours movers
    ah_movers = []
    for ticker in tickers:
        try:
            quote = get_stock_quote(ticker)
            price = quote.get("price", 0)
            close = quote.get("regularMarketPreviousClose", quote.get("previous_close", 0))
            
            if price and close and close > 0:
                change_pct = ((price - close) / close) * 100
                
                # Flag >1.5% after-hours moves
                if abs(change_pct) > 1.5:
                    ah_movers.append({
                        "ticker": ticker,
                        "price": price,
                        "close": close,
                        "change_pct": round(change_pct, 2)
                    })
        except Exception as e:
            logger.warning(f"Failed to check after-hours for {ticker}: {e}")
    
    if not ah_movers:
        return None  # No alert needed
    
    # Build context
    context = "# After-Hours Alert — " + datetime.now().strftime("%Y-%m-%d %I:%M %p CST") + "\n\n"
    context += "## Significant After-Hours Moves\n\n"
    
    for mover in sorted(ah_movers, key=lambda x: abs(x["change_pct"]), reverse=True)[:5]:
        direction = "🟢" if mover["change_pct"] > 0 else "🔴"
        context += f"{direction} **${mover['ticker']}**: ${mover['price']} ({mover['change_pct']:+.2f}%)\n"
        context += f"   Regular Close: ${mover['close']}\n\n"
    
    # Get recent news for these movers
    for mover in ah_movers[:5]:
        try:
            news = get_news(mover["ticker"], limit=2)
            articles = news.get("articles", [])
            if articles:
                context += f"### Recent News for ${mover['ticker']}:\n"
                for article in articles[:1]:
                    context += f"- {article.get('title', 'N/A')}\n"
        except:
            pass
    
    # Ask Qwen for quick analysis
    prompt = f"""{context}

YOUR TASK:
Quick after-hours analysis:
1. **Catalyst Identification**: Why are these stocks moving?
2. **Overnight Risk**: Will this hold or reverse by morning open?
3. **Action Required**: Should I adjust positions or prepare orders?

Keep it under 250 words. Be direct."""

    try:
        analysis = ask(prompt, max_tokens=1536)
        return analysis
    except Exception as e:
        logger.error(f"After-hours analysis failed: {e}")
        return context


if __name__ == "__main__":
    # Test functions
    logging.basicConfig(level=logging.INFO)
    print("\n" + "="*60)
    print("OVERNIGHT NEWS DIGEST")
    print("="*60)
    print(overnight_news_digest())
    
    print("\n" + "="*60)
    print("PRE-MARKET CATALYST SCAN")
    print("="*60)
    print(premarket_catalyst_scan())
