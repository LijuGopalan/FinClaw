"""
schwab_client.py — Charles Schwab Market Data API Integration
=============================================================
Wraps the official schwab-py library (https://github.com/alexgolec/schwab-py)
for real-time, production-grade market data.

Key features
------------
* OAuth2 token management with automatic refresh (7-day token lifetime)
* Lazy initialization — client is created on first use, not on import
* Thread-safe singleton so all skills share one authenticated session
* Graceful fallback flag — callers check `schwab_available()` before use
* Zero-dependency fallback — nothing breaks if schwab-py is not installed

Authentication flow
-------------------
Schwab uses a 3-legged OAuth2 flow.  The *first* time you run this you must
complete a browser login:

    python -c "from skills.schwab_client import force_reauth; force_reauth()"

After that, a token file is stored at `data/schwab_token.json` and refreshed
automatically on every call.

Environment variables (set in .env)
------------------------------------
    SCHWAB_API_KEY        Client ID  (App Key in Schwab dev portal)
    SCHWAB_APP_SECRET     Client Secret
    SCHWAB_CALLBACK_URL   Must match exactly what is registered on the portal
                          (default: https://127.0.0.1)
    SCHWAB_TOKEN_PATH     Where to store/read the OAuth token
                          (default: <project_root>/data/schwab_token.json)
"""

import os
import logging
import threading
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("finclaw.schwab")

# ── credentials ──────────────────────────────────────────────────────────────
SCHWAB_API_KEY      = os.getenv("SCHWAB_API_KEY", "")
SCHWAB_APP_SECRET   = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_CALLBACK_URL = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")

_BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOKEN_PATH = os.getenv(
    "SCHWAB_TOKEN_PATH",
    os.path.join(_BASE_DIR, "data", "schwab_token.json")
)

# ── module-level state ────────────────────────────────────────────────────────
_client = None          # schwab.client.Client instance
_client_lock = threading.Lock()
_schwab_available = False   # True once client is successfully initialised
_init_attempted = False     # Prevents repeated retries after a hard failure


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def schwab_available() -> bool:
    """Return True if the Schwab client is ready for API calls."""
    _ensure_client()
    return _schwab_available


def get_client():
    """Return the authenticated schwab-py Client, or None if unavailable."""
    _ensure_client()
    return _client if _schwab_available else None


def force_reauth():
    """
    Delete the stored token and re-run the interactive OAuth flow.
    Run this from the terminal when the token has expired:

        python -c "from skills.schwab_client import force_reauth; force_reauth()"
    """
    global _client, _schwab_available, _init_attempted
    if os.path.exists(_TOKEN_PATH):
        os.remove(_TOKEN_PATH)
        logger.info("Removed stale token at %s", _TOKEN_PATH)
    with _client_lock:
        _client = None
        _schwab_available = False
        _init_attempted = False
    _ensure_client(interactive=True)


