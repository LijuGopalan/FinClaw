"""
Smart Money Tracker — Congress, Insiders, ARK Invest
===================================================
Tracks trades by politicians, corporate insiders, and institutional investors.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from skills.financial_skills import get_insider_activity, get_stock_quote
except ImportError:
    def get_insider_activity(ticker):
        return {}
    def get_stock_quote(ticker):
        return {}

from skills.llm import ask

logger = logging.getLogger("finclaw.smart_money")


def track_congressional_trades():
    """
    Track congressional stock trades from public disclosures
    Uses Capitol Trades API or web scraping
    """
    logger.info("Tracking congressional trades...")
    
    # Note: Capitol Trades requires subscription. 
    # For free alternative, we'll track via public SEC disclosures
    # or use the free tier of quiverquant API
    
    trades = []
    
    try:
        # QuiverQuant free API endpoint for congressional trades
        # Sign up at quiverquant.com for API key
        api_key = os.getenv("QUIVER_API_KEY")
        
        if api_key:
            url = "https://api.quiverquant.com/beta/live/congresstrading"
            headers = {"Authorization": f"Token {api_key}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Filter for recent trades (last 7 days)
                cutoff = datetime.now() - timedelta(days=7)
                
                for trade in data:
                    trade_date = datetime.fromisoformat(trade.get('TransactionDate', ''))
                    if trade_date >= cutoff:
                        trades.append({
                            "politician": trade.get('Representative', 'Unknown'),
                            "ticker": trade.get('Ticker', ''),
                            "transaction": trade.get('Transaction', ''),
                            "amount": trade.get('Amount', ''),
                            "date": trade.get('TransactionDate', '')
                        })
        else:
            logger.warning("QUIVER_API_KEY not set - congressional tracking disabled")
            
    except Exception as e:
        logger.error(f"Failed to fetch congressional trades: {e}")
    
    return trades


def track_insider_trades(watchlist_tickers: list):
    """
    Track insider buying/selling for watchlist stocks
    """
    logger.info(f"Tracking insider trades for {len(watchlist_tickers)} stocks...")
    
    significant_trades = []
    
    for ticker in watchlist_tickers:
        try:
            insider_data = get_insider_activity(ticker)
            transactions = insider_data.get('transactions', [])
            
            # Filter for significant trades (>$100k or CEO/CFO trades)
            for txn in transactions[:5]:  # Last 5 transactions
                amount = txn.get('value', 0)
                title = txn.get('title', '').lower()
                transaction_type = txn.get('transaction', '')
                
                # Flag significant trades
                is_significant = (
                    amount > 100000 or  # >$100k
                    'ceo' in title or 
                    'cfo' in title or
                    'president' in title or
                    'director' in title
                )
                
                if is_significant:
                    significant_trades.append({
                        "ticker": ticker,
                        "insider": txn.get('insider', 'Unknown'),
                        "title": txn.get('title', 'Unknown'),
                        "transaction": transaction_type,
                        "shares": txn.get('shares', 0),
                        "value": amount,
                        "date": txn.get('date', ''),
                        "price": txn.get('price', 0)
                    })
                    
        except Exception as e:
            logger.warning(f"Failed to get insider data for {ticker}: {e}")
    
    return significant_trades


def track_ark_trades():
    """
    Track ARK Invest (Cathie Wood) daily trades
    """
    logger.info("Tracking ARK Invest trades...")
    
    trades = []
    
    try:
        # ARK publishes daily trades via their API
        url = "https://arkfunds.io/api/v1/etf/trades"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Get today's trades
            today = datetime.now().date()
            
            for trade in data.get('trades', [])[:20]:  # Last 20 trades
                trade_date_str = trade.get('date', '')
                
                try:
                    trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
                    
                    if trade_date == today or (today - trade_date).days <= 1:
                        trades.append({
                            "fund": trade.get('fund', ''),
                            "ticker": trade.get('ticker', ''),
                            "company": trade.get('company', ''),
                            "direction": trade.get('direction', ''),  # Buy or Sell
                            "shares": trade.get('shares', 0),
                            "etf_percent": trade.get('etf_percent', 0),
                            "date": trade_date_str
                        })
                except ValueError:
                    continue
                    
    except Exception as e:
        logger.error(f"Failed to fetch ARK trades: {e}")
    
    return trades


def generate_smart_money_report():
    """
    Daily smart money tracking report (6:00 PM after disclosures)
    """
    logger.info("Generating smart money report...")
    
    # Load watchlist
    universe_path = os.path.join(os.path.dirname(__file__), "..", "data", "universe.json")
    try:
        with open(universe_path, 'r') as f:
            watchlist = json.load(f)
    except:
        watchlist = []
    
    # Gather all smart money data
    congress_trades = track_congressional_trades()
    insider_trades = track_insider_trades(watchlist)
    ark_trades = track_ark_trades()
    
    # Filter for watchlist stocks
    watchlist_set = set(watchlist)
    
    congress_watchlist = [t for t in congress_trades if t['ticker'] in watchlist_set]
    ark_watchlist = [t for t in ark_trades if t['ticker'] in watchlist_set]
    
    # Check if there's anything to report
    if not (congress_watchlist or insider_trades or ark_watchlist):
        return None  # No significant smart money activity
    
    # Build context for Qwen
    context = f"""# Smart Money Tracker Report
{datetime.now().strftime("%Y-%m-%d %I:%M %p")}

