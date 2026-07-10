"""
FinClaw API Server — Flask Backend
=====================================
REST API that exposes all financial skills as endpoints
for the interactive dashboard. Run with:

    python server.py

Then open http://localhost:5055 for the dashboard.
"""

import os
import re
import sys
import json
import logging
import yaml
from datetime import datetime, date
from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS

# Ensure skills directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))

from financial_skills import (
    get_stock_quote,
    get_options_chain,
    get_market_movers,
    get_technical_analysis,
    get_portfolio,
    add_portfolio_holding,
    get_news,
    get_earnings_calendar,
    get_fundamentals,
    get_insider_activity,
    get_fear_greed_index,
    get_economic_indicators,
    get_earnings_analysis,
    get_sector_rotation,
    clear_cache,
    get_cache_stats,
)

from opportunity_engine import (
    build_opportunity_brief,
    get_opportunities,
)

from db import (
    init_db,
    save_signal,
    resolve_signal,
    get_signals,
    get_signal_performance,
    save_portfolio_snapshot,
    get_portfolio_history,
    save_options_flow,
    get_options_flow_history,
    get_options_flow_summary,
    save_alert,
    get_alerts,
    acknowledge_alert,
    save_scan,
    get_scan_history,
)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("finclaw")


# ============================================================
# INPUT VALIDATION
# ============================================================
_TICKER_RE = re.compile(
    r'^[A-Z]{1,5}$'            # Normal tickers: AAPL, NVDA
    r'|^\^[A-Z]{2,5}$'         # Index symbols: ^VIX, ^TNX
    r'|^[A-Z]+-[A-Z]+$'        # Crypto pairs: BTC-USD
    r'|^[A-Z]+=F$'             # Futures: GC=F, CL=F
)

def validate_ticker(ticker: str) -> str:
    """Sanitize and validate ticker input. Returns uppercase ticker or aborts 400."""
    ticker = ticker.strip().upper()[:12]  # hard length cap
    if not _TICKER_RE.match(ticker):
        abort(400, description=f"Invalid ticker symbol: {ticker}")
    return ticker


# ============================================================
# CONFIG LOADER
# ============================================================
_config_path = os.path.join(os.path.dirname(__file__), "openclaw.config.yml")
_config = {}
try:
    with open(_config_path, "r") as f:
        _config = yaml.safe_load(f) or {}
    logger.info("Loaded config from %s", _config_path)
except Exception as e:
    logger.warning("Could not load config: %s", e)

# ============================================================
# APP SETUP
# ============================================================
app = Flask(__name__, static_folder="dashboard")
CORS(app)

# Initialize database explicitly (not on import)
init_db()
logger.info("Database initialized")

# Rate limiting — prevent API key exhaustion
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["120 per minute"],
        storage_uri="memory://",
    )
    logger.info("Rate limiter enabled (120 req/min)")
except ImportError:
    limiter = None
    logger.warning("flask-limiter not installed — rate limiting disabled. Run: pip install flask-limiter")


# ============================================================
# SERVE DASHBOARD
# ============================================================
@app.route("/")
def serve_dashboard():
    """Serve the interactive dashboard."""
    return send_from_directory("dashboard", "index.html")


@app.route("/dashboard/<path:filename>")
def serve_dashboard_files(filename):
    """Serve dashboard static files."""
    return send_from_directory("dashboard", filename)


# ============================================================
# MARKET DATA ENDPOINTS
# ============================================================
@app.route("/api/quote/<ticker>")
def api_quote(ticker):
    """Get stock quote for a ticker."""
    ticker = validate_ticker(ticker)
    return jsonify(get_stock_quote(ticker))


@app.route("/api/quotes")
def api_quotes():
    """Get quotes for multiple tickers (comma-separated)."""
    tickers = request.args.get("tickers", "").split(",")
    tickers = [t.strip() for t in tickers if t.strip()]
    results = {}
    for t in tickers[:20]:  # Limit to 20 tickers
        results[t.upper()] = get_stock_quote(t)
    return jsonify(results)


@app.route("/api/technicals/<ticker>")
def api_technicals(ticker):
    """Get technical analysis for a ticker."""
    ticker = validate_ticker(ticker)
    return jsonify(get_technical_analysis(ticker))


@app.route("/api/fundamentals/<ticker>")
def api_fundamentals(ticker):
    """Get fundamental analysis for a ticker."""
    ticker = validate_ticker(ticker)
    return jsonify(get_fundamentals(ticker))


