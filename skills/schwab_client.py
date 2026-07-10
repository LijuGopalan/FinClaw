import os
import datetime
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("finclaw.schwab")

_client = None
_schwab_available = False

APP_KEY = os.getenv("SCHWAB_APP_KEY")
APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
CALLBACK_URL = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8080")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "schwab_token.json")

def _ensure_client():
    global _client, _schwab_available
    if _client is not None:
        return
        
    if not APP_KEY or not APP_SECRET:
        _schwab_available = False
        return

    if not os.path.exists(TOKEN_PATH):
        logger.warning(f"Schwab token file not found at {TOKEN_PATH}. Run setup_schwab.py first.")
        _schwab_available = False
        return

    try:
        import schwab
        # Create a client from the existing token file
        _client = schwab.auth.client_from_token_file(TOKEN_PATH, APP_KEY, APP_SECRET)
        _schwab_available = True
        logger.info("✅ Schwab client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Schwab client: {e}")
        _schwab_available = False

def schwab_available() -> bool:
    _ensure_client()
    return _schwab_available

def get_quote(ticker: str) -> dict:
    if not schwab_available():
        return None
        
    try:
        r = _client.get_quote(ticker)
        r.raise_for_status()
        data = r.json()
        
        # schwab-py returns a dict where the key is the ticker
        if ticker not in data:
            return None
            
        quote = data[ticker].get("quote", {})
        reference = data[ticker].get("reference", {})
        
        return {
            "ticker": ticker,
            "price": quote.get("lastPrice"),
            "change": quote.get("netChange"),
            "change_pct": quote.get("netPercentChangeInDouble"),
            "open": quote.get("openPrice"),
            "high": quote.get("highPrice"),
            "low": quote.get("lowPrice"),
            "close": quote.get("closePrice"),
            "volume": quote.get("totalVolume"),
            "high_52w": quote.get("52WeekHigh"),
            "low_52w": quote.get("52WeekLow"),
            "source": "Charles Schwab",
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Schwab get_quote error for {ticker}: {e}")
        return None

def get_quotes_batch(tickers: list) -> dict:
    if not schwab_available():
        return {}
        
    results = {}
    try:
        # Client handles multiple tickers as a list or comma-separated string
        r = _client.get_quotes(tickers)
        r.raise_for_status()
        data = r.json()
        
        for t, t_data in data.items():
            quote = t_data.get("quote", {})
            results[t] = {
                "ticker": t,
                "price": quote.get("lastPrice"),
                "change_pct": quote.get("netPercentChangeInDouble"),
                "volume": quote.get("totalVolume")
            }
        return results
    except Exception as e:
        logger.error(f"Schwab get_quotes_batch error: {e}")
        return {}

def get_price_history(ticker: str, period: str = "1y", interval: str = "1d"):
    """
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y
    interval: 1m, 5m, 15m, 30m, 1d, 1wk
    Returns a list of dicts: {"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
    """
    if not schwab_available():
        return None
        
    try:
        import schwab
        
        # Map parameters to schwab-py enums
        period_type = schwab.client.Client.PriceHistory.PeriodType.MONTH
        period_val = 1
        freq_type = schwab.client.Client.PriceHistory.FrequencyType.DAILY
        freq_val = 1
        
        if interval == "1d":
            freq_type = schwab.client.Client.PriceHistory.FrequencyType.DAILY
            freq_val = 1
            if period == "1mo":
                period_type = schwab.client.Client.PriceHistory.PeriodType.MONTH
                period_val = 1
            elif period == "3mo":
                period_type = schwab.client.Client.PriceHistory.PeriodType.MONTH
                period_val = 3
            elif period == "6mo":
                period_type = schwab.client.Client.PriceHistory.PeriodType.MONTH
                period_val = 6
            elif period == "1y":
                period_type = schwab.client.Client.PriceHistory.PeriodType.YEAR
                period_val = 1
            elif period == "5d":
                period_type = schwab.client.Client.PriceHistory.PeriodType.DAY
                period_val = 5
        elif interval in ["1m", "5m", "15m", "30m"]:
            freq_type = schwab.client.Client.PriceHistory.FrequencyType.MINUTE
            freq_val = int(interval.replace("m", ""))
            period_type = schwab.client.Client.PriceHistory.PeriodType.DAY
            period_val = 1 if period == "1d" else 5 if period == "5d" else 1

        r = _client.get_price_history_every_day(
            ticker,
            period_type=period_type,
            period=period_val,
            frequency_type=freq_type,
            frequency=freq_val
        )
        r.raise_for_status()
        data = r.json()
        
        candles = data.get("candles", [])
        formatted = []
        for c in candles:
            # Schwab returns epoch in milliseconds
            dt = datetime.datetime.fromtimestamp(c["datetime"] / 1000.0)
            formatted.append({
                "time": dt.isoformat(),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"]
            })
        return formatted
    except Exception as e:
        logger.error(f"Schwab get_price_history error for {ticker}: {e}")
        return None

def get_option_chain(ticker: str, expiry: str = None) -> dict:
    if not schwab_available():
        return None
    try:
        # If expiry is None, schwab-py handles it (gets everything, but we can just ask for all or a specific one)
        # Note: schwab-py get_option_chain is very powerful. We will get ALL chains and parse them.
        import schwab
        
        # We can specify fromDate and toDate if expiry is given
        kwargs = {}
        if expiry:
            from datetime import datetime
            try:
                dt = datetime.strptime(expiry, "%Y-%m-%d")
                kwargs["fromDate"] = dt
                kwargs["toDate"] = dt
            except:
                pass
                
        r = _client.get_option_chain(ticker, **kwargs)
        r.raise_for_status()
        data = r.json()
        
        if data.get("status") != "SUCCESS":
            return None
            
        return data
    except Exception as e:
        logger.error(f"Schwab get_option_chain error for {ticker}: {e}")
        return None
