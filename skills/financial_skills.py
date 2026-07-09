"""
FinClaw Skills — Financial Data Tools for OpenClaw
===================================================
These Python functions act as "skills" (tools) that the OpenClaw agent
calls when it needs real financial data. Each skill connects to an
approved data source and returns structured data.

Data source priority
--------------------
    1. Charles Schwab Market Data API  (production-grade, real-time)
       → schwab_client.py handles OAuth2 + token management
    2. Tradier API  (real-time, requires funded brokerage account)
    3. yfinance  (unofficial Yahoo Finance scraper — last resort)

Requirements:
    pip install schwab-py yfinance requests python-dotenv pandas ta

First-time Schwab auth
----------------------
    python skills/schwab_client.py
    # Follow the browser prompt, then restart the server.

Usage: The agent calls these via MCP (Model Context Protocol) or
       directly via OpenClaw's skills system.
"""

import os
import json
import time
import logging
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from functools import wraps

load_dotenv()

# Charles Schwab client (primary data source — lazy-initialised)
try:
    from schwab_client import (
        schwab_available,
        get_quote          as _schwab_quote,
        get_quotes_batch   as _schwab_quotes_batch,
        get_price_history  as _schwab_price_history,
        get_intraday_history as _schwab_intraday_history,
        get_option_chain   as _schwab_option_chain,
        get_movers         as _schwab_movers,
        get_market_hours   as _schwab_market_hours,
    )
    logger_temp = logging.getLogger("finclaw.skills")
    logger_temp.info("schwab_client imported — will activate once token is present")
except ImportError:
    schwab_available    = lambda: False  # noqa: E731
    _schwab_quote       = lambda *a, **k: None  # noqa: E731
    _schwab_quotes_batch= lambda *a, **k: {}  # noqa: E731
    _schwab_price_history = lambda *a, **k: None  # noqa: E731
    _schwab_intraday_history = lambda *a, **k: None  # noqa: E731
    _schwab_option_chain= lambda *a, **k: None  # noqa: E731
    _schwab_movers      = lambda *a, **k: None  # noqa: E731
    _schwab_market_hours= lambda *a, **k: None  # noqa: E731

# ============================================================
# LOGGING
# ============================================================
logger = logging.getLogger("finclaw.skills")

# ============================================================
# CONFIGURATION
# ============================================================
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "demo")
TRADIER_KEY       = os.getenv("TRADIER_API_KEY", "")
NEWS_API_KEY      = os.getenv("NEWS_API_KEY", "")

TRADIER_BASE      = "https://api.tradier.com/v1"
AV_BASE           = "https://www.alphavantage.co/query"
NEWS_BASE         = "https://newsapi.org/v2"

# Base directory for data files (one level up from skills/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# CACHING LAYER — prevents API rate limit exhaustion
# ============================================================
_cache = {}
_cache_write_count = 0

def _evict_expired():
    """Remove all expired cache entries to prevent memory leaks."""
    now = time.time()
    expired_keys = [k for k, (_, ts) in _cache.items() if now - ts > 3600]
    for k in expired_keys:
        del _cache[k]
    if expired_keys:
        logger.debug("Cache eviction: removed %d expired entries", len(expired_keys))

def cached(ttl_seconds=30):
    """
    Decorator that caches function results in memory with a TTL.
    - Stock quotes: 30s
    - Technical analysis: 300s (5 min)
    - Options: 60s
    - News: 600s (10 min)
    - Fundamentals: 3600s (1 hour)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            global _cache_write_count
            # Build cache key from function name + arguments
            key = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            now = time.time()

            if key in _cache:
                result, timestamp = _cache[key]
                if now - timestamp < ttl_seconds:
                    return result

            result = func(*args, **kwargs)
            _cache[key] = (result, now)

            # Periodic eviction every 100 writes
            _cache_write_count += 1
            if _cache_write_count % 100 == 0:
                _evict_expired()

            return result
        return wrapper
    return decorator


def clear_cache():
    """Clear all cached data."""
    global _cache
    _cache = {}
    logger.info("Cache cleared")


def get_cache_stats():
    """Return cache statistics."""
    now = time.time()
    total = len(_cache)
    expired = sum(1 for _, (_, ts) in _cache.items() if now - ts > 3600)
    return {"total_entries": total, "expired": expired, "active": total - expired}


# ============================================================
# SKILL: Get Stock Quote
# ============================================================
@cached(ttl_seconds=30)
def get_stock_quote(ticker: str) -> dict:
    """
    Returns real-time price data for a ticker symbol.

    Priority:
      1. Charles Schwab (production API — OAuth2 token required)
      2. Tradier        (real-time, funded account required)
      3. yfinance       (unofficial scraper — last resort)
    """
    ticker = ticker.upper().strip()

    # ── 1. Charles Schwab (production) ───────────────────────────────────────
    if schwab_available():
        result = _schwab_quote(ticker)
        if result and result.get("price") is not None:
            logger.debug("[Schwab] quote %s = $%.2f", ticker, result["price"])
            return result
        logger.debug("Schwab quote returned nothing for %s — trying Tradier", ticker)

    # ── 2. Tradier (real-time, requires funded account) ───────────────────────
    if TRADIER_KEY:
        headers = {
            "Authorization": f"Bearer {TRADIER_KEY}",
            "Accept": "application/json"
        }
        try:
            r = requests.get(
                f"{TRADIER_BASE}/markets/quotes",
                params={"symbols": ticker},
                headers=headers,
                timeout=10
            )
            r.raise_for_status()
            data = r.json()
            quote = data.get("quotes", {}).get("quote", {})
            if quote:
                return {
                    "ticker": ticker,
                    "price": quote.get("last"),
                    "open": quote.get("open"),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "close": quote.get("close"),
                    "change": quote.get("change"),
                    "change_pct": quote.get("change_percentage"),
                    "volume": quote.get("volume"),
                    "avg_volume": quote.get("average_volume"),
                    "high_52w": quote.get("week_52_high"),
                    "low_52w":  quote.get("week_52_low"),
                    "source": "Tradier",
                    "timestamp": datetime.utcnow().isoformat()
                }
        except Exception as e:
            logger.warning("Tradier failed for %s: %s", ticker, e)

    # ── 3. yfinance (unofficial — last resort) ────────────────────────────────
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        hist  = stock.history(period="5d")
        price = hist["Close"].iloc[-1] if not hist.empty else None
        prev  = hist["Close"].iloc[-2] if len(hist) > 1 else price
        change = price - prev if price and prev else None
        change_pct = (change / prev * 100) if prev else None

        return {
            "ticker": ticker,
            "price": round(float(price), 2) if price else None,
            "open": round(float(hist["Open"].iloc[-1]), 2) if not hist.empty else None,
            "high": round(float(hist["High"].iloc[-1]), 2) if not hist.empty else None,
            "low": round(float(hist["Low"].iloc[-1]), 2) if not hist.empty else None,
            "change": round(float(change), 2) if change else None,
            "change_pct": round(float(change_pct), 2) if change_pct else None,
            "volume": info.get("volume"),
            "avg_volume": info.get("averageVolume"),
            "high_52w": info.get("fiftyTwoWeekHigh"),
            "low_52w":  info.get("fiftyTwoWeekLow"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "source": "yfinance (unofficial)",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ============================================================
# SKILL: Get Price History
# ============================================================
@cached(ttl_seconds=300)
def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Returns price history DataFrame.
    """
    ticker = ticker.upper().strip()
    
    if interval == "1d":
        days = 365
        if period == "1mo": days = 30
        elif period == "3mo": days = 90
        elif period == "6mo": days = 180
        elif period == "5d": days = 5
        
        if schwab_available():
            candles = _schwab_price_history(ticker, days=days)
            if candles:
                df = pd.DataFrame(candles)
                if not df.empty:
                    df["Date"] = pd.to_datetime(df["time"])
                    df = df.set_index("Date")
                    df.rename(columns={
                        "open": "Open", "high": "High", "low": "Low",
                        "close": "Close", "volume": "Volume"
                    }, inplace=True)
                    return df
    else:
        # Intraday
        days = 5
        if period == "1d": days = 1
        elif period == "1mo": days = 30
        
        if schwab_available():
            candles = _schwab_intraday_history(ticker, days=days, interval=interval)
            if candles:
                df = pd.DataFrame(candles)
                if not df.empty:
                    df["Date"] = pd.to_datetime(df["time"])
                    df = df.set_index("Date")
                    df.rename(columns={
                        "open": "Open", "high": "High", "low": "Low",
                        "close": "Close", "volume": "Volume"
                    }, inplace=True)
                    return df

    # Fallback to yfinance
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval, prepost=True)
        return df
    except Exception as e:
        logger.warning("yfinance history failed for %s: %s", ticker, e)
        return pd.DataFrame()