@app.route("/api/insider/<ticker>")
def api_insider(ticker):
    """Get insider activity for a ticker."""
    ticker = validate_ticker(ticker)
    return jsonify(get_insider_activity(ticker))


@app.route("/api/earnings/<ticker>")
def api_earnings_analysis(ticker):
    """Get earnings analysis for a ticker."""
    ticker = validate_ticker(ticker)
    return jsonify(get_earnings_analysis(ticker))


# ============================================================
# MARKET OVERVIEW ENDPOINTS
# ============================================================
@app.route("/api/market/movers")
def api_market_movers():
    """Get market movers and sector performance."""
    return jsonify(get_market_movers())


@app.route("/api/market/fear-greed")
def api_fear_greed():
    """Get Fear & Greed composite index."""
    return jsonify(get_fear_greed_index())


@app.route("/api/market/sectors")
def api_sectors():
    """Get sector rotation analysis."""
    return jsonify(get_sector_rotation())


@app.route("/api/market/economic")
def api_economic():
    """Get economic indicators."""
    return jsonify(get_economic_indicators())


# ============================================================
# OPTIONS ENDPOINTS
# ============================================================
@app.route("/api/options/<ticker>")
def api_options(ticker):
    """Get options chain for a ticker."""
    ticker = validate_ticker(ticker)
    expiry = request.args.get("expiry")
    return jsonify(get_options_chain(ticker, expiry))


@app.route("/api/options/flow/history")
def api_options_flow_history():
    """Get historical options flow data."""
    ticker = request.args.get("ticker")
    days = int(request.args.get("days", 7))
    return jsonify(get_options_flow_history(ticker, days))


@app.route("/api/options/flow/summary/<ticker>")
def api_options_flow_summary(ticker):
    """Get options flow summary for a ticker."""
    days = int(request.args.get("days", 5))
    return jsonify(get_options_flow_summary(ticker, days))


# ============================================================
# PORTFOLIO ENDPOINTS
# ============================================================
@app.route("/api/portfolio")
def api_portfolio():
    """Get portfolio with live prices."""
    portfolio = get_portfolio()

    # Save snapshot for history tracking (max one per day)
    if "summary" in portfolio:
        s = portfolio["summary"]
        today_str = date.today().isoformat()
        existing = get_portfolio_history(days=1)
        already_saved = any(
            snap.get("created_at", "")[:10] == today_str
            for snap in existing
        )
        if not already_saved:
            spy = get_stock_quote("SPY")
            save_portfolio_snapshot(
                s["total_value"], s["total_cost"], s["total_gain_loss"],
                s["total_return_pct"], spy.get("price"),
                portfolio.get("holdings")
            )
            logger.info("Saved daily portfolio snapshot (value=$%.2f)", s["total_value"])

    return jsonify(portfolio)


@app.route("/api/portfolio/holding", methods=["POST"])
def api_add_holding():
    """Add or update a portfolio holding."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    result = add_portfolio_holding(
        ticker=data.get("ticker", ""),
        shares=data.get("shares", 0),
        avg_cost=data.get("avg_cost", 0),
        sector=data.get("sector", "Other"),
        horizon=data.get("horizon", "long-term"),
        notes=data.get("notes", ""),
    )
    return jsonify(result)


@app.route("/api/portfolio/history")
def api_portfolio_history():
    """Get portfolio value history for performance charting."""
    days = int(request.args.get("days", 90))
    return jsonify(get_portfolio_history(days))


# ============================================================
# NEWS ENDPOINTS
# ============================================================
@app.route("/api/news")
def api_news_general():
    """Get general market news."""
    limit = int(request.args.get("limit", 10))
    return jsonify(get_news(query="stock market", limit=limit))


@app.route("/api/news/<ticker>")
def api_news_ticker(ticker):
    """Get news for a specific ticker."""
    ticker = validate_ticker(ticker)
    limit = int(request.args.get("limit", 10))
    return jsonify(get_news(ticker=ticker, limit=limit))


# ============================================================
# EARNINGS CALENDAR
# ============================================================
@app.route("/api/earnings/calendar")
def api_earnings_calendar():
    """Get upcoming earnings dates."""
    tickers = request.args.get("tickers")
    if tickers:
        tickers = [t.strip() for t in tickers.split(",")]
    return jsonify(get_earnings_calendar(tickers))


# ============================================================
# SIGNALS ENDPOINTS
# ============================================================
@app.route("/api/signals")
def api_get_signals():
    """Get AI signal history."""
    ticker = request.args.get("ticker")
    limit = int(request.args.get("limit", 50))
    return jsonify(get_signals(ticker, limit))


@app.route("/api/signals", methods=["POST"])
def api_save_signal():
    """Save a new AI signal."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    save_signal(
        ticker=data.get("ticker"),
        action=data.get("action"),
        horizon=data.get("horizon"),
        confidence=data.get("confidence"),
        entry_low=data.get("entry_low"),
        entry_high=data.get("entry_high"),
        target_price=data.get("target_price"),
        stop_loss=data.get("stop_loss"),
        thesis=data.get("thesis"),
        price_at_signal=data.get("price_at_signal"),
    )
    return jsonify({"status": "saved"})


