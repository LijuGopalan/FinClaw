"""
Real-Time News Sentiment Analysis
=================================
Uses Qwen to analyze news sentiment and headline risk in real-time.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import with graceful handling of optional dependencies
try:
    from skills.financial_skills import get_news
except ImportError as e:
    logging.warning(f"Some dependencies missing: {e}")
    def get_news(ticker, limit=3):
        return {"articles": []}

from skills.llm import ask
try:
    from skills.db import get_db
except ImportError:
    logging.warning("Database module not available")
    def get_db():
        class DummyConn:
            def execute(self, *args):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return DummyConn()

logger = logging.getLogger("finclaw.sentiment")


def analyze_headline_sentiment(ticker: str, headline: str, description: str = "") -> dict:
    """
    Use Qwen to analyze sentiment of a single headline
    Returns structured JSON with sentiment classification
    """
    
    prompt = f"""Analyze this news headline for stock ${ticker}:

HEADLINE: {headline}
DESCRIPTION: {description}

Classify the sentiment and provide a risk score.

Return ONLY a valid JSON object (no markdown, no extra text) with this exact structure:
{{
  "sentiment": "bullish" OR "bearish" OR "neutral",
  "score": <number from 0-100>,
  "reasoning": "<brief 1-sentence explanation>",
  "headline_risk": "low" OR "medium" OR "high"
}}

Rules:
- bullish: positive catalysts (earnings beat, product launch, upgrade, partnership)
- bearish: negative catalysts (earnings miss, lawsuit, downgrade, regulatory issues)
- neutral: routine updates with no clear direction
- score: 0=extremely bearish, 50=neutral, 100=extremely bullish
- headline_risk: probability this moves stock significantly (low=<1%, medium=1-3%, high=>3%)

JSON response:"""

    try:
        response = ask(prompt, max_tokens=256)
        
        # Extract JSON from response (remove markdown code blocks if present)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split('\n')
            response = '\n'.join([l for l in lines if not l.startswith('```')])
        
        # Parse JSON
        sentiment_data = json.loads(response.strip())
        
        # Validate required fields
        required_fields = ['sentiment', 'score', 'reasoning', 'headline_risk']
        if not all(field in sentiment_data for field in required_fields):
            raise ValueError("Missing required fields in response")
        
        return sentiment_data
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {response}")
        return {
            "sentiment": "neutral",
            "score": 50,
            "reasoning": "Failed to analyze - parsing error",
            "headline_risk": "low"
        }
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return {
            "sentiment": "neutral",
            "score": 50,
            "reasoning": f"Analysis error: {str(e)}",
            "headline_risk": "low"
        }


def scan_watchlist_sentiment(tickers: list) -> dict:
    """
    Scan sentiment for all watchlist tickers
    Returns aggregated sentiment data
    """
    logger.info(f"Scanning sentiment for {len(tickers)} tickers...")
    
    results = {}
    alerts = []
    
    for ticker in tickers:
        try:
            # Get latest news
            news = get_news(ticker, limit=3)
            articles = news.get('articles', [])
            
            if not articles:
                continue
            
            # Analyze each article
            ticker_sentiments = []
            for article in articles[:2]:  # Top 2 articles
                headline = article.get('title', '')
                description = article.get('description', '')
                
                if headline:
                    sentiment = analyze_headline_sentiment(ticker, headline, description)
                    sentiment['headline'] = headline
                    sentiment['published_at'] = article.get('publishedAt', '')
                    sentiment['source'] = article.get('source', {}).get('name', 'Unknown')
                    ticker_sentiments.append(sentiment)
            
            if ticker_sentiments:
                # Calculate average sentiment score
                avg_score = sum(s['score'] for s in ticker_sentiments) / len(ticker_sentiments)
                
                # Check for high-risk headlines
                high_risk_headlines = [s for s in ticker_sentiments if s['headline_risk'] == 'high']
                
                results[ticker] = {
                    "avg_score": round(avg_score, 1),
                    "sentiment": "bullish" if avg_score > 60 else ("bearish" if avg_score < 40 else "neutral"),
                    "articles_analyzed": len(ticker_sentiments),
                    "details": ticker_sentiments,
                    "high_risk_count": len(high_risk_headlines)
                }
                
                # Alert on extreme sentiment or high risk
                if avg_score > 75 or avg_score < 25 or high_risk_headlines:
                    alerts.append({
                        "ticker": ticker,
                        "avg_score": avg_score,
                        "sentiment": results[ticker]["sentiment"],
                        "reason": f"{len(high_risk_headlines)} high-risk headlines" if high_risk_headlines else "Extreme sentiment"
                    })
                    
        except Exception as e:
            logger.warning(f"Failed to analyze sentiment for {ticker}: {e}")
    
    return {
        "timestamp": datetime.now().isoformat(),
        "tickers_analyzed": len(results),
        "results": results,
        "alerts": alerts
    }


def save_sentiment_scan(scan_data: dict):
    """Save sentiment scan results to database"""
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO scans (scan_type, scan_date, data)
                   VALUES (?, ?, ?)""",
                ("sentiment_scan", datetime.now().isoformat(), json.dumps(scan_data))
            )
    except Exception as e:
        logger.error(f"Failed to save sentiment scan: {e}")


def get_sentiment_alerts() -> str:
    """
    Generate formatted alert message for significant sentiment changes
    """
    # Load watchlist
    universe_path = os.path.join(os.path.dirname(__file__), "..", "data", "universe.json")
    try:
        with open(universe_path, 'r') as f:
            tickers = json.load(f)
    except:
        return "Failed to load watchlist"
    
    # Scan sentiment
    scan_data = scan_watchlist_sentiment(tickers)
    
    # Save to database
    save_sentiment_scan(scan_data)
    
    # Check if there are alerts
    alerts = scan_data.get('alerts', [])
    
    if not alerts:
        return None  # No alerts needed
    
    # Format alert message
    message = f"📰 <b>News Sentiment Alert</b>\n\n"
    message += f"Detected {len(alerts)} significant sentiment changes:\n\n"
    
    for alert in alerts[:5]:  # Top 5 alerts
        ticker = alert['ticker']
        score = alert['avg_score']
        sentiment = alert['sentiment']
        
        emoji = "🔥" if sentiment == "bullish" else ("⚠️" if sentiment == "bearish" else "📊")
        
        message += f"{emoji} <b>${ticker}</b>: {sentiment.upper()} ({score:.0f}/100)\n"
        message += f"   Reason: {alert['reason']}\n"
        
        # Add top headline
        details = scan_data['results'][ticker]['details']
        if details:
            top_headline = details[0]
            message += f"   📄 {top_headline['headline'][:80]}...\n"
        message += "\n"
    
    message += f"<i>Analyzed {scan_data['tickers_analyzed']} stocks at {datetime.now().strftime('%I:%M %p')}</i>"
    
    return message


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test single headline analysis
    print("Testing sentiment analysis...")
    result = analyze_headline_sentiment(
        "NVDA",
        "NVIDIA announces breakthrough AI chip, stock surges 8%",
        "Company unveils new GPU architecture with 2x performance improvement"
    )
    print(json.dumps(result, indent=2))
    
    # Test watchlist scan
    print("\nTesting watchlist sentiment scan...")
    scan = scan_watchlist_sentiment(["NVDA", "AAPL", "TSLA"])
    print(json.dumps(scan, indent=2))