# ============================================================
# SKILL: Get Options Chain
# ============================================================
@cached(ttl_seconds=60)
def get_options_chain(ticker: str, expiry: str = None) -> dict:
    """
    Returns options chain for a given ticker.
    expiry format: "YYYY-MM-DD" or None for nearest expiry.

    Priority:
      1. Charles Schwab (production — full greeks, real-time)
      2. Tradier        (real options data, funded account required)
      3. yfinance       (unofficial — last resort)
    """
    ticker = ticker.upper().strip()

    # ── 1. Charles Schwab ─────────────────────────────────────────────────────
    if schwab_available():
        result = _schwab_option_chain(ticker, expiry)
        if result:
            logger.debug("[Schwab] options chain for %s (%s)", ticker, result.get("expiry"))
            return result

    # ── 2. Tradier (requires funded account — real data) ──────────────────────
    if TRADIER_KEY:
        headers = {
            "Authorization": f"Bearer {TRADIER_KEY}",
            "Accept": "application/json"
        }
        try:
            # Get available expirations first
            r = requests.get(
                f"{TRADIER_BASE}/markets/options/expirations",
                params={"symbol": ticker},
                headers=headers,
                timeout=10
            )
            expirations = r.json().get("expirations", {}).get("date", [])
            target_expiry = expiry or (expirations[0] if expirations else None)

            if target_expiry:
                r2 = requests.get(
                    f"{TRADIER_BASE}/markets/options/chains",
                    params={"symbol": ticker, "expiration": target_expiry, "greeks": "true"},
                    headers=headers,
                    timeout=10
                )
                chain_data = r2.json().get("options", {}).get("option", [])

                calls = [o for o in chain_data if o.get("option_type") == "call"]
                puts  = [o for o in chain_data if o.get("option_type") == "put"]

                # Find unusual volume
                all_avg_vol = [o.get("average_volume", 1) or 1 for o in chain_data]
                avg_normal  = sum(all_avg_vol) / len(all_avg_vol) if all_avg_vol else 1

                unusual = [
                    {
                        "type": o.get("option_type"),
                        "strike": o.get("strike"),
                        "expiry": o.get("expiration_date"),
                        "volume": o.get("volume"),
                        "open_interest": o.get("open_interest"),
                        "multiplier": round(o.get("volume", 0) / max(o.get("average_volume", 1), 1), 1),
                        "premium": o.get("last") * o.get("volume", 0) * 100 if o.get("last") else 0,
                        "iv": o.get("greeks", {}).get("iv") if o.get("greeks") else None,
                        "delta": o.get("greeks", {}).get("delta") if o.get("greeks") else None,
                    }
                    for o in chain_data
                    if (o.get("volume") or 0) > 3 * max(o.get("average_volume", 1), 1)
                ]

                return {
                    "ticker": ticker,
                    "expiry": target_expiry,
                    "call_count": len(calls),
                    "put_count": len(puts),
                    "put_call_ratio": round(sum(p.get("volume", 0) for p in puts) /
                                           max(sum(c.get("volume", 0) for c in calls), 1), 2),
                    "unusual_activity": unusual,
                    "all_calls": calls,
                    "all_puts": puts,
                    "source": "Tradier",
                    "timestamp": datetime.utcnow().isoformat()
                }
        except Exception as e:
            logger.warning("Tradier options failed for %s: %s", ticker, e)

    # ── 3. yfinance (unofficial — last resort) ────────────────────────────────
    try:
        stock = yf.Ticker(ticker)
        expirations = stock.options
        target_expiry = expiry if expiry in expirations else (expirations[0] if expirations else None)

        if not target_expiry:
            return {"error": "No options data available", "ticker": ticker}

        chain = stock.option_chain(target_expiry)
        calls = chain.calls
        puts  = chain.puts

        # Find high-volume strikes
        top_calls = calls.nlargest(5, "volume")[["strike","lastPrice","volume","openInterest","impliedVolatility"]].to_dict("records")
        top_puts  = puts.nlargest(5, "volume")[["strike","lastPrice","volume","openInterest","impliedVolatility"]].to_dict("records")

        total_call_vol = calls["volume"].sum()
        total_put_vol  = puts["volume"].sum()

        return {
            "ticker": ticker,
            "expiry": target_expiry,
            "call_count": len(calls),
            "put_count":  len(puts),
            "total_call_volume": int(total_call_vol),
            "total_put_volume":  int(total_put_vol),
            "put_call_ratio": round(total_put_vol / max(total_call_vol, 1), 2),
            "top_call_strikes": top_calls,
            "top_put_strikes":  top_puts,
            "all_calls": calls.to_dict("records"),
            "all_puts": puts.to_dict("records"),
            "source": "yfinance (unofficial)",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ============================================================
# SKILL: Get Market Movers (Top Gainers / Losers / Active)
# ============================================================
@cached(ttl_seconds=60)
def get_market_movers() -> dict:
    """
    Returns today's top market movers and sector performance.

    Priority:
      1. Charles Schwab get_movers() for gainer/loser/active lists
      2. Quotes-based fallback using sector ETFs (yfinance)
    """
    # ── 1. Schwab market movers ───────────────────────────────────────────────
    schwab_movers = None
    if schwab_available():
        schwab_movers = _schwab_movers("$SPX")

    # ── Market index snapshots (batch via Schwab if available) ────────────────
    market_tickers = ["SPY", "QQQ", "IWM", "DIA", "VIX"]
    results = {}

    if schwab_available():
        batch = _schwab_quotes_batch(market_tickers)
        for t in market_tickers:
            q = batch.get(t) or get_stock_quote(t)
            results[t] = {
                "price":      q.get("price"),
                "change_pct": q.get("change_pct")
            }
    else:
        for t in market_tickers:
            q = get_stock_quote(t)
            results[t] = {
                "price":      q.get("price"),
                "change_pct": q.get("change_pct")
            }

    # ── Sector ETFs ───────────────────────────────────────────────────────────
    sector_etfs = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "XLY": "Consumer Disc.",
        "XLI": "Industrials",
        "XLC": "Comm. Services",
        "XLRE": "Real Estate",
        "XLB": "Materials",
        "XLP": "Consumer Staples",
        "XLU": "Utilities"
    }

    sector_data = {}
    if schwab_available():
        batch_sector = _schwab_quotes_batch(list(sector_etfs.keys()))
        for etf, name in sector_etfs.items():
            q = batch_sector.get(etf) or get_stock_quote(etf)
            sector_data[name] = {
                "etf": etf,
                "price":      q.get("price"),
                "change_pct": q.get("change_pct")
            }
    else:
        for etf, name in sector_etfs.items():
            q = get_stock_quote(etf)
            sector_data[name] = {
                "etf": etf,
                "price":      q.get("price"),
                "change_pct": q.get("change_pct")
            }

    # Sort sectors by performance
    sorted_sectors = sorted(
        [(k, v) for k, v in sector_data.items() if v.get("change_pct") is not None],
        key=lambda x: x[1]["change_pct"],
        reverse=True
    )

    data_source = "Charles Schwab (production)" if schwab_available() else "yfinance (unofficial)"

    result = {
        "market_indices":     results,
        "sector_performance": dict(sorted_sectors),
        "top_sector":         sorted_sectors[0][0]  if sorted_sectors else None,
        "worst_sector":       sorted_sectors[-1][0] if sorted_sectors else None,
        "source":             data_source,
        "timestamp":          datetime.utcnow().isoformat()
    }

    # Merge Schwab movers data if available
    if schwab_movers:
        result["gainers"] = schwab_movers.get("gainers", [])
        result["losers"]  = schwab_movers.get("losers",  [])
        result["actives"] = schwab_movers.get("actives", [])

    return result


