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

def _extract_change_pct(quote: dict):
    """Extract percentage change from Schwab quote data."""
    for key in ("netPercentChange", "netPercentChangeInDouble", "markPercentChange"):
        val = quote.get(key)
        if val is not None:
            return round(float(val), 4)
    net = quote.get("netChange")
    close = quote.get("closePrice") or quote.get("openPrice")
    if net is not None and close:
        try:
            return round((float(net) / float(close)) * 100.0, 4)
        except ZeroDivisionError:
            pass
    return None

def _normalize_ticker(ticker: str) -> str:
    """Schwab uses '$VIX' for the CBOE Volatility Index instead of 'VIX' or '^VIX'.
    Non-equity symbols (crypto, futures, Yahoo index symbols) are skipped."""
    sym = str(ticker).strip().upper()
    if sym in ("VIX", "^VIX"):
        return "$VIX"
    if sym.startswith("^") or "=" in sym or "-USD" in sym:
        return None
    return sym

def get_quote(ticker: str) -> dict:
    global _client, _schwab_available
    if not schwab_available():
        return None
        
    schwab_sym = _normalize_ticker(ticker)
    if not schwab_sym:
        return None
    if not schwab_sym:
        return None
    try:
        r = _client.get_quote(schwab_sym)
        r.raise_for_status()
        data = r.json()
        
        # schwab-py returns a dict where the key is the ticker
        if schwab_sym not in data:
            return None
            
        quote = data[schwab_sym].get("quote", {})
        reference = data[schwab_sym].get("reference", {})
        
        return {
            "ticker": ticker,
            "price": quote.get("lastPrice"),
            "change": quote.get("netChange"),
            "change_pct": _extract_change_pct(quote),
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
        err_str = str(e).lower()
        if "invalid_client" in err_str or "invalid_grant" in err_str or "unauthorized" in err_str:
            _client = None
            _schwab_available = False
        return None

def get_quotes_batch(tickers: list) -> dict:
    global _client, _schwab_available
    if not schwab_available():
        return {}
        
    schwab_tickers = [sym for t in tickers if (sym := _normalize_ticker(t))]
    if not schwab_tickers:
        return {}
    sym_map = {sym: t for t in tickers if (sym := _normalize_ticker(t))}
    results = {}
    try:
        # Client handles multiple tickers as a list or comma-separated string
        r = _client.get_quotes(schwab_tickers)
        r.raise_for_status()
        data = r.json()
        
        for t, t_data in data.items():
            orig_t = sym_map.get(t, t)
            quote = t_data.get("quote", {})
            results[orig_t] = {
                "ticker": orig_t,
                "price": quote.get("lastPrice"),
                "change_pct": _extract_change_pct(quote),
                "volume": quote.get("totalVolume")
            }
        return results
    except Exception as e:
        logger.error(f"Schwab get_quotes_batch error: {e}")
        err_str = str(e).lower()
        if "invalid_client" in err_str or "invalid_grant" in err_str or "unauthorized" in err_str:
            _client = None
            _schwab_available = False
        return {}

def get_price_history(ticker: str, period: str = "1y", interval: str = "1d"):
    """
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y
    interval: 1m, 5m, 15m, 30m, 1d, 1wk
    Returns a list of dicts: {"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
    """
    global _client, _schwab_available
    if not schwab_available():
        return None
        
    schwab_sym = _normalize_ticker(ticker)
    if not schwab_sym:
        return None
    try:
        import schwab
        
        if interval == "1m":
            r = _client.get_price_history_every_minute(schwab_sym)
        elif interval == "5m":
            r = _client.get_price_history_every_five_minutes(schwab_sym)
        elif interval == "15m":
            r = _client.get_price_history_every_fifteen_minutes(schwab_sym)
        elif interval == "30m":
            r = _client.get_price_history_every_thirty_minutes(schwab_sym)
        elif interval in ["1wk", "1w"]:
            r = _client.get_price_history_every_week(schwab_sym)
        else: # default to 1d
            r = _client.get_price_history_every_day(schwab_sym)

        r.raise_for_status()
        data = r.json()
        
        candles = data.get("candles", [])
        
        # Slicing based on period requested
        limit = None
        if period == "5d":
            limit = 5 if interval == "1d" else 5 * 78
        elif period == "1mo":
            limit = 22 if interval == "1d" else 22 * 78
        elif period == "3mo":
            limit = 65 if interval == "1d" else 65 * 78
        elif period == "6mo":
            limit = 130 if interval == "1d" else None
        elif period == "1y":
            limit = 252 if interval == "1d" else None

        if limit and len(candles) > limit:
            candles = candles[-limit:]

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

def get_fundamentals(ticker: str) -> dict:
    """
    Fetch fundamental data from Schwab's instruments endpoint.
    Returns PE, EPS, market cap, dividend info, etc. when available.
    Falls back gracefully — returns None if Schwab doesn't have the data.
    """
    if not schwab_available():
        return None

    try:
        import schwab
        r = _client.get_instruments(ticker, schwab.client.Client.Instrument.Projection.FUNDAMENTAL)
        r.raise_for_status()
        data = r.json()

        # Schwab returns {"instruments": [{...}]} — extract first match
        instruments = data.get("instruments", [])
        if not instruments:
            # Fallback: try ticker-keyed format
            inst = data.get(ticker)
            if not inst:
                return None
        else:
            inst = instruments[0]

        fundamental = inst.get("fundamental", {})

        if not fundamental:
            return None

        return {
            "ticker": ticker,
            "name": inst.get("description"),
            "exchange": inst.get("exchange"),
            "pe_ratio": fundamental.get("peRatio"),
            "peg_ratio": fundamental.get("pegRatio"),
            "pb_ratio": fundamental.get("pbRatio"),
            "eps": fundamental.get("epsTTM"),
            "dividend_yield": fundamental.get("dividendYield"),
            "dividend_amount": fundamental.get("dividendAmount"),
            "dividend_date": fundamental.get("dividendDate"),
            "market_cap": fundamental.get("marketCap"),
            "revenue_per_share": fundamental.get("revPerShare"),
            "gross_margin_ttm": fundamental.get("grossMarginTTM"),
            "net_profit_margin_ttm": fundamental.get("netProfitMarginTTM"),
            "operating_margin_ttm": fundamental.get("operatingMarginTTM"),
            "return_on_equity": fundamental.get("returnOnEquity"),
            "return_on_assets": fundamental.get("returnOnAssets"),
            "debt_to_equity": fundamental.get("debtToEquity") or fundamental.get("totalDebtToEquity"),
            "current_ratio": fundamental.get("currentRatio"),
            "quick_ratio": fundamental.get("quickRatio"),
            "beta": fundamental.get("beta"),
            "52_week_high": fundamental.get("52WeekHigh") or fundamental.get("high52"),
            "52_week_low": fundamental.get("52WeekLow") or fundamental.get("low52"),
            "shares_outstanding": fundamental.get("sharesOutstanding"),
            "short_interest_ratio": fundamental.get("shortIntDayToCover"),
            "vol_1day_avg": fundamental.get("vol1DayAvg"),
            "vol_10day_avg": fundamental.get("vol10DayAvg"),
            "vol_3month_avg": fundamental.get("vol3MonthAvg"),
            "source": "Charles Schwab",
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Schwab get_fundamentals error for {ticker}: {e}")
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