@app.route("/api/signals/<int:signal_id>/resolve", methods=["POST"])
def api_resolve_signal(signal_id):
    """Resolve a signal with outcome."""
    data = request.json
    resolve_signal(
        signal_id,
        data.get("outcome"),
        data.get("outcome_price"),
        data.get("outcome_return_pct"),
    )
    return jsonify({"status": "resolved"})


@app.route("/api/signals/performance")
def api_signal_performance():
    """Get signal win/loss statistics."""
    return jsonify(get_signal_performance())


@app.route("/api/signals/resolve", methods=["POST"])
def api_resolve_signals():
    """Auto-resolve all OPEN signals against current prices."""
    try:
        from signal_resolver import resolve_open_signals
        result = resolve_open_signals(
            get_stock_quote_fn=get_stock_quote,
            get_signals_fn=get_signals,
            resolve_signal_fn=resolve_signal,
        )
        return jsonify({"status": "resolved", "results": result})
    except Exception as e:
        logger.error("Signal resolution failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ============================================================
# NOTIFICATIONS ENDPOINTS
# ============================================================
@app.route("/api/notify", methods=["POST"])
def api_send_notification():
    """Send a notification via configured channels (Telegram, Slack, Email)."""
    data = request.json
    if not data or not data.get("message"):
        return jsonify({"error": "message is required"}), 400

    try:
        from notifications import send_alert as notify
        result = notify(
            title=data.get("title", "FinClaw Alert"),
            message=data.get("message"),
            channels=data.get("channels"),
        )
        save_alert(
            alert_type=data.get("type", "info"),
            title=data.get("title", "FinClaw Alert"),
            message=data.get("message"),
            ticker=data.get("ticker"),
        )
        return jsonify({"status": "sent", "channels": result})
    except Exception as e:
        logger.error("Notification failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/notify/test", methods=["POST"])
def api_test_notification():
    """Send a test notification to verify setup."""
    try:
        from notifications import send_alert as notify
        result = notify(
            title="🧪 Test Notification",
            message="If you see this, your FinClaw notifications are working!",
        )
        return jsonify({"status": "test sent", "channels": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# ALERTS ENDPOINTS
# ============================================================
@app.route("/api/alerts")
def api_get_alerts():
    """Get alert history."""
    limit = int(request.args.get("limit", 50))
    unread = request.args.get("unread", "false").lower() == "true"
    return jsonify(get_alerts(limit, unread))


@app.route("/api/alerts/<int:alert_id>/ack", methods=["POST"])
def api_ack_alert(alert_id):
    """Acknowledge an alert."""
    acknowledge_alert(alert_id)
    return jsonify({"status": "acknowledged"})


# ============================================================
# SCAN HISTORY
# ============================================================
@app.route("/api/scans")
def api_scan_history():
    """Get scan history."""
    scan_type = request.args.get("type")
    days = int(request.args.get("days", 7))
    return jsonify(get_scan_history(scan_type, days))


# ============================================================
# OPPORTUNITY SCANNER
# ============================================================
def _parse_ticker_list(raw_value):
    """Parse and validate a comma-separated ticker list from request input."""
    if not raw_value:
        return None
    tickers = []
    for raw in str(raw_value).split(","):
        raw = raw.strip()
        if raw:
            tickers.append(validate_ticker(raw))
    return tickers[:80]


def _parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes", "on")


@app.route("/api/opportunities")
def api_opportunities():
    """
    Get ranked opportunities across configured OpenClaw watchlists.
    Query params:
      session=premarket|regular|postmarket|closed|auto
      horizon=scalp|day|swing|long|auto
      tickers=AAPL,NVDA
      limit=12
      include_options=true|false
      min_score=0-100
    """
    session = request.args.get("session", "auto")
    horizon = request.args.get("horizon", "auto")
    tickers = _parse_ticker_list(request.args.get("tickers"))
    limit = int(request.args.get("limit", 12))
    universe_limit = int(request.args.get("universe_limit", 24))
    min_score = int(request.args.get("min_score", 0))
    include_options = _parse_bool(request.args.get("include_options"), True)

    result = get_opportunities(
        session=session,
        horizon=horizon,
        tickers=tickers,
        limit=limit,
        universe_limit=universe_limit,
        min_score=min_score,
        include_options=include_options,
    )
    return jsonify(result)


@app.route("/api/opportunities/scan", methods=["POST"])
def api_opportunities_scan():
    """
    Run an opportunity scan, save it to scan history, and optionally notify.
    Runs asynchronously so the scheduler never times out waiting.
    """
    import threading
    data = request.json or {}
    tickers = data.get("tickers")
    if isinstance(tickers, str):
        tickers = _parse_ticker_list(tickers)
    elif isinstance(tickers, list):
        tickers = [validate_ticker(str(t)) for t in tickers[:80]]
    else:
        tickers = None

    scan_params = {
        "session": data.get("session", "auto"),
        "horizon": data.get("horizon", "auto"),
        "tickers": tickers,
        "limit": int(data.get("limit", 12)),
        "universe_limit": int(data.get("universe_limit", 40)),
        "min_score": int(data.get("min_score", 0)),
        "include_options": _parse_bool(data.get("include_options"), True),
        "notify": data.get("notify", False),
        "channels": data.get("channels"),
    }

    def run_scan_async(params):
        try:
            result = get_opportunities(
                session=params["session"],
                horizon=params["horizon"],
                tickers=params["tickers"],
                limit=params["limit"],
                universe_limit=params["universe_limit"],
                min_score=params["min_score"],
                include_options=params["include_options"],
            )
            brief = build_opportunity_brief(result)
            scan_type = f"{result.get('session')}_{result.get('horizon')}_opportunities"
            save_scan(scan_type, result)
            logger.info("Scan complete: %s (%d opportunities)", scan_type, len(result.get('opportunities', [])))

            if params["notify"] and brief:
                try:
                    from notifications import send_alert as notify
                    notify(
                        title=f"FinClaw {result.get('session')} opportunities",
                        message=brief,
                        channels=params["channels"],
                    )
                    top_ticker = (result.get("opportunities") or [{}])[0].get("ticker")
                    save_alert(
                        alert_type="info",
                        title=f"{result.get('session', 'Market').title()} Opportunity Scan",
                        message=brief,
                        ticker=top_ticker,
                    )
                    logger.info("Telegram alert sent for %s", scan_type)
                    
                    # PORTFOLIO DEFENSE ALERTS
                    for opp in result.get('opportunities', []):
                        action = opp.get("action", "")
                        if action in ["PROFIT-TAKE", "SELL/TRIM"]:
                            reason_str = "; ".join(opp.get("reasons", []) + opp.get("risk_flags", []))
                            notify(
                                title=f"🚨 PORTFOLIO ALERT: {action} {opp.get('ticker')}",
                                message=f"Price: ${opp.get('price')}\nReason: {reason_str}",
                                channels=params["channels"],
                            )
                            save_alert(
                                alert_type="warning",
                                title=f"{action} {opp.get('ticker')}",
                                message=f"Price: ${opp.get('price')}\nReason: {reason_str}",
                                ticker=opp.get("ticker"),
                            )

                    # NEW: Advanced Manual Trading Alerts for High Conviction ML Signals
                    try:
                        from skills.execution_engine import execute_trade_from_signal
                        for opp in result.get('opportunities', []):
                            alert_res = execute_trade_from_signal(opp)
                            if alert_res.get("status") == "alert_sent":
                                notify(
                                    title=f"Manual Trade Alert: {opp.get('ticker')}",
                                    message=alert_res.get("message"),
                                    channels=params["channels"],
                                )
                    except Exception as ex:
                        logger.error("Failed to generate manual trade alerts: %s", ex)
                        
                except Exception as e:
                    logger.error("Opportunity notification failed: %s", e)
        except Exception as e:
            logger.error("Background scan failed: %s", e)

    thread = threading.Thread(target=run_scan_async, args=(scan_params,), daemon=True)
    thread.start()

    return jsonify({
        "status": "accepted",
        "message": "Scan started in background. Telegram alert will fire when complete (if high-conviction signals found).",
    }), 202


# ============================================================
# COMPREHENSIVE DASHBOARD DATA (single call)
# ============================================================
@app.route("/api/dashboard")
def api_dashboard():
    """
    Returns all data needed for the dashboard in a single call.
    This reduces the number of requests on initial page load.
    """
    try:
        # Core market data
        watchlist_tickers = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL"]

        # Fetch watchlist data with technicals
        watchlist = []
        for ticker in watchlist_tickers:
            quote = get_stock_quote(ticker)
            ta = get_technical_analysis(ticker)
            fund = get_fundamentals(ticker)

            # Generate simple signal from technicals
            rsi = ta.get("rsi_14", 50)
            macd_hist = ta.get("macd_histogram", 0)
            signal = "HOLD"
            if rsi < 35 and macd_hist > 0:
                signal = "BUY"
            elif rsi > 65 and macd_hist < 0:
                signal = "SELL"
            elif rsi < 40:
                signal = "WATCH"
            elif rsi > 60 and macd_hist > 0:
                signal = "BUY"

            watchlist.append({
                "ticker": ticker,
                "name": fund.get("name", ticker),
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "volume": quote.get("volume"),
                "rsi": round(rsi, 1) if isinstance(rsi, (int, float)) else None,
                "signal": signal,
                "market_cap": fund.get("market_cap_fmt"),
                "pe_ratio": fund.get("valuation", {}).get("pe_trailing"),
            })

        # Market overview
        market_movers = get_market_movers()

        # Fear & Greed
        fear_greed = get_fear_greed_index()

        # Portfolio
        portfolio = get_portfolio()

        # Recent alerts from DB
        alerts = get_alerts(limit=10)

        # Signal performance
        sig_perf = get_signal_performance()

        return jsonify({
            "watchlist": watchlist,
            "market": market_movers,
            "fear_greed": fear_greed,
            "portfolio": portfolio,
            "alerts": alerts,
            "signal_performance": sig_perf,
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# UTILITY ENDPOINTS
# ============================================================
@app.route("/api/cache/stats")
def api_cache_stats():
    """Get cache statistics."""
    return jsonify(get_cache_stats())


@app.route("/api/cache/clear", methods=["POST"])
def api_clear_cache():
    """Clear all cached data."""
    clear_cache()
    logger.info("Cache cleared by user")
    return jsonify({"status": "cache cleared"})


@app.route("/api/config/watchlist")
def api_config_watchlist():
    """Get watchlists from openclaw.config.yml so dashboard stays in sync."""
    monitoring = _config.get("monitoring", {})
    return jsonify({
        "watchlists": monitoring.get("watchlists", {"Default": ["SPY","QQQ","NVDA","AAPL","MSFT","TSLA","AMZN","META","GOOGL"]}),
        "source": "openclaw.config.yml",
    })


@app.route("/api/health")
def api_health():
    """Health check endpoint — includes data source status."""
    try:
        from skills.ibkr_client import ibkr_available
        ibkr_on = ibkr_available()
    except ImportError:
        ibkr_on = False

    return jsonify({
        "status":   "healthy",
        "agent":    "FinClaw",
        "version":  "2.2.0",
        "data_sources": {
            "ibkr":    {"active": ibkr_on,        "label": "Interactive Brokers (production)"},
            "tradier": {"active": bool(os.getenv("TRADIER_API_KEY")), "label": "Tradier"},
            "yfinance":{"active": True,              "label": "yfinance (fallback)"},
        },
        "timestamp": datetime.utcnow().isoformat(),
    })


# ============================================================
# IBKR API STATUS & AUTH ENDPOINTS
# ============================================================
@app.route("/api/ibkr/status")
def api_ibkr_status():
    """Return the current IBKR API connection status."""
    try:
        from skills.ibkr_client import (
            ibkr_available, IBKR_HOST, IBKR_PORT
        )
        active = ibkr_available()
        return jsonify({
            "authenticated":   active,
            "host":            IBKR_HOST,
            "port":            IBKR_PORT,
            "instructions":    (
                f"Ensure IB Gateway or TWS is running locally on port {IBKR_PORT}."
                if not active else "IBKR API is connected and active."
            ),
        })
    except ImportError:
        return jsonify({
            "authenticated": False,
            "error": "ib_async not installed. Run: pip install ib_async",
        })

@app.route("/api/ibkr/reauth", methods=["POST"])
def api_ibkr_reauth():
    """
    Trigger a forced reconnect to IB Gateway.
    """
    try:
        import skills.ibkr_client as _ic
        _ic._ibkr_available = False
        if _ic._ib:
            _ic._ib.disconnect()
            _ic._ib = None
        _ic._ensure_client()
        if _ic.ibkr_available():
            return jsonify({"status": "success", "message": "IBKR reconnected."})
        else:
            return jsonify({
                "status": "needs_auth",
                "message": (
                    f"Could not connect to IB Gateway on port {_ic.IBKR_PORT}."
                )
            }), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# MAIN
# ============================================================

# =====================================================================
# ADVANCED DASHBOARD ENDPOINTS (Heatmap, Rebalancer, Payoff, Sandbox)
# =====================================================================
@app.route("/api/portfolio/rebalance_simulation", methods=["POST"])
def api_portfolio_rebalance_simulation():
    try:
        from skills.financial_skills import get_portfolio
        from skills.opportunity_engine import get_opportunities
        
        portfolio = get_portfolio()
        holdings = portfolio.get("holdings", [])
        
        # Simple math logic to simulate moving allocations
        # In a real scenario we use actual Opportunity scores, here we mock the simulation logic
        
        return jsonify({
            "status": "success",
            "current_allocation": [{"ticker": h["ticker"], "shares": h["shares"], "value": h.get("current_value", 0)} for h in holdings],
            "ai_suggestion": "Reduce NVDA by 5%, Increase PLTR by 5% to reduce beta.",
            "risk_score_before": 85,
            "risk_score_after": 72
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/market/heatmap")
def api_market_heatmap():
    try:
        from skills.financial_skills import get_news
        # We will mock a quick sentiment analysis loop for the top 6 tickers
        tickers = ["NVDA", "PLTR", "AAPL", "TSLA", "CRWD", "ARM"]
        heatmap = []
        for t in tickers:
            # We mock the sentiment score to simulate the UI
            import random
            score = random.randint(-100, 100)
            heatmap.append({"ticker": t, "sentiment": score})
        return jsonify({"heatmap": heatmap})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/options/payoff", methods=["POST"])
def api_options_payoff():
    try:
        data = request.json
        ticker = data.get("ticker", "NVDA")
        strike = float(data.get("strike", 150.0))
        premium = float(data.get("premium", 5.0))
        opt_type = data.get("type", "call").lower()
        
        # Generate payoff array
        prices = [strike * (0.8 + 0.02 * i) for i in range(21)]
        payoff = []
        for p in prices:
            if opt_type == "call":
                profit = max(0, p - strike) - premium
            else:
                profit = max(0, strike - p) - premium
            payoff.append({"price": round(p, 2), "profit": round(profit * 100, 2)}) # *100 for contract multiplier
            
        return jsonify({
            "ticker": ticker,
            "strike": strike,
            "premium": premium,
            "type": opt_type,
            "payoff": payoff,
            "breakeven": strike + premium if opt_type == "call" else strike - premium
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    try:
        data = request.json
        ticker = data.get("ticker", "NVDA")
        strategy = data.get("strategy", "episodic_pivot")
        
        # In a real scenario we run historical simulation over 1 year of data.
        # We will mock the output to simulate the UI.
        import random
        win_rate = round(random.uniform(45.0, 85.0), 1)
        roi = round(random.uniform(10.0, 150.0), 1)
        
        return jsonify({
            "ticker": ticker,
            "strategy": strategy,
            "trades_executed": random.randint(5, 50),
            "win_rate": win_rate,
            "roi_pct": roi,
            "max_drawdown_pct": round(random.uniform(5.0, 25.0), 1)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    logger.info("")
    logger.info("🦾 FinClaw API Server Starting...")
    logger.info("=" * 50)
    logger.info("  Dashboard:  http://localhost:%d", port)
    logger.info("  API Base:   http://localhost:%d/api", port)
    logger.info("  Health:     http://localhost:%d/api/health", port)
    logger.info("  Debug mode: %s", debug)
    logger.info("=" * 50)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug,
        threaded=True,
    )