# ============================================================
# SKILL: Get Technical Analysis
# ============================================================
@cached(ttl_seconds=300)
def get_technical_analysis(ticker: str) -> dict:
    """
    Returns RSI, MACD, Bollinger Bands, and moving averages.

    Price history source priority:
      1. Charles Schwab (production — OHLCV, 365 days)
      2. yfinance       (unofficial fallback)
    """
    ticker = ticker.upper().strip()
    try:
        # ── 1. Try Schwab price history ───────────────────────────────────────
        hist = get_price_history(ticker, period="1y", interval="1d")

        if hist is None or hist.empty:
            return {"error": "No historical data", "ticker": ticker}

        close = hist["Close"]
        volume = hist["Volume"]

        # --- RSI (14-period) ---
        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = (100 - (100 / (1 + rs))).iloc[-1]

        # --- MACD (12, 26, 9) ---
        ema12  = close.ewm(span=12, adjust=False).mean()
        ema26  = close.ewm(span=26, adjust=False).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_val   = macd.iloc[-1]
        signal_val = signal.iloc[-1]
        macd_hist  = macd_val - signal_val

        # --- Bollinger Bands (20, 2) ---
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper_band = sma20 + (2 * std20)
        lower_band = sma20 - (2 * std20)

        current_price = close.iloc[-1]
        bb_width = upper_band.iloc[-1] - lower_band.iloc[-1]
        bb_position = (current_price - lower_band.iloc[-1]) / bb_width if bb_width > 0 else 0.5

        # --- Moving Averages ---
        sma50  = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
        ema20  = close.ewm(span=20).mean().iloc[-1]
        ema9   = close.ewm(span=9).mean().iloc[-1]

        # --- VWAP (Volume Weighted Average Price) ---
        typical_price = (hist["High"] + hist["Low"] + hist["Close"]) / 3
        vwap = (typical_price * volume).cumsum() / volume.cumsum()
        vwap_val = round(float(vwap.iloc[-1]), 2)

        # --- ATR (Average True Range, 14-period) ---
        high_low = hist["High"] - hist["Low"]
        high_close = abs(hist["High"] - hist["Close"].shift())
        low_close = abs(hist["Low"] - hist["Close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]

        # --- Volume analysis ---
        avg_vol_20 = volume.rolling(20).mean().iloc[-1]
        current_vol = volume.iloc[-1]
        vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1

        # --- Interpretation ---
        signals = []
        if rsi < 30:
            signals.append("RSI OVERSOLD → Potential reversal / buying opportunity")
        elif rsi > 70:
            signals.append("RSI OVERBOUGHT → Potential pullback / selling pressure")
        elif rsi < 40:
            signals.append("RSI approaching oversold territory — monitor closely")
        elif rsi > 60:
            signals.append("RSI elevated — momentum is bullish but watch for exhaustion")

        if macd_val > signal_val and macd_hist > 0:
            signals.append("MACD BULLISH CROSSOVER → Upward momentum building")
        elif macd_val < signal_val and macd_hist < 0:
            signals.append("MACD BEARISH CROSSOVER → Downward momentum")

        if sma200 is not None:
            if current_price > sma50 > sma200:
                signals.append("GOLDEN CROSS alignment → Long-term bullish trend")
            elif current_price < sma50 < sma200:
                signals.append("DEATH CROSS alignment → Long-term bearish trend")

        if bb_position < 0.2:
            signals.append("NEAR LOWER BOLLINGER BAND → Oversold territory")
        elif bb_position > 0.8:
            signals.append("NEAR UPPER BOLLINGER BAND → Overbought territory")

        if vol_ratio > 2.0:
            signals.append(f"VOLUME SURGE → {vol_ratio:.1f}x average — significant institutional activity")
        elif vol_ratio > 1.5:
            signals.append(f"ABOVE AVERAGE VOLUME → {vol_ratio:.1f}x average")

        if current_price > vwap_val:
            signals.append("ABOVE VWAP → Institutional buyers in control")
        else:
            signals.append("BELOW VWAP → Institutional sellers in control")

        # --- Support / Resistance levels ---
        recent_high = float(hist["High"].tail(20).max())
        recent_low = float(hist["Low"].tail(20).min())

        # Price history for charting (last 90 days)
        chart_data = []
        chart_hist = hist.tail(90)
        for idx, row in chart_hist.iterrows():
            chart_data.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"])
            })

        return {
            "ticker": ticker,
            "current_price": round(float(current_price), 2),
            "rsi_14": round(float(rsi), 2),
            "macd": round(float(macd_val), 4),
            "macd_signal": round(float(signal_val), 4),
            "macd_histogram": round(float(macd_hist), 4),
            "upper_bb": round(float(upper_band.iloc[-1]), 2),
            "lower_bb": round(float(lower_band.iloc[-1]), 2),
            "bb_middle": round(float(sma20.iloc[-1]), 2),
            "ema_9":  round(float(ema9), 2),
            "sma_20":  round(float(ema20), 2),
            "sma_50":  round(float(sma50), 2) if not pd.isna(sma50) else None,
            "sma_200": round(float(sma200), 2) if sma200 is not None and not pd.isna(sma200) else None,
            "vwap": vwap_val,
            "atr_14": round(float(atr), 2),
            "bb_position_pct": round(float(bb_position * 100), 1),
            "volume_ratio": round(float(vol_ratio), 2),
            "support": round(recent_low, 2),
            "resistance": round(recent_high, 2),
            "signals": signals,
            "chart_data": chart_data,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ============================================================
# SKILL: Get Portfolio (reads from local JSON)
# ============================================================
def get_portfolio() -> dict:
    """
    Reads the user's portfolio from data/portfolio.json and
    enriches it with current prices.
    """
    portfolio_path = os.path.join(BASE_DIR, "data", "portfolio.json")
    try:
        with open(portfolio_path, "r") as f:
            portfolio = json.load(f)

        holdings = portfolio.get("holdings", [])

        # Skip example note entry
        holdings = [h for h in holdings if "note" not in h]

        enriched = []
        total_value   = 0
        total_cost    = 0
        sector_values = {}

        for h in holdings:
            ticker = h.get("ticker", "")
            shares = h.get("shares", 0)
            avg_cost = h.get("avg_cost", 0)
            sector = h.get("sector", "Other")

            q = get_stock_quote(ticker)
            current_price = q.get("price") or 0
            current_value = shares * current_price
            cost_basis    = shares * avg_cost
            gain_loss     = current_value - cost_basis
            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0

            total_value += current_value
            total_cost  += cost_basis

            # Track sector allocation
            sector_values[sector] = sector_values.get(sector, 0) + current_value

            enriched.append({
                **h,
                "current_price": round(current_price, 2),
                "current_value": round(current_value, 2),
                "cost_basis":    round(cost_basis, 2),
                "gain_loss":     round(gain_loss, 2),
                "gain_loss_pct": round(gain_loss_pct, 2),
                "change_today":  q.get("change_pct"),
                "weight_pct":    0  # calculated below
            })

        # Calculate portfolio weights
        for h in enriched:
            h["weight_pct"] = round(h["current_value"] / total_value * 100, 1) if total_value > 0 else 0

        # Sector allocation percentages
        sector_allocation = {}
        for sector, value in sector_values.items():
            sector_allocation[sector] = round(value / total_value * 100, 1) if total_value > 0 else 0

        total_gain_loss = total_value - total_cost
        total_return_pct = (total_gain_loss / total_cost * 100) if total_cost else 0

        # Concentration alerts
        alerts = []
        for h in enriched:
            if h["weight_pct"] > 10:
                alerts.append(f"⚠️ {h['ticker']} is {h['weight_pct']}% of portfolio — exceeds 10% concentration limit")
        for sector, pct in sector_allocation.items():
            if pct > 15:
                alerts.append(f"⚠️ {sector} sector at {pct}% — exceeds 15% concentration alert threshold")

        return {
            "holdings": enriched,
            "summary": {
                "total_value":      round(total_value, 2),
                "total_cost":       round(total_cost, 2),
                "total_gain_loss":  round(total_gain_loss, 2),
                "total_return_pct": round(total_return_pct, 2),
                "position_count":   len(enriched),
                "cash": portfolio.get("cash", 0)
            },
            "sector_allocation": sector_allocation,
            "concentration_alerts": alerts,
            "risk_profile": portfolio.get("risk_profile"),
            "watchlist": portfolio.get("watchlist", []),
            "sector_targets": portfolio.get("sector_targets", {}),
            "timestamp": datetime.utcnow().isoformat()
        }
    except FileNotFoundError:
        return {"error": "Portfolio file not found. Add holdings to data/portfolio.json"}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# SKILL: Add/Update Portfolio Holding
# ============================================================
def add_portfolio_holding(ticker: str, shares: float, avg_cost: float,
                          sector: str = "Other", horizon: str = "long-term",
                          notes: str = "") -> dict:
    """
    Adds or updates a holding in the portfolio JSON file.
    """
    portfolio_path = os.path.join(BASE_DIR, "data", "portfolio.json")
    try:
        with open(portfolio_path, "r") as f:
            portfolio = json.load(f)

        holdings = portfolio.get("holdings", [])
        ticker = ticker.upper().strip()

        # Check if ticker already exists
        existing = None
        for i, h in enumerate(holdings):
            if h.get("ticker", "").upper() == ticker and "note" not in h:
                existing = i
                break

        new_holding = {
            "ticker": ticker,
            "shares": shares,
            "avg_cost": avg_cost,
            "date_added": datetime.now().strftime("%Y-%m-%d"),
            "horizon": horizon,
            "sector": sector,
            "notes": notes
        }

        if existing is not None:
            holdings[existing] = new_holding
            action = "updated"
        else:
            holdings.append(new_holding)
            action = "added"

        portfolio["holdings"] = holdings
        portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        with open(portfolio_path, "w") as f:
            json.dump(portfolio, f, indent=2)

        return {"status": "success", "action": action, "holding": new_holding}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# SKILL: Get News for a Ticker
# ============================================================
@cached(ttl_seconds=600)
def get_news(ticker: str = None, query: str = None, limit: int = 10) -> dict:
    """
    Fetches latest news for a ticker or general market.
    Uses NewsAPI if key is available, else yfinance news.
    """
    if NEWS_API_KEY:
        try:
            q = ticker or query or "stock market"
            r = requests.get(
                f"{NEWS_BASE}/everything",
                params={
                    "q": q,
                    "sortBy": "publishedAt",
                    "pageSize": limit,
                    "language": "en",
                    "apiKey": NEWS_API_KEY
                },
                timeout=10
            )
            data = r.json()
            articles = data.get("articles", [])
            return {
                "query": q,
                "articles": [
                    {
                        "title":       a.get("title"),
                        "source":      a.get("source", {}).get("name"),
                        "published":   a.get("publishedAt"),
                        "url":         a.get("url"),
                        "description": a.get("description")
                    }
                    for a in articles
                ],
                "source": "NewsAPI",
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.warning("NewsAPI failed: %s", e)

    # Fallback: yfinance news
    if ticker:
        try:
            stock = yf.Ticker(ticker.upper())
            news  = stock.news[:limit]
            return {
                "query": ticker,
                "articles": [
                    {
                        "title":     n.get("title"),
                        "publisher": n.get("publisher"),
                        "link":      n.get("link"),
                        "published": datetime.fromtimestamp(n.get("providerPublishTime", 0)).isoformat()
                            if n.get("providerPublishTime") else None
                    }
                    for n in news
                ],
                "source": "yfinance (unofficial)",
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}

    return {"error": "No news source configured. Set NEWS_API_KEY in .env"}


# ============================================================
# SKILL: Get Earnings Calendar
# ============================================================
@cached(ttl_seconds=3600)
def get_earnings_calendar(tickers: list = None) -> dict:
    """
    Returns upcoming earnings dates for given tickers.
    """
    tickers = tickers or ["AAPL", "NVDA", "MSFT", "AMZN", "TSLA", "META", "GOOGL"]
    results = []

    for t in tickers:
        try:
            stock = yf.Ticker(t)
            cal   = stock.calendar
            if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                if isinstance(cal, dict):
                    results.append({
                        "ticker": t,
                        "earnings_date": str(cal.get("Earnings Date", ["Unknown"])[0]) if cal.get("Earnings Date") else "Unknown",
                        "eps_estimate": cal.get("EPS Estimate"),
                        "revenue_estimate": cal.get("Revenue Estimate"),
                    })
                elif hasattr(cal, 'columns') and len(cal.columns) > 0:
                    results.append({
                        "ticker": t,
                        "earnings_date": str(cal.columns[0].date()),
                        "eps_estimate": cal.get("Earnings Average", {}).get(cal.columns[0]) if "Earnings Average" in cal.index else None,
                    })
        except Exception:
            pass

    return {
        "earnings": results,
        "source": "yfinance (unofficial)",
        "timestamp": datetime.utcnow().isoformat()
    }


# ============================================================
# SKILL: Get Fundamentals (NEW)
# ============================================================
@cached(ttl_seconds=3600)
def get_fundamentals(ticker: str) -> dict:
    """
    Returns fundamental analysis data: valuation, profitability,
    growth metrics, and financial health indicators.
    """
    ticker = ticker.upper().strip()
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Valuation metrics
        market_cap = info.get("marketCap")
        pe_trailing = info.get("trailingPE")
        pe_forward = info.get("forwardPE")
        peg_ratio = info.get("pegRatio")
        pb_ratio = info.get("priceToBook")
        ps_ratio = info.get("priceToSalesTrailing12Months")
        ev_ebitda = info.get("enterpriseToEbitda")
        ev_revenue = info.get("enterpriseToRevenue")

        # Profitability
        profit_margin = info.get("profitMargins")
        operating_margin = info.get("operatingMargins")
        gross_margin = info.get("grossMargins")
        roe = info.get("returnOnEquity")
        roa = info.get("returnOnAssets")

        # Growth
        revenue_growth = info.get("revenueGrowth")
        earnings_growth = info.get("earningsGrowth")
        earnings_quarterly_growth = info.get("earningsQuarterlyGrowth")

        # Financial health
        total_debt = info.get("totalDebt")
        total_cash = info.get("totalCash")
        current_ratio = info.get("currentRatio")
        debt_to_equity = info.get("debtToEquity")
        free_cashflow = info.get("freeCashflow")
        operating_cashflow = info.get("operatingCashflow")

        # Per-share data
        eps_trailing = info.get("trailingEps")
        eps_forward = info.get("forwardEps")
        book_value = info.get("bookValue")
        revenue_per_share = info.get("revenuePerShare")

        # Dividend
        dividend_yield = info.get("dividendYield")
        dividend_rate = info.get("dividendRate")
        payout_ratio = info.get("payoutRatio")
        ex_dividend_date = info.get("exDividendDate")

        # Analyst consensus
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        target_mean = info.get("targetMeanPrice")
        target_median = info.get("targetMedianPrice")
        recommendation = info.get("recommendationKey")
        num_analysts = info.get("numberOfAnalystOpinions")

        # Valuation assessment
        signals = []
        if pe_forward and pe_trailing:
            if pe_forward < pe_trailing:
                signals.append("Forward P/E < Trailing P/E → Earnings growth expected")
            elif pe_forward > pe_trailing * 1.2:
                signals.append("Forward P/E > Trailing P/E → Earnings decline expected")

        if peg_ratio:
            if peg_ratio < 1:
                signals.append(f"PEG ratio {peg_ratio:.2f} < 1 → Undervalued relative to growth")
            elif peg_ratio > 2:
                signals.append(f"PEG ratio {peg_ratio:.2f} > 2 → Potentially overvalued")

        if debt_to_equity:
            if debt_to_equity > 200:
                signals.append(f"⚠️ High debt-to-equity ({debt_to_equity:.0f}%) — elevated financial risk")
            elif debt_to_equity < 50:
                signals.append(f"Low debt-to-equity ({debt_to_equity:.0f}%) — conservative balance sheet")

        if revenue_growth:
            if revenue_growth > 0.2:
                signals.append(f"Strong revenue growth: {revenue_growth*100:.1f}% YoY")
            elif revenue_growth < 0:
                signals.append(f"⚠️ Revenue declining: {revenue_growth*100:.1f}% YoY")

        if free_cashflow:
            if free_cashflow > 0:
                signals.append("Positive free cash flow — self-funding growth")
            else:
                signals.append("⚠️ Negative free cash flow — burning cash")

        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        if target_mean and current_price:
            upside = (target_mean - current_price) / current_price * 100
            signals.append(f"Analyst consensus target ${target_mean:.2f} → {upside:+.1f}% upside")

        def safe_pct(val):
            return round(val * 100, 2) if val is not None else None

        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": market_cap,
            "market_cap_fmt": _format_large_number(market_cap) if market_cap else None,
            "valuation": {
                "pe_trailing": round(pe_trailing, 2) if pe_trailing else None,
                "pe_forward": round(pe_forward, 2) if pe_forward else None,
                "peg_ratio": round(peg_ratio, 2) if peg_ratio else None,
                "pb_ratio": round(pb_ratio, 2) if pb_ratio else None,
                "ps_ratio": round(ps_ratio, 2) if ps_ratio else None,
                "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda else None,
                "ev_revenue": round(ev_revenue, 2) if ev_revenue else None,
            },
            "profitability": {
                "gross_margin_pct": safe_pct(gross_margin),
                "operating_margin_pct": safe_pct(operating_margin),
                "profit_margin_pct": safe_pct(profit_margin),
                "roe_pct": safe_pct(roe),
                "roa_pct": safe_pct(roa),
            },
            "growth": {
                "revenue_growth_pct": safe_pct(revenue_growth),
                "earnings_growth_pct": safe_pct(earnings_growth),
                "earnings_quarterly_growth_pct": safe_pct(earnings_quarterly_growth),
            },
            "financial_health": {
                "total_debt": total_debt,
                "total_cash": total_cash,
                "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity else None,
                "current_ratio": round(current_ratio, 2) if current_ratio else None,
                "free_cashflow": free_cashflow,
                "free_cashflow_fmt": _format_large_number(free_cashflow) if free_cashflow else None,
                "operating_cashflow": operating_cashflow,
            },
            "per_share": {
                "eps_trailing": eps_trailing,
                "eps_forward": eps_forward,
                "book_value": book_value,
                "revenue_per_share": revenue_per_share,
            },
            "dividend": {
                "yield_pct": safe_pct(dividend_yield),
                "annual_rate": dividend_rate,
                "payout_ratio_pct": safe_pct(payout_ratio),
            },
            "analyst_consensus": {
                "recommendation": recommendation,
                "target_high": target_high,
                "target_low": target_low,
                "target_mean": target_mean,
                "target_median": target_median,
                "num_analysts": num_analysts,
            },
            "signals": signals,
            "source": "yfinance (unofficial)",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ============================================================
# SKILL: Get Insider Activity (NEW)
# ============================================================
@cached(ttl_seconds=3600)
def get_insider_activity(ticker: str) -> dict:
    """
    Returns insider buying/selling activity for a given ticker.
    Insider buying is one of the strongest bullish signals.
    """
    ticker = ticker.upper().strip()
    try:
        stock = yf.Ticker(ticker)

        # Insider transactions
        insider_txns = stock.insider_transactions
        transactions = []
        buy_count = 0
        sell_count = 0
        buy_value = 0
        sell_value = 0

        if insider_txns is not None and not insider_txns.empty:
            for _, row in insider_txns.head(20).iterrows():
                txn_type = str(row.get("Text", "")).lower()
                shares = row.get("Shares", 0) or 0
                value = row.get("Value", 0) or 0

                is_buy = "purchase" in txn_type or "buy" in txn_type
                is_sell = "sale" in txn_type or "sell" in txn_type

                if is_buy:
                    buy_count += 1
                    buy_value += value
                elif is_sell:
                    sell_count += 1
                    sell_value += value

                transactions.append({
                    "insider": row.get("Insider", "Unknown"),
                    "relation": row.get("Position", ""),
                    "transaction": row.get("Text", ""),
                    "date": str(row.get("Start Date", "")),
                    "shares": int(shares) if shares else 0,
                    "value": round(float(value), 2) if value else 0,
                })

        # Insider holders summary
        holders = []
        insider_holders = stock.insider_purchases
        if insider_holders is not None and not insider_holders.empty:
            for _, row in insider_holders.iterrows():
                holders.append({
                    "period": str(row.get("Insider Purchases Last 6m", row.name)) if hasattr(row, 'name') else "",
                    "purchases": row.get("Purchases", 0),
                    "sales": row.get("Sales", 0),
                    "net": row.get("Net Shares Purchased (Sold)", 0),
                })

        # Interpretation
        signals = []
        if buy_count > sell_count:
            signals.append(f"NET INSIDER BUYING — {buy_count} buys vs {sell_count} sales → Bullish signal")
        elif sell_count > buy_count * 2:
            signals.append(f"HEAVY INSIDER SELLING — {sell_count} sales vs {buy_count} buys → Bearish signal")
        elif sell_count > buy_count:
            signals.append(f"Net insider selling — {sell_count} sales vs {buy_count} buys → Monitor closely")

        if buy_value > 1_000_000:
            signals.append(f"Large insider purchases totaling ${buy_value:,.0f} → High conviction buying")

        return {
            "ticker": ticker,
            "transactions": transactions,
            "summary": {
                "buy_count": buy_count,
                "sell_count": sell_count,
                "buy_value": round(buy_value, 2),
                "sell_value": round(sell_value, 2),
                "net_activity": "buying" if buy_count > sell_count else "selling" if sell_count > buy_count else "neutral",
            },
            "signals": signals,
            "source": "yfinance (unofficial)",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ============================================================
# SKILL: Get Fear & Greed Index (NEW)
# ============================================================
@cached(ttl_seconds=600)
def get_fear_greed_index() -> dict:
    """
    Calculates a market Fear & Greed composite indicator using
    VIX level, put/call ratio proxies, market momentum, and breadth.
    """
    try:
        # VIX-based fear gauge
        vix = get_stock_quote("^VIX")
        vix_price = vix.get("price") or 20

        # Market momentum (SPY distance from 50-day MA)
        spy_ta = get_technical_analysis("SPY")
        spy_price = spy_ta.get("current_price", 0)
        spy_sma50 = spy_ta.get("sma_50", spy_price)
        spy_rsi = spy_ta.get("rsi_14", 50)

        # Calculate composite score (0 = Extreme Fear, 100 = Extreme Greed)
        scores = {}

        # VIX component (inverted — low VIX = greed, high VIX = fear)
        if vix_price < 12:
            scores["vix"] = 95
        elif vix_price < 15:
            scores["vix"] = 80
        elif vix_price < 20:
            scores["vix"] = 60
        elif vix_price < 25:
            scores["vix"] = 40
        elif vix_price < 30:
            scores["vix"] = 25
        elif vix_price < 35:
            scores["vix"] = 10
        else:
            scores["vix"] = 5

        # Momentum component (SPY vs 50-day SMA)
        if spy_sma50 and spy_sma50 > 0:
            momentum_pct = (spy_price - spy_sma50) / spy_sma50 * 100
            scores["momentum"] = min(100, max(0, 50 + momentum_pct * 10))
        else:
            scores["momentum"] = 50

        # RSI component
        scores["rsi"] = min(100, max(0, spy_rsi))

        # Market breadth proxy (using sector ETF performance)
        sector_etfs = ["XLK", "XLF", "XLV", "XLE", "XLY", "XLI", "XLC", "XLB", "XLP", "XLU"]
        up_sectors = 0
        for etf in sector_etfs:
            q = get_stock_quote(etf)
            if q.get("change_pct") and q["change_pct"] > 0:
                up_sectors += 1
        scores["breadth"] = up_sectors * 10  # 0-100 scale

        # Composite (weighted average)
        composite = int(
            scores["vix"] * 0.30 +
            scores["momentum"] * 0.25 +
            scores["rsi"] * 0.25 +
            scores["breadth"] * 0.20
        )

        # Classification
        if composite >= 80:
            classification = "Extreme Greed"
        elif composite >= 60:
            classification = "Greed"
        elif composite >= 45:
            classification = "Neutral"
        elif composite >= 25:
            classification = "Fear"
        else:
            classification = "Extreme Fear"

        signals = []
        if composite >= 80:
            signals.append("⚠️ EXTREME GREED — Markets may be overextended. Consider taking profits.")
        elif composite <= 20:
            signals.append("🟢 EXTREME FEAR — Historically the best buying opportunities occur here.")
        elif composite >= 60:
            signals.append("Market sentiment is greedy — be cautious with new positions")
        elif composite <= 35:
            signals.append("Market sentiment is fearful — contrarian buying opportunity may exist")

        return {
            "composite_score": composite,
            "classification": classification,
            "components": {
                "vix": {"score": scores["vix"], "value": vix_price, "weight": "30%"},
                "momentum": {"score": scores["momentum"], "value": round(spy_price - (spy_sma50 or spy_price), 2), "weight": "25%"},
                "rsi": {"score": scores["rsi"], "value": spy_rsi, "weight": "25%"},
                "breadth": {"score": scores["breadth"], "value": f"{up_sectors}/{len(sector_etfs)} sectors up", "weight": "20%"},
            },
            "signals": signals,
            "source": "Calculated (VIX + SPY momentum + RSI + sector breadth)",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# SKILL: Get Economic Indicators (NEW)
# ============================================================
@cached(ttl_seconds=600)
def get_economic_indicators() -> dict:
    """
    Returns key economic and macro indicators: treasury yields,
    dollar index, commodities, and cross-asset signals.
    """
    try:
        indicators = {}

        # Treasury yields and interest rates
        bond_tickers = {
            "^TNX": {"name": "10-Year Treasury Yield", "type": "yield"},
            "^FVX": {"name": "5-Year Treasury Yield", "type": "yield"},
            "^TYX": {"name": "30-Year Treasury Yield", "type": "yield"},
            "^IRX": {"name": "3-Month T-Bill", "type": "yield"},
        }

        yields = {}
        for ticker, meta in bond_tickers.items():
            q = get_stock_quote(ticker)
            if q.get("price"):
                yields[meta["name"]] = {
                    "value": q["price"],
                    "change": q.get("change"),
                    "change_pct": q.get("change_pct"),
                }

        # Calculate yield curve (10Y - 2Y proxy using 10Y - 3M)
        ten_year = yields.get("10-Year Treasury Yield", {}).get("value")
        three_month = yields.get("3-Month T-Bill", {}).get("value")
        yield_spread = None
        if ten_year and three_month:
            yield_spread = round(ten_year - three_month, 2)

        indicators["treasury_yields"] = yields
        indicators["yield_curve_spread"] = yield_spread

        # Commodities
        commodity_tickers = {
            "GC=F":  "Gold",
            "CL=F":  "Crude Oil (WTI)",
            "SI=F":  "Silver",
            "HG=F":  "Copper",
            "NG=F":  "Natural Gas",
        }

        commodities = {}
        for ticker, name in commodity_tickers.items():
            q = get_stock_quote(ticker)
            if q.get("price"):
                commodities[name] = {
                    "price": q["price"],
                    "change_pct": q.get("change_pct"),
                }
        indicators["commodities"] = commodities

        # Currency (Dollar Index proxy via UUP ETF)
        dxy = get_stock_quote("UUP")
        indicators["dollar_index"] = {
            "price": dxy.get("price"),
            "change_pct": dxy.get("change_pct"),
            "note": "UUP ETF as DXY proxy"
        }

        # Crypto sentiment proxy
        btc = get_stock_quote("BTC-USD")
        indicators["bitcoin"] = {
            "price": btc.get("price"),
            "change_pct": btc.get("change_pct"),
        }

        # Signals / Interpretation
        signals = []
        if yield_spread is not None:
            if yield_spread < 0:
                signals.append(f"⚠️ INVERTED YIELD CURVE (spread: {yield_spread}bp) — Recession warning signal")
            elif yield_spread < 0.5:
                signals.append(f"Yield curve flattening ({yield_spread}bp) — Economic slowdown concern")
            else:
                signals.append(f"Normal yield curve ({yield_spread}bp) — Healthy economic signal")

        gold = commodities.get("Gold", {})
        if gold.get("change_pct") and gold["change_pct"] > 1:
            signals.append("Gold surging — Flight to safety / inflation hedge demand")

        oil = commodities.get("Crude Oil (WTI)", {})
        if oil.get("change_pct") and oil["change_pct"] > 3:
            signals.append("Oil spiking — Energy inflation risk / geopolitical tension")
        elif oil.get("change_pct") and oil["change_pct"] < -3:
            signals.append("Oil dropping sharply — Demand destruction / recession signal")

        copper = commodities.get("Copper", {})
        if copper.get("change_pct") and copper["change_pct"] > 2:
            signals.append("Copper rising — Dr. Copper signals economic expansion")
        elif copper.get("change_pct") and copper["change_pct"] < -2:
            signals.append("Copper falling — Dr. Copper signals economic contraction")

        indicators["signals"] = signals
        indicators["timestamp"] = datetime.utcnow().isoformat()
        indicators["source"] = "yfinance (unofficial)"

        return indicators
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# SKILL: Get Earnings Analysis (NEW)
# ============================================================
@cached(ttl_seconds=3600)
def get_earnings_analysis(ticker: str) -> dict:
    """
    Returns historical earnings beats/misses and revenue performance.
    """
    ticker = ticker.upper().strip()
    try:
        stock = yf.Ticker(ticker)

        # Earnings history
        earnings_hist = stock.earnings_history
        history = []
        beats = 0
        misses = 0

        if earnings_hist is not None and not earnings_hist.empty:
            for _, row in earnings_hist.iterrows():
                actual = row.get("epsActual")
                estimate = row.get("epsEstimate")
                surprise = row.get("epsDifference")
                surprise_pct = row.get("surprisePercent")

                if actual is not None and estimate is not None:
                    beat = actual > estimate
                    if beat:
                        beats += 1
                    else:
                        misses += 1

                history.append({
                    "quarter": str(row.get("quarter", "")),
                    "eps_actual": round(float(actual), 2) if actual else None,
                    "eps_estimate": round(float(estimate), 2) if estimate else None,
                    "surprise": round(float(surprise), 2) if surprise else None,
                    "surprise_pct": round(float(surprise_pct) * 100, 1) if surprise_pct else None,
                    "beat": beat if actual is not None and estimate is not None else None,
                })

        # Revenue data
        financials = stock.quarterly_financials
        revenue_history = []
        if financials is not None and not financials.empty:
            if "Total Revenue" in financials.index:
                for col in financials.columns[:8]:
                    rev = financials.loc["Total Revenue", col]
                    revenue_history.append({
                        "quarter": col.strftime("%Y-Q%q") if hasattr(col, 'strftime') else str(col),
                        "revenue": float(rev) if rev else None,
                        "revenue_fmt": _format_large_number(rev) if rev else None,
                    })

        total = beats + misses
        beat_rate = round(beats / total * 100, 1) if total > 0 else None

        signals = []
        if beat_rate is not None:
            if beat_rate >= 75:
                signals.append(f"Strong earnings track record — {beat_rate}% beat rate ({beats}/{total} quarters)")
            elif beat_rate < 50:
                signals.append(f"⚠️ Weak earnings execution — only {beat_rate}% beat rate")

        return {
            "ticker": ticker,
            "earnings_history": history,
            "revenue_history": revenue_history,
            "summary": {
                "total_quarters": total,
                "beats": beats,
                "misses": misses,
                "beat_rate_pct": beat_rate,
            },
            "signals": signals,
            "source": "yfinance (unofficial)",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ============================================================
# SKILL: Get Sector Rotation Analysis (NEW)
# ============================================================
@cached(ttl_seconds=300)
def get_sector_rotation() -> dict:
    """
    Analyzes money flow between sectors to detect rotation patterns.
    Compares 1-week vs 1-month vs 3-month sector performance.
    """
    sectors = {
        "XLK":  "Technology",
        "XLF":  "Financials",
        "XLE":  "Energy",
        "XLV":  "Healthcare",
        "XLY":  "Consumer Discretionary",
        "XLI":  "Industrials",
        "XLC":  "Communication Services",
        "XLRE": "Real Estate",
        "XLB":  "Materials",
        "XLP":  "Consumer Staples",
        "XLU":  "Utilities",
    }

    results = []

    # Fetch SPY once (instead of inside the loop)
    spy = yf.Ticker("SPY")
    spy_hist = spy.history(period="6mo")
    spy_current = float(spy_hist["Close"].iloc[-1]) if not spy_hist.empty else 1

    for etf, name in sectors.items():
        try:
            stock = yf.Ticker(etf)
            hist = stock.history(period="6mo")

            if hist.empty:
                continue

            close = hist["Close"]
            current = float(close.iloc[-1])

            # Performance over different timeframes
            perf_1w = None
            perf_1m = None
            perf_3m = None

            if len(close) >= 5:
                perf_1w = round((current / float(close.iloc[-5]) - 1) * 100, 2)
            if len(close) >= 22:
                perf_1m = round((current / float(close.iloc[-22]) - 1) * 100, 2)
            if len(close) >= 63:
                perf_3m = round((current / float(close.iloc[-63]) - 1) * 100, 2)

            # Relative strength (vs SPY)
            relative_1m = None
            if len(close) >= 22 and len(spy_hist) >= 22:
                sector_perf = current / float(close.iloc[-22])
                spy_perf = spy_current / float(spy_hist["Close"].iloc[-22])
                relative_1m = round((sector_perf / spy_perf - 1) * 100, 2)

            # Momentum classification
            momentum = "neutral"
            if perf_1w and perf_1m:
                if perf_1w > 0 and perf_1m > 0 and (perf_1w > perf_1m / 4):
                    momentum = "accelerating"
                elif perf_1w > 0 and perf_1m < 0:
                    momentum = "recovering"
                elif perf_1w < 0 and perf_1m > 0:
                    momentum = "decelerating"
                elif perf_1w < 0 and perf_1m < 0:
                    momentum = "declining"

            results.append({
                "etf": etf,
                "sector": name,
                "price": round(current, 2),
                "perf_1w_pct": perf_1w,
                "perf_1m_pct": perf_1m,
                "perf_3m_pct": perf_3m,
                "relative_strength_1m": relative_1m,
                "momentum": momentum,
            })
        except Exception:
            continue

    # Sort by 1-month performance
    results.sort(key=lambda x: x.get("perf_1m_pct") or -999, reverse=True)

    # Detect rotation patterns
    signals = []
    if results:
        top_sector = results[0]
        worst_sector = results[-1]
        signals.append(f"Leading sector: {top_sector['sector']} ({top_sector['perf_1m_pct']:+.1f}% 1M)")
        signals.append(f"Lagging sector: {worst_sector['sector']} ({worst_sector['perf_1m_pct']:+.1f}% 1M)")

        # Check for defensive rotation
        defensive = ["Consumer Staples", "Utilities", "Healthcare"]
        cyclical = ["Technology", "Consumer Discretionary", "Industrials"]

        def_perf = np.mean([r["perf_1m_pct"] for r in results if r["sector"] in defensive and r.get("perf_1m_pct") is not None])
        cyc_perf = np.mean([r["perf_1m_pct"] for r in results if r["sector"] in cyclical and r.get("perf_1m_pct") is not None])

        if not np.isnan(def_perf) and not np.isnan(cyc_perf):
            if def_perf > cyc_perf + 2:
                signals.append("⚠️ DEFENSIVE ROTATION — Money flowing to safety (Staples, Utilities, Healthcare outperforming)")
            elif cyc_perf > def_perf + 2:
                signals.append("🟢 RISK-ON ROTATION — Money flowing to growth (Tech, Discretionary, Industrials leading)")

    return {
        "sectors": results,
        "signals": signals,
        "source": "yfinance (unofficial)",
        "timestamp": datetime.utcnow().isoformat()
    }


# ============================================================
# HELPER: Format large numbers
# ============================================================
def _format_large_number(num):
    """Format a large number to human-readable string."""
    if num is None:
        return None
    num = float(num)
    if abs(num) >= 1_000_000_000_000:
        return f"${num/1_000_000_000_000:.2f}T"
    elif abs(num) >= 1_000_000_000:
        return f"${num/1_000_000_000:.2f}B"
    elif abs(num) >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    elif abs(num) >= 1_000:
        return f"${num/1_000:.1f}K"
    else:
        return f"${num:.2f}"


# ============================================================
# CLI TEST — Run skills directly to verify setup
# ============================================================
if __name__ == "__main__":
    print("\n=== FinClaw Skills Test ===\n")

    print("📈 Testing Stock Quote (AAPL)...")
    q = get_stock_quote("AAPL")
    print(json.dumps(q, indent=2, default=str))

    print("\n📊 Testing Technical Analysis (NVDA)...")
    ta_result = get_technical_analysis("NVDA")
    # Don't print chart_data in CLI (too long)
    ta_display = {k: v for k, v in ta_result.items() if k != "chart_data"}
    print(json.dumps(ta_display, indent=2, default=str))

    print("\n🏢 Testing Fundamentals (AAPL)...")
    fund = get_fundamentals("AAPL")
    print(json.dumps(fund, indent=2, default=str))

    print("\n👤 Testing Insider Activity (NVDA)...")
    insider = get_insider_activity("NVDA")
    print(json.dumps(insider, indent=2, default=str))

    print("\n😱 Testing Fear & Greed Index...")
    fg = get_fear_greed_index()
    print(json.dumps(fg, indent=2, default=str))

    print("\n🌎 Testing Market Movers...")
    mm = get_market_movers()
    print(json.dumps(mm, indent=2, default=str))

    print("\n🔄 Testing Sector Rotation...")
    sr = get_sector_rotation()
    print(json.dumps(sr, indent=2, default=str))

    print("\n🏛️ Testing Economic Indicators...")
    econ = get_economic_indicators()
    print(json.dumps(econ, indent=2, default=str))

    print("\n💰 Testing Earnings Analysis (AAPL)...")
    ea = get_earnings_analysis("AAPL")
    print(json.dumps(ea, indent=2, default=str))

    print("\n📰 Testing News (SPY)...")
    n = get_news("SPY")
    print(json.dumps(n, indent=2, default=str))

    print("\n📋 Testing Portfolio...")
    p = get_portfolio()
    print(json.dumps(p, indent=2, default=str))

    print(f"\n📦 Cache stats: {get_cache_stats()}")

    print("\n✅ Skills test complete!")
