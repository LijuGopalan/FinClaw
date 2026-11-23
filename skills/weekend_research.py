"""
Weekend Deep Research — Comprehensive Stock Analysis
===================================================
Generates detailed research reports for watchlist stocks while markets are closed.
"""

import os
import sys
import json
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import with graceful handling of optional dependencies
try:
    from skills.financial_skills import (
        get_stock_quote, get_technical_analysis, get_fundamentals,
        get_insider_activity, get_news
    )
except ImportError as e:
    logging.warning(f"Some dependencies missing: {e}")
    # Define stub functions
    def get_stock_quote(ticker):
        return {}
    def get_technical_analysis(ticker):
        return {}
    def get_fundamentals(ticker):
        return {}
    def get_insider_activity(ticker):
        return {}
    def get_news(ticker, limit=5):
        return {"articles": []}

from skills.llm import ask
try:
    from skills.opportunity_engine import score_ticker_opportunity
except ImportError:
    def score_ticker_opportunity(**kwargs):
        return {}

logger = logging.getLogger("finclaw.weekend")


def get_watchlist_tickers():
    """Load tickers from universe.json"""
    universe_path = os.path.join(os.path.dirname(__file__), "..", "data", "universe.json")
    try:
        with open(universe_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return []


def generate_stock_research_report(ticker: str) -> dict:
    """
    Generate comprehensive research report for a single stock
    """
    logger.info(f"Generating research report for {ticker}...")
    
    try:
        # Gather all data
        quote = get_stock_quote(ticker)
        technicals = get_technical_analysis(ticker)
        fundamentals = get_fundamentals(ticker)
        insider = get_insider_activity(ticker)
        news = get_news(ticker, limit=5)
        
        # Get opportunity score
        try:
            opp_score = score_ticker_opportunity(
                ticker=ticker,
                session="closed",
                horizon="long"
            )
        except:
            opp_score = {}
        
        # Build context for Qwen
        context = f"""# Deep Research Report: ${ticker}
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Current Price & Metrics
- Price: ${quote.get('price', 'N/A')}
- 52-Week Range: ${quote.get('fifty_two_week_low', 'N/A')} - ${quote.get('fifty_two_week_high', 'N/A')}
- Market Cap: ${quote.get('market_cap', 'N/A'):,}
- Average Volume: {quote.get('average_volume', 'N/A'):,}

## Technical Analysis
- RSI (14): {technicals.get('rsi', 'N/A')}
- MACD: {technicals.get('macd', 'N/A')}
- 50-Day MA: ${technicals.get('ma_50', 'N/A')}
- 200-Day MA: ${technicals.get('ma_200', 'N/A')}
- Support: ${technicals.get('support', 'N/A')}
- Resistance: ${technicals.get('resistance', 'N/A')}

## Fundamental Analysis
- P/E Ratio: {fundamentals.get('pe_ratio', 'N/A')}
- P/B Ratio: {fundamentals.get('pb_ratio', 'N/A')}
- Profit Margin: {fundamentals.get('profit_margin', 'N/A')}%
- ROE: {fundamentals.get('roe', 'N/A')}%
- Debt/Equity: {fundamentals.get('debt_to_equity', 'N/A')}
- Forward P/E: {fundamentals.get('forward_pe', 'N/A')}

## Insider Activity
{json.dumps(insider.get('transactions', [])[:3], indent=2) if insider.get('transactions') else 'No recent insider activity'}

## Recent News Headlines
"""
        
        for i, article in enumerate(news.get('articles', [])[:5], 1):
            context += f"{i}. {article.get('title', 'N/A')} ({article.get('publishedAt', 'N/A')})\n"
        
        if opp_score:
            context += f"\n## Opportunity Score: {opp_score.get('score', 'N/A')}/100\n"
            context += f"Action: {opp_score.get('action', 'N/A')}\n"
        
        # Ask Qwen to synthesize the report
        prompt = f"""{context}

YOUR TASK:
Write a comprehensive institutional-grade research report with:

1. **Executive Summary** (2-3 sentences)
2. **Technical Setup**
   - Current trend (bullish/bearish/neutral)
   - Key support/resistance levels
   - Chart pattern analysis
3. **Fundamental Outlook**
   - Valuation assessment (cheap/fair/expensive vs sector)
   - Growth trajectory
   - Balance sheet health
4. **Catalysts & Risks**
   - Upcoming catalysts (earnings, product launches, etc.)
   - Key risks (competition, regulation, macro)
5. **Investment Thesis**
   - Bull case (why to buy)
   - Bear case (why to avoid/sell)
6. **Recommendation**
   - BUY / HOLD / SELL
   - Target price (12-month)
   - Confidence level (High/Medium/Low)

Keep analysis sharp and data-driven. Cite specific numbers. Max 600 words."""

        report = ask(prompt, max_tokens=3072)
        
        return {
            "ticker": ticker,
            "generated_at": datetime.now().isoformat(),
            "report": report,
            "data": {
                "price": quote.get('price'),
                "market_cap": quote.get('market_cap'),
                "pe_ratio": fundamentals.get('pe_ratio'),
                "opportunity_score": opp_score.get('score') if opp_score else None
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to generate report for {ticker}: {e}")
        return {
            "ticker": ticker,
            "error": str(e),
            "generated_at": datetime.now().isoformat()
        }


def weekend_deep_research_batch():
    """
    Saturday 9:00 AM: Generate research reports for all watchlist stocks
    """
    logger.info("Starting weekend deep research batch...")
    
    tickers = get_watchlist_tickers()
    if not tickers:
        return "No watchlist tickers found."
    
    reports = []
    
    # Process in parallel (max 5 concurrent to avoid rate limits)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(generate_stock_research_report, ticker): ticker 
                   for ticker in tickers}
        
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                report = future.result()
                reports.append(report)
                logger.info(f"Completed research for {ticker}")
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
    
    # Save reports to file
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "research_reports")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(output_dir, f"weekend_research_{timestamp}.json")
    
    with open(output_file, 'w') as f:
        json.dump(reports, f, indent=2)
    
    logger.info(f"Saved {len(reports)} reports to {output_file}")
    
    # Generate summary
    summary = f"""# Weekend Deep Research Complete
    
Generated {len(reports)} comprehensive research reports for watchlist stocks.
Reports saved to: {output_file}

## Top Recommendations:
"""
    
    # Extract top BUY recommendations
    buy_recs = []
    for report in reports:
        if report.get('report') and 'BUY' in report['report'][:500]:
            buy_recs.append(report)
    
    for rec in buy_recs[:5]:
        summary += f"\n### ${rec['ticker']}\n"
        # Extract first paragraph as summary
        lines = rec['report'].split('\n')
        summary += lines[0] if lines else "See full report for details."
    
    return summary


def weekly_trading_plan():
    """
    Sunday 3:00 PM: Generate trading plan for upcoming week
    """
    logger.info("Generating weekly trading plan...")
    
    tickers = get_watchlist_tickers()
    
    # Get current portfolio
    portfolio_path = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")
    try:
        with open(portfolio_path, 'r') as f:
            portfolio = json.load(f)
    except:
        portfolio = {"holdings": []}
    
    # Gather key data for all holdings
    holdings_data = []
    for holding in portfolio.get('holdings', []):
        ticker = holding.get('ticker')
        try:
            quote = get_stock_quote(ticker)
            technicals = get_technical_analysis(ticker)
            holdings_data.append({
                "ticker": ticker,
                "shares": holding.get('shares'),
                "cost_basis": holding.get('cost_basis'),
                "current_price": quote.get('price'),
                "support": technicals.get('support'),
                "resistance": technicals.get('resistance'),
                "rsi": technicals.get('rsi')
            })
        except Exception as e:
            logger.warning(f"Failed to get data for {ticker}: {e}")
    
    context = f"""# Weekly Trading Plan
Week of {datetime.now().strftime("%B %d, %Y")}

## Current Portfolio Holdings:
"""
    
    for h in holdings_data:
        context += f"\n### ${h['ticker']}\n"
        context += f"- Position: {h.get('shares', 0)} shares @ ${h.get('cost_basis', 0)}\n"
        context += f"- Current Price: ${h.get('current_price', 0)}\n"
        context += f"- Support: ${h.get('support', 'N/A')} | Resistance: ${h.get('resistance', 'N/A')}\n"
        context += f"- RSI: {h.get('rsi', 'N/A')}\n"
    
    context += f"\n## Watchlist ({len(tickers)} stocks monitored)\n"
    context += f"Tickers: {', '.join(tickers[:20])}\n"
    
    prompt = f"""{context}

YOUR TASK:
Create a detailed trading plan for the upcoming week:

1. **Holdings Management**
   - For each position: key levels to watch (support/resistance)
   - Which positions to trim if they hit resistance
   - Which positions to add to on dips to support
   - Stop-loss levels for risk management

2. **New Opportunities**
   - Top 3 watchlist stocks with best setup for entry this week
   - Specific entry price zones
   - Target prices and timeframes

3. **Market Outlook**
   - Overall market bias (bullish/bearish/neutral)
   - Key economic events this week to watch
   - Sector rotation expectations

4. **Risk Management Rules**
   - Position sizing guidelines
   - Maximum acceptable drawdown this week
   - Conditions that would trigger defensive positioning

Keep it actionable and specific. Max 500 words."""

    try:
        plan = ask(prompt, max_tokens=2560)
        
        # Save to file
        plans_dir = os.path.join(os.path.dirname(__file__), "..", "data", "trading_plans")
        os.makedirs(plans_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        plan_file = os.path.join(plans_dir, f"weekly_plan_{timestamp}.md")
        
        with open(plan_file, 'w') as f:
            f.write(plan)
        
        logger.info(f"Trading plan saved to {plan_file}")
        
        return plan
    except Exception as e:
        logger.error(f"Failed to generate trading plan: {e}")
        return "Failed to generate trading plan."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test single stock report
    print("="*60)
    print("TESTING SINGLE STOCK RESEARCH")
    print("="*60)
    report = generate_stock_research_report("NVDA")
    print(json.dumps(report, indent=2))