## Congressional Trades (Your Watchlist)
"""
    
    if congress_watchlist:
        for trade in congress_watchlist[:5]:
            context += f"\n### {trade['politician']}\n"
            context += f"- **${trade['ticker']}**: {trade['transaction']}\n"
            context += f"- Amount: {trade['amount']}\n"
            context += f"- Date: {trade['date']}\n"
    else:
        context += "\nNo congressional trades in your watchlist this week.\n"
    
    context += "\n## Insider Activity (Your Watchlist)\n"
    
    if insider_trades:
        for trade in insider_trades[:10]:
            context += f"\n### ${trade['ticker']} — {trade['insider']} ({trade['title']})\n"
            context += f"- **{trade['transaction']}**: {trade['shares']:,} shares @ ${trade['price']}\n"
            context += f"- Total Value: ${trade['value']:,.0f}\n"
            context += f"- Date: {trade['date']}\n"
    else:
        context += "\nNo significant insider activity detected.\n"
    
    context += "\n## ARK Invest Trades (Your Watchlist)\n"
    
    if ark_watchlist:
        for trade in ark_watchlist[:10]:
            direction_emoji = "🟢" if trade['direction'].lower() == 'buy' else "🔴"
            context += f"\n{direction_emoji} **${trade['ticker']}** ({trade['company']})\n"
            context += f"- Fund: {trade['fund']}\n"
            context += f"- Direction: {trade['direction']}\n"
            context += f"- Shares: {trade['shares']:,}\n"
            context += f"- % of ETF: {trade['etf_percent']:.2f}%\n"
    else:
        context += "\nNo ARK trades in your watchlist today.\n"
    
    # Ask Qwen to analyze
    prompt = f"""{context}

YOUR TASK:
Analyze this smart money activity and provide:

1. **Most Significant Signals**
   - Which trades are most noteworthy?
   - Are insiders buying or selling?
   - Is Cathie Wood accumulating or trimming?

2. **Bullish Signals**
   - Which stocks are seeing smart money accumulation?
   - Congressional buys that align with your thesis?
   - Insider buying by CEOs/CFOs?

3. **Bearish Signals**
   - Which stocks are seeing insider selling?
   - ARK trimming positions (possible valuation concern)?
   - Congressional sells that warrant caution?

4. **Action Items**
   - Should you follow any of these trades?
   - Position adjustments to consider?
   - Stocks to add to watchlist based on smart money?

Keep it under 400 words. Be sharp and actionable."""

    try:
        analysis = ask(prompt, max_tokens=2048)
        
        # Save report
        reports_dir = os.path.join(os.path.dirname(__file__), "..", "data", "smart_money_reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        report_file = os.path.join(reports_dir, f"smart_money_{timestamp}.json")
        
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "congress_trades": congress_watchlist,
            "insider_trades": insider_trades,
            "ark_trades": ark_watchlist,
            "analysis": analysis
        }
        
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to generate smart money analysis: {e}")
        return context  # Return raw data as fallback


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("="*60)
    print("SMART MONEY TRACKER TEST")
    print("="*60)
    
    report = generate_smart_money_report()
    if report:
        print(report)
    else:
        print("No significant smart money activity today.")