# ─────────────────────────────────────────────────────────────────────────────
# Internal initialisation
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_client(interactive: bool = False):
    """Lazy-initialise the Schwab client (thread-safe, idempotent)."""
    global _client, _schwab_available, _init_attempted

    if _schwab_available or _init_attempted:
        return

    with _client_lock:
        # Double-checked locking
        if _schwab_available or _init_attempted:
            return

        _init_attempted = True

        # ── sanity checks ─────────────────────────────────────────────────────
        if not SCHWAB_API_KEY or not SCHWAB_APP_SECRET:
            logger.warning(
                "Schwab API credentials not set. "
                "Add SCHWAB_API_KEY and SCHWAB_APP_SECRET to .env"
            )
            return

        # ── try to import schwab-py ───────────────────────────────────────────
        try:
            import schwab  # noqa: F401 — presence check
            from schwab import auth as schwab_auth
        except ImportError:
            logger.warning(
                "schwab-py not installed. Run: pip install schwab-py  "
                "(falling back to yfinance)"
            )
            return

        # ── ensure token directory exists ─────────────────────────────────────
        os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)

        # ── token file present → try to load without browser ─────────────────
        if os.path.exists(_TOKEN_PATH):
            try:
                client = schwab_auth.client_from_token_file(
                    token_path=_TOKEN_PATH,
                    api_key=SCHWAB_API_KEY,
                    app_secret=SCHWAB_APP_SECRET,
                )
                _client = client
                _schwab_available = True
                logger.info("✅ Schwab client initialised from token file (%s)", _TOKEN_PATH)
                return
            except Exception as exc:
                logger.warning("Token file load failed (%s) — will re-auth if interactive", exc)

        # ── no token or stale token → need browser flow ───────────────────────
        if not interactive:
            logger.info(
                "No valid Schwab token at %s. "
                "Run `python -c \"from skills.schwab_client import force_reauth; force_reauth()\"` "
                "to authenticate, then restart the server.",
                _TOKEN_PATH,
            )
            return

        # ── interactive browser login ─────────────────────────────────────────
        try:
            client = schwab_auth.easy_client(
                api_key=SCHWAB_API_KEY,
                app_secret=SCHWAB_APP_SECRET,
                callback_url=SCHWAB_CALLBACK_URL,
                token_path=_TOKEN_PATH,
                # easy_client will open a browser or print a URL to visit
            )
            _client = client
            _schwab_available = True
            logger.info("✅ Schwab client authenticated via browser flow")
        except Exception as exc:
            logger.error("Schwab interactive auth failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# High-level data helpers (called from financial_skills.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_quote(ticker: str) -> dict | None:
    """
    Fetch a real-time quote for *ticker* from Schwab.

    Returns a normalised dict (same shape as the yfinance fallback) or None.
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx
        resp = client.get_quote(ticker)
        if resp.status_code != httpx.codes.OK:
            logger.warning("Schwab quote HTTP %s for %s", resp.status_code, ticker)
            return None

        data = resp.json()
        q = data.get(ticker, {})

        # The Schwab quote payload nests data under asset-type sub-keys.
        # We walk common sub-keys to find the right payload.
        quote_payload = (
            q.get("quote")
            or q.get("equity")
            or q.get("etf")
            or q
        )

        price       = _safe_float(quote_payload.get("lastPrice") or quote_payload.get("mark"))
        open_p      = _safe_float(quote_payload.get("openPrice"))
        high_p      = _safe_float(quote_payload.get("highPrice"))
        low_p       = _safe_float(quote_payload.get("lowPrice"))
        prev_close  = _safe_float(quote_payload.get("closePrice"))
        change      = _safe_float(quote_payload.get("netChange"))
        change_pct  = _safe_float(quote_payload.get("netPercentChangeInDouble"))
        volume      = _safe_int(quote_payload.get("totalVolume"))
        avg_volume  = _safe_int(quote_payload.get("avgVolume") or quote_payload.get("averageVolume10Days"))
        high_52w    = _safe_float(quote_payload.get("52WkHigh") or quote_payload.get("fiftyTwoWeekHigh"))
        low_52w     = _safe_float(quote_payload.get("52WkLow") or quote_payload.get("fiftyTwoWeekLow"))

        if price is None:
            return None

        return {
            "ticker":      ticker,
            "price":       round(price, 2),
            "open":        round(open_p, 2)     if open_p   is not None else None,
            "high":        round(high_p, 2)     if high_p   is not None else None,
            "low":         round(low_p, 2)      if low_p    is not None else None,
            "prev_close":  round(prev_close, 2) if prev_close is not None else None,
            "change":      round(change, 2)     if change   is not None else None,
            "change_pct":  round(change_pct, 4) if change_pct is not None else None,
            "volume":      volume,
            "avg_volume":  avg_volume,
            "high_52w":    high_52w,
            "low_52w":     low_52w,
            "market_cap":  None,  # not in quote endpoint
            "pe_ratio":    None,  # not in quote endpoint
            "source":      "Charles Schwab (production)",
            "timestamp":   datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.warning("Schwab get_quote failed for %s: %s", ticker, exc)
        return None


def get_quotes_batch(tickers: list[str]) -> dict:
    """
    Fetch quotes for multiple tickers in a single Schwab API call.

    Returns {ticker: normalised_quote_dict} for successful tickers.
    """
    client = get_client()
    if not client:
        return {}

    try:
        import httpx
        resp = client.get_quotes(tickers)
        if resp.status_code != httpx.codes.OK:
            logger.warning("Schwab batch quotes HTTP %s", resp.status_code)
            return {}

        raw = resp.json()
        result = {}
        for ticker in tickers:
            q_data = raw.get(ticker)
            if not q_data:
                continue
            quote_payload = (
                q_data.get("quote")
                or q_data.get("equity")
                or q_data.get("etf")
                or q_data
            )
            price = _safe_float(
                quote_payload.get("lastPrice") or quote_payload.get("mark")
            )
            if price is None:
                continue
            change     = _safe_float(quote_payload.get("netChange"))
            change_pct = _safe_float(quote_payload.get("netPercentChangeInDouble"))
            result[ticker] = {
                "ticker":     ticker,
                "price":      round(price, 2),
                "open":       _safe_float(quote_payload.get("openPrice")),
                "high":       _safe_float(quote_payload.get("highPrice")),
                "low":        _safe_float(quote_payload.get("lowPrice")),
                "prev_close": _safe_float(quote_payload.get("closePrice")),
                "change":     round(change, 2)     if change     is not None else None,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
                "volume":     _safe_int(quote_payload.get("totalVolume")),
                "avg_volume": _safe_int(quote_payload.get("averageVolume10Days")),
                "high_52w":   _safe_float(quote_payload.get("52WkHigh")),
                "low_52w":    _safe_float(quote_payload.get("52WkLow")),
                "source":     "Charles Schwab (production)",
                "timestamp":  datetime.utcnow().isoformat(),
            }
        return result
    except Exception as exc:
        logger.warning("Schwab get_quotes_batch failed: %s", exc)
        return {}


def get_price_history(ticker: str, days: int = 365) -> list[dict] | None:
    """
    Fetch daily OHLCV history for *ticker* from Schwab.

    Returns a list of {time, open, high, low, close, volume} dicts
    sorted oldest → newest, or None on failure.
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx
        from datetime import timedelta, timezone

        end_dt   = datetime.now(tz=timezone.utc)
        start_dt = end_dt - timedelta(days=days)

        resp = client.get_price_history_every_day(
            ticker,
            start_datetime=start_dt,
            end_datetime=end_dt,
            need_extended_hours_data=False,
            need_previous_close=True,
        )

        if resp.status_code != httpx.codes.OK:
            logger.warning("Schwab price history HTTP %s for %s", resp.status_code, ticker)
            return None

        payload = resp.json()
        candles = payload.get("candles", [])
        result  = []
        for c in candles:
            ts = c.get("datetime")  # epoch milliseconds
            if ts is None:
                continue
            dt = datetime.utcfromtimestamp(ts / 1000)
            result.append({
                "time":   dt.strftime("%Y-%m-%d"),
                "open":   round(float(c.get("open", 0)), 2),
                "high":   round(float(c.get("high", 0)), 2),
                "low":    round(float(c.get("low", 0)), 2),
                "close":  round(float(c.get("close", 0)), 2),
                "volume": int(c.get("volume", 0)),
            })
        return result if result else None
    except Exception as exc:
        logger.warning("Schwab get_price_history failed for %s: %s", ticker, exc)
        return None


def get_intraday_history(ticker: str, days: int = 5, interval: str = "5m") -> list[dict] | None:
    """
    Fetch intraday OHLCV history for *ticker* from Schwab.

    *interval* can be '1m', '5m', '10m', '15m', '30m'.
    Returns a list of {time, open, high, low, close, volume} dicts
    sorted oldest → newest, or None on failure.
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx
        from datetime import timedelta, timezone

        end_dt   = datetime.now(tz=timezone.utc)
        start_dt = end_dt - timedelta(days=days)

        freq_map = {
            "1m": client.PriceHistory.Frequency.EVERY_MINUTE,
            "5m": client.PriceHistory.Frequency.EVERY_FIVE_MINUTES,
            "10m": client.PriceHistory.Frequency.EVERY_TEN_MINUTES,
            "15m": client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES,
            "30m": client.PriceHistory.Frequency.EVERY_THIRTY_MINUTES,
        }
        frequency = freq_map.get(interval.lower(), client.PriceHistory.Frequency.EVERY_FIVE_MINUTES)

        resp = client.get_price_history(
            ticker,
            period_type=client.PriceHistory.PeriodType.DAY,
            frequency_type=client.PriceHistory.FrequencyType.MINUTE,
            frequency=frequency,
            start_datetime=start_dt,
            end_datetime=end_dt,
            need_extended_hours_data=True,
            need_previous_close=True,
        )

        if resp.status_code != httpx.codes.OK:
            logger.warning("Schwab intraday history HTTP %s for %s", resp.status_code, ticker)
            return None

        payload = resp.json()
        candles = payload.get("candles", [])
        result  = []
        for c in candles:
            ts = c.get("datetime")  # epoch milliseconds
            if ts is None:
                continue
            dt = datetime.utcfromtimestamp(ts / 1000)
            result.append({
                "time":   dt.isoformat(),
                "open":   round(float(c.get("open", 0)), 2),
                "high":   round(float(c.get("high", 0)), 2),
                "low":    round(float(c.get("low", 0)), 2),
                "close":  round(float(c.get("close", 0)), 2),
                "volume": int(c.get("volume", 0)),
            })
        return result if result else None
    except Exception as exc:
        logger.warning("Schwab get_intraday_history failed for %s: %s", ticker, exc)
        return None


def get_option_chain(ticker: str, expiry: str = None) -> dict | None:
    """
    Fetch the full options chain for *ticker* from Schwab.

    *expiry* is an optional 'YYYY-MM-DD' string.  When None, the nearest
    expiration is used.

    Returns a normalised dict compatible with the existing code, or None.
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx

        kwargs = {}
        if expiry:
            # Schwab accepts from_date / to_date to filter expiry range
            kwargs["from_date"]    = datetime.strptime(expiry, "%Y-%m-%d")
            kwargs["to_date"]      = datetime.strptime(expiry, "%Y-%m-%d")

        resp = client.get_option_chain(ticker, **kwargs)
        if resp.status_code != httpx.codes.OK:
            logger.warning("Schwab options HTTP %s for %s", resp.status_code, ticker)
            return None

        data = resp.json()

        # Extract expiration dates
        call_map = data.get("callExpDateMap", {})
        put_map  = data.get("putExpDateMap", {})

        if not call_map and not put_map:
            return None

        # Pick the earliest expiration key (format: "YYYY-MM-DD:N")
        all_expiry_keys = sorted(list(call_map.keys()) + list(put_map.keys()))
        target_key = all_expiry_keys[0] if all_expiry_keys else None
        target_exp_date = target_key.split(":")[0] if target_key else expiry

        calls_raw = list(call_map.get(target_key, {}).values()) if target_key in call_map else []
        puts_raw  = list(put_map.get(target_key, {}).values())  if target_key in put_map  else []

        def flatten_contracts(contracts_by_strike):
            """Each strike maps to a list with one contract dict."""
            flat = []
            for contracts in contracts_by_strike:
                for c in contracts:
                    flat.append(c)
            return flat

        calls = flatten_contracts(calls_raw)
        puts  = flatten_contracts(puts_raw)

        def parse_contract(c: dict) -> dict:
            return {
                "strike":        c.get("strikePrice"),
                "bid":           c.get("bid"),
                "ask":           c.get("ask"),
                "last":          c.get("last"),
                "volume":        c.get("totalVolume"),
                "open_interest": c.get("openInterest"),
                "iv":            c.get("volatility"),
                "delta":         c.get("delta"),
                "gamma":         c.get("gamma"),
                "theta":         c.get("theta"),
                "vega":          c.get("vega"),
                "rho":           c.get("rho"),
                "in_the_money":  c.get("inTheMoney"),
                "expiry":        c.get("expirationDate"),
            }

        parsed_calls = [parse_contract(c) for c in calls]
        parsed_puts  = [parse_contract(c) for c in puts]

        # Identify unusual options activity (volume > 3x open interest)
        unusual = []
        for opt_type, contracts in [("call", calls), ("put", puts)]:
            for c in contracts:
                vol = c.get("totalVolume") or 0
                oi  = c.get("openInterest") or 1
                if vol > 3 * oi and vol > 50:
                    unusual.append({
                        "type":           opt_type,
                        "strike":         c.get("strikePrice"),
                        "expiry":         c.get("expirationDate"),
                        "volume":         vol,
                        "open_interest":  oi,
                        "vol_oi_ratio":   round(vol / max(oi, 1), 1),
                        "premium_est":    round((c.get("last") or 0) * vol * 100, 0),
                        "iv":             c.get("volatility"),
                        "delta":          c.get("delta"),
                    })

        total_call_vol = sum(c.get("totalVolume") or 0 for c in calls)
        total_put_vol  = sum(c.get("totalVolume") or 0 for c in puts)

        return {
            "ticker":          ticker,
            "expiry":          target_exp_date,
            "underlying_price": data.get("underlyingPrice"),
            "call_count":      len(calls),
            "put_count":       len(puts),
            "total_call_volume": total_call_vol,
            "total_put_volume":  total_put_vol,
            "put_call_ratio":  round(total_put_vol / max(total_call_vol, 1), 2),
            "top_calls":       sorted(parsed_calls, key=lambda x: x.get("volume") or 0, reverse=True)[:10],
            "top_puts":        sorted(parsed_puts,  key=lambda x: x.get("volume") or 0, reverse=True)[:10],
            "all_calls":       parsed_calls,
            "all_puts":        parsed_puts,
            "unusual_activity": unusual,
            "iv_mark":         data.get("volatility"),
            "source":          "Charles Schwab (production)",
            "timestamp":       datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.warning("Schwab get_option_chain failed for %s: %s", ticker, exc)
        return None


def get_movers(index: str = "$SPX") -> dict | None:
    """
    Fetch top market movers from Schwab for a given index.

    *index* examples: ``$SPX``, ``$COMPX``, ``$DJI``, ``NYSE``, ``NASDAQ``.
    Returns a normalised dict or None.
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx

        # Map common symbols to Schwab's Movers index enum
        _idx_map = {
            "SPX":    "$SPX.X",
            "$SPX":   "$SPX.X",
            "SPY":    "$SPX.X",
            "QQQ":    "$COMPX",
            "$COMPX": "$COMPX",
            "DIA":    "$DJI",
            "$DJI":   "$DJI",
        }
        schwab_index = _idx_map.get(index.upper(), index)

        resp = client.get_movers(schwab_index)
        if resp.status_code != httpx.codes.OK:
            logger.warning("Schwab movers HTTP %s for %s", resp.status_code, index)
            return None

        data = resp.json()
        screeners = data.get("screeners", [])
        if not screeners:
            # Some API versions return a list directly
            screeners = data if isinstance(data, list) else []

        gainers = [m for m in screeners if (m.get("netChange") or 0) > 0]
        losers  = [m for m in screeners if (m.get("netChange") or 0) < 0]
        actives = sorted(screeners, key=lambda x: x.get("totalVolume") or 0, reverse=True)

        def fmt(m: dict) -> dict:
            return {
                "ticker":     m.get("symbol"),
                "name":       m.get("description"),
                "price":      _safe_float(m.get("last")),
                "change":     _safe_float(m.get("netChange")),
                "change_pct": _safe_float(m.get("netPercentChangeInDouble")),
                "volume":     _safe_int(m.get("totalVolume")),
            }

        return {
            "index":   index,
            "gainers": [fmt(m) for m in sorted(gainers, key=lambda x: x.get("netPercentChangeInDouble") or 0, reverse=True)[:10]],
            "losers":  [fmt(m) for m in sorted(losers,  key=lambda x: x.get("netPercentChangeInDouble") or 0)[:10]],
            "actives": [fmt(m) for m in actives[:10]],
            "source":  "Charles Schwab (production)",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.warning("Schwab get_movers failed for %s: %s", index, exc)
        return None


def get_market_hours() -> dict | None:
    """
    Return today's market session hours (equity market).
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx

        resp = client.get_market_hours(
            markets=[client.MarketHours.Market.EQUITY],
        )
        if resp.status_code != httpx.codes.OK:
            return None

        data = resp.json()
        equity = data.get("equity", {}).get("EQ", {})
        return {
            "is_open":      equity.get("isOpen"),
            "session_hours": equity.get("sessionHours"),
            "source":       "Charles Schwab",
            "timestamp":    datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.warning("Schwab get_market_hours failed: %s", exc)
        return None


def get_instruments(query: str) -> list[dict] | None:
    """
    Search for instruments by symbol or description.
    Useful for resolving tickers from company names.
    """
    client = get_client()
    if not client:
        return None

    try:
        import httpx

        resp = client.get_instruments(
            symbols=[query],
            projection=client.Instrument.Projection.SYMBOL_SEARCH,
        )
        if resp.status_code != httpx.codes.OK:
            return None

        data = resp.json()
        instruments = data.get("instruments", [])
        return [
            {
                "symbol":      i.get("symbol"),
                "description": i.get("description"),
                "exchange":    i.get("exchange"),
                "asset_type":  i.get("assetType"),
                "cusip":       i.get("cusip"),
            }
            for i in instruments
        ]
    except Exception as exc:
        logger.warning("Schwab get_instruments failed for '%s': %s", query, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Auth helper — generate the first token interactively
# ─────────────────────────────────────────────────────────────────────────────

def run_first_time_auth():
    """
    Interactive helper for first-time OAuth2 authentication.

    Uses the manual copy-paste flow (client_from_manual_flow):
    1. A URL is printed to the terminal.
    2. Open it in a browser, log in with Schwab credentials.
    3. After login, Schwab redirects to https://127.0.0.1?code=...
       The page will fail to load — that is EXPECTED.
    4. Copy the FULL URL from the browser address bar and paste it here.

    Run from a terminal:
        python skills/schwab_client.py
    """
    if not SCHWAB_API_KEY or not SCHWAB_APP_SECRET:
        print("ERROR: SCHWAB_API_KEY and SCHWAB_APP_SECRET must be set in .env")
        return

    try:
        from schwab import auth as schwab_auth
    except ImportError:
        print("ERROR: schwab-py not installed. Run: pip install schwab-py")
        return

    os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
    print(f"\n{'='*64}")
    print("  Charles Schwab \u2014 First-time OAuth2 Authentication")
    print(f"{'='*64}")
    print(f"\n  Client ID    : {SCHWAB_API_KEY[:12]}...")
    print(f"  Callback URL : {SCHWAB_CALLBACK_URL}")
    print(f"  Token path   : {_TOKEN_PATH}")
    print()
    print("  Instructions")
    print("  " + "\u2500" * 40)
    print("  1. A browser login URL will be printed below.")
    print("  2. Open it in any browser and log in with your Schwab credentials.")
    print("  3. After login, the browser will redirect to https://127.0.0.1")
    print("     The page will show a connection error \u2014 that is EXPECTED.")
    print("  4. Copy the FULL URL from the browser address bar")
    print("     (starts with https://127.0.0.1?code=...)")
    print("  5. Paste it below and press Enter.")
    print()

    try:
        client = schwab_auth.client_from_manual_flow(
            api_key=SCHWAB_API_KEY,
            app_secret=SCHWAB_APP_SECRET,
            callback_url=SCHWAB_CALLBACK_URL,
            token_path=_TOKEN_PATH,
        )
        print(f"\n\u2705 Authentication complete! Token saved to:\n   {_TOKEN_PATH}")
        print("   Restart the FinClaw server to activate Schwab real-time data.\n")
        return client
    except Exception as exc:
        print(f"\n\u274c Authentication failed: {exc}")
        print("\nTroubleshooting:")
        print("  - Make sure the callback URL in the Schwab developer portal matches exactly:")
        print(f"    {SCHWAB_CALLBACK_URL}")
        print("  - Your app status must be 'Ready for use' on developer.schwab.com")
        print("  - Try deleting data/schwab_token.json and re-running this script")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_first_time_auth()
