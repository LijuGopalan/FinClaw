"""
FinClaw Scheduler — Algorithmic + LLM-Powered Market Intelligence
=================================================================
ENHANCED 24/7 QWEN UTILIZATION:

  PRE-MARKET (2:00-9:00 AM CST):
  - 02:00  Overnight news digest (Qwen)
  - 03:00  Earnings preview (Qwen)
  - 06:00  Pre-market catalyst scan (Qwen)
  - 08:15  Pre-market LLM brief (Qwen)

  MARKET HOURS (9:00-4:00 PM CST):
  - Every 15 min  Intraday scalp scan (algorithmic)
  - Every 15 min  News sentiment analysis (Qwen)
  - 10:00  Delivery volume confluence scan
  - 12:00  Midday LLM update (Qwen)
  - 14:00  Delivery volume confluence scan

  AFTER-HOURS (4:00-8:00 PM CST):
  - 16:05  Close summary LLM brief (Qwen)
  - 16:30  Daily trade journal & performance review (Qwen)
  - Every 30 min  After-hours monitoring (Qwen)
  - 18:00  Smart money tracker (Congress, insiders, ARK)

  CONTINUOUS (Every 4 hours, 24/7):
  - Volatility regime detection & strategy adjustment (Qwen)

  WEEKENDS (Markets Closed):
  - Saturday 09:00  Weekend deep research (all 37 stocks, Qwen)
  - Saturday 14:00  Portfolio rebalancing analysis (Qwen)
  - Saturday 23:00  ML model retraining (MLX)
  - Sunday 10:00   Week-ahead macro preview (Qwen)
  - Sunday 15:00   Weekly trading plan (Qwen)
  - Sunday 16:00   Weekly performance review (Qwen)

ALL LLM OPERATIONS NOW USE LOCAL QWEN 2.5 (ZERO COST, 100% PRIVATE)
"""

import os
import sys
import time
import threading
import requests
import logging
import pytz
from datetime import datetime

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] scheduler: %(message)s",
    filename="server.log",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

# ── Constants ───────────────────────────────────────────────────────────────
API_BASE = "http://localhost:5055/api"

# Add skills/ to path so we can import llm.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))

# Import new 24/7 monitoring functions
from overnight_monitor import overnight_news_digest, premarket_catalyst_scan, afterhours_monitoring
from weekend_research import weekend_deep_research_batch, weekly_trading_plan
from news_sentiment import get_sentiment_alerts

# Import advanced features
from smart_money_tracker import generate_smart_money_report
from trade_journal import generate_daily_journal, generate_weekly_performance_review
from volatility_regime import detect_volatility_regime

# Import ML retraining
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ml_pipeline"))
from auto_retrain import run_weekly_retrain, generate_retrain_report


# ── Helpers ─────────────────────────────────────────────────────────────────
def _api_get(path, timeout=30):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.warning("API GET %s failed: %s", path, e)
        return {}


def _send_telegram(message: str):
    """Send a message directly via Telegram Bot API."""
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logging.warning("Telegram not configured")
        return
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        res.raise_for_status()
    except Exception as e:
        # Fallback to plain text if HTML parsing fails (e.g. unclosed tags from Gemini)
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 400:
            logging.warning("Telegram HTML parse failed, retrying as plain text...")
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
                    timeout=10,
                ).raise_for_status()
            except Exception as e2:
                logging.error("Telegram fallback send failed: %s", e2)
        else:
            logging.error("Telegram send failed: %s", e)


# ── Algorithmic scan trigger ─────────────────────────────────────────────────
def trigger_scan(session_type, horizon, notify=True):
    try:
        url = f"{API_BASE}/opportunities/scan"
        payload = {"session": session_type, "horizon": horizon, "notify": notify}
        res = requests.post(url, json=payload, timeout=600)
        res.raise_for_status()
        logging.info("Triggered scan %s_%s: %s", session_type, horizon, res.status_code)
    except Exception as e:
        logging.error("Failed to trigger scan %s_%s: %s", session_type, horizon, e)

def trigger_delivery_volume_scan():
    """Run the delivery volume confluence scan over portfolio holdings."""
    def _run():
        try:
            from skills.delivery_volume import scan_and_alert_portfolio
            
            logging.info("Starting Delivery Volume Confluence Scan...")
            
            # Use requests to hit our local API instead of importing skills directly 
            # to avoid circular import issues in scheduler daemon
            portfolio = _api_get("/portfolio", timeout=30)
            holdings = portfolio.get("holdings", [])
            tickers = [h["ticker"] for h in holdings if "ticker" in h]
            
            if not tickers:
                logging.warning("No tickers found in portfolio for delivery volume scan")
                return
                
            scan_and_alert_portfolio(tickers)
        except Exception as e:
            logging.error("Failed to run delivery volume scan: %s", e)
            
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# ── LLM briefing engine ──────────────────────────────────────────────────────
def trigger_llm_brief(brief_type: str):
    """Fetch live data, ask Gemini Flash to write an intelligent brief, send to Telegram."""
    def _run():
        try:
            from llm import ask, build_market_context, earnings_watch_tickers, apply_earnings_guard, EARNINGS_TASK_LINE
        except ImportError as e:
            logging.error("LLM module not available: %s", e)
            return

        logging.info("Starting LLM brief: %s", brief_type)

        # Fetch live context data
        # Timeouts are generous because these calls hit live APIs (yfinance / Tradier)
        # and the opportunities scan can take 40-60s on a full watchlist.
        portfolio = _api_get("/portfolio",                           timeout=90)
        movers    = _api_get("/market/movers",                       timeout=45)
        fg        = _api_get("/market/fear-greed",                   timeout=20)
        alerts    = _api_get("/alerts?limit=5",                      timeout=20)
        opps      = _api_get("/opportunities?limit=8&session=auto",  timeout=90)
        earnings_tickers = earnings_watch_tickers(portfolio if isinstance(portfolio, dict) else {})
        earnings  = _api_get("/earnings/calendar?tickers=" + ",".join(earnings_tickers), timeout=60)

        api_data = {
            "portfolio":      portfolio,
            "market_indices": (movers.get("market_indices") if isinstance(movers, dict) else {}),
            "fear_greed":     fg,
            "alerts":         (alerts if isinstance(alerts, list) else alerts.get("alerts", []) if isinstance(alerts, dict) else []),
            "opportunities":  (opps.get("opportunities", []) if isinstance(opps, dict) else opps if isinstance(opps, list) else []),
            "earnings":       earnings if isinstance(earnings, dict) else {},
        }

        context = build_market_context(api_data)

        # Build the prompt for this brief type
        if brief_type == "premarket":
            task = (
                "It is pre-market (8:15 AM CST). Write a sharp pre-market brief covering:\n"
                "1. Market overnight context and key index levels\n"
                "2. Key risks for today\n"
                "3. Top 2-3 portfolio holdings to watch today\n"
                "4. Fear & Greed interpretation\n"
                f"{EARNINGS_TASK_LINE}\n"
                "Note: Distinguish strictly between Today's Change (%) and All-Time P&L (%). Do not invent stop losses if none are set.\n"
                "CRITICAL: Ground all prices, setups, and ideas strictly in the data above. NEVER invent tickers, price levels, or stop-losses from memory.\n"
                "Keep it under 350 words. Format with clear section headers."
            )
        elif brief_type == "midday":
            task = (
                "It is midday (12:00 PM CST). Write a concise midday market update covering:\n"
                "1. How the morning session went (indices, sentiment)\n"
                "2. Portfolio holdings today (use 'Today' change %, DO NOT confuse with all-time total P&L)\n"
                "3. Top 1-2 afternoon scalp or swing setups from the opportunity scan (if none, state 'No setups flagged')\n"
                "4. Any action needed (hold, trail stop, add, trim)\n"
                "CRITICAL: Ground all prices strictly in the data above. NEVER cite prices from pre-training memory.\n"
                "Keep it under 300 words.\n"
                f"{EARNINGS_TASK_LINE}"
            )
        elif brief_type == "close":
            task = (
                "Market is closed (4:05 PM CST). Write an end-of-day portfolio review:\n"
                "1. How the portfolio performed TODAY (use 'Today' change %, DO NOT report all-time loss as today's loss!)\n"
                "2. Any positions near stop-loss (if no stops are set in data, explicitly state 'No stop-loss configured')\n"
                "3. Top 2 overnight/next-day watchlist ideas from the scan (if none, state 'No setups flagged')\n"
                "4. One-sentence macro read for tomorrow\n"
                "5. Rebalancing suggestion if any position exceeds 10% concentration\n"
                "CRITICAL: Ground all prices strictly in the data above. NEVER cite prices from pre-training memory.\n"
                "Keep it under 350 words.\n"
                f"{EARNINGS_TASK_LINE}"
            )
        else:
            task = "Write a brief market summary based on the data provided."

        prompt = f"{context}\n\n---\nYOUR TASK:\n{task}"

        response = apply_earnings_guard(ask(prompt, max_tokens=8192), api_data)

        # Format and send
        header = {
            "premarket": "🌅 <b>FinClaw Pre-Market Brief</b>",
            "midday":    "☀️ <b>FinClaw Midday Update</b>",
            "close":     "🌆 <b>FinClaw Close Summary</b>",
        }.get(brief_type, "🦾 <b>FinClaw Brief</b>")

        # Telegram has 4096 char limit — truncate gracefully
        message = f"{header}\n\n{response}"
        if len(message) > 4000:
            message = message[:3980] + "\n\n<i>[truncated — see dashboard for full report]</i>"

        _send_telegram(message)
        logging.info("LLM brief sent: %s", brief_type)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# ── Main scheduler loop ──────────────────────────────────────────────────────
def run_scheduler():
    logging.info("Starting FinClaw Scheduler Daemon (24/7 Qwen-Powered Intelligence)...")

    last_intraday        = None
    last_sentiment       = None
    last_premarket_day   = None
    last_midday_day      = None
    last_close_day       = None
    last_delivery_10_day = None
    last_delivery_14_day = None
    last_afterhours      = None
    last_overnight_news  = None
    last_earnings_preview = None
    last_premarket_catalyst = None
    last_weekend_research = None
    last_trading_plan = None
    last_ml_retrain = None
    last_smart_money = None
    last_daily_journal = None
    last_weekly_review = None
    last_volatility_check = None

    while True:
        # Enforce CST timezone for all scheduling logic
        cst_tz = pytz.timezone('America/Chicago')
        now = datetime.now(cst_tz)

        # ── OVERNIGHT INTELLIGENCE (2:00-7:00 AM) ──────────────────────────
        # Run 7 days a week
        today_str = now.strftime("%Y-%m-%d")
        
        # 02:00 CST — Overnight News Digest
        if now.hour == 2 and now.minute == 0 and last_overnight_news != today_str:
            try:
                digest = overnight_news_digest()
                if digest:
                    _send_telegram(f"🌙 <b>Overnight News Digest</b>\n\n{digest}")
                last_overnight_news = today_str
            except Exception as e:
                logging.error(f"Overnight news digest failed: {e}")
        
        # 06:00 CST — Pre-Market Catalyst Scan
        if now.hour == 6 and now.minute == 0 and last_premarket_catalyst != today_str:
            try:
                catalyst_report = premarket_catalyst_scan()
                if catalyst_report:
                    _send_telegram(f"⚡ <b>Pre-Market Catalysts</b>\n\n{catalyst_report}")
                last_premarket_catalyst = today_str
            except Exception as e:
                logging.error(f"Pre-market catalyst scan failed: {e}")

        # ── WEEKDAY MARKET OPERATIONS ──────────────────────────────────────
        # Only run on weekdays (Mon=0 … Fri=4)
        if now.weekday() <= 4:

            # ── 08:15 CST — Pre-market LLM brief ──────────────────────────
            if now.hour == 8 and now.minute == 15 and last_premarket_day != today_str:
                trigger_llm_brief("premarket")
                last_premarket_day = today_str

            # ── 08:30–16:00 CST — Intraday scalp scan (algorithmic, every 15 min) ──
            if 8 <= now.hour < 16:
                if (now.hour == 8 and now.minute >= 30) or now.hour >= 9:
                    if now.minute % 15 == 0:
                        minute_key = f"{now.hour}:{now.minute}"
                        if last_intraday != minute_key:
                            trigger_scan("regular", "scalp")
                            last_intraday = minute_key
                        
                        # News sentiment analysis (every 15 min during market hours)
                        if last_sentiment != minute_key:
                            try:
                                sentiment_alert = get_sentiment_alerts()
                                if sentiment_alert:
                                    _send_telegram(sentiment_alert)
                                last_sentiment = minute_key
                            except Exception as e:
                                logging.error(f"Sentiment scan failed: {e}")

            # ── 10:00 CST — Delivery Volume Confluence Check ────────────────
            if now.hour == 10 and now.minute == 0 and last_delivery_10_day != today_str:
                trigger_delivery_volume_scan()
                last_delivery_10_day = today_str

            # ── 12:00 CST — Midday LLM swing analysis ─────────────────────
            if now.hour == 12 and now.minute == 0 and last_midday_day != today_str:
                trigger_llm_brief("midday")
                last_midday_day = today_str
                
            # ── 14:00 CST — Delivery Volume Confluence Check ────────────────
            if now.hour == 14 and now.minute == 0 and last_delivery_14_day != today_str:
                trigger_delivery_volume_scan()
                last_delivery_14_day = today_str

            # ── 16:05 CST — Close summary LLM brief ───────────────────────
            if now.hour == 16 and now.minute == 5 and last_close_day != today_str:
                trigger_llm_brief("close")
                last_close_day = today_str
            
            # ── 16:30 CST — Daily Trade Journal ───────────────────────────
            if now.hour == 16 and now.minute == 30 and last_daily_journal != today_str:
                try:
                    journal = generate_daily_journal()
                    if journal:
                        _send_telegram(f"📓 <b>Daily Trade Journal</b>\n\n{journal}")
                    last_daily_journal = today_str
                except Exception as e:
                    logging.error(f"Daily journal failed: {e}")
            
            # ── 18:00 CST — Smart Money Tracker ───────────────────────────
            if now.hour == 18 and now.minute == 0 and last_smart_money != today_str:
                try:
                    smart_money = generate_smart_money_report()
                    if smart_money:
                        _send_telegram(f"💰 <b>Smart Money Report</b>\n\n{smart_money}")
                    last_smart_money = today_str
                except Exception as e:
                    logging.error(f"Smart money tracker failed: {e}")

        # ── AFTER-HOURS MONITORING (4:00-8:00 PM, weekdays) ─────────────────
        if now.weekday() <= 4 and 16 <= now.hour < 20:
            if now.minute % 30 == 0:
                minute_key = f"{now.hour}:{now.minute}"
                if last_afterhours != minute_key:
                    try:
                        ah_alert = afterhours_monitoring()
                        if ah_alert:
                            _send_telegram(f"🌆 <b>After-Hours Alert</b>\n\n{ah_alert}")
                        last_afterhours = minute_key
                    except Exception as e:
                        logging.error(f"After-hours monitoring failed: {e}")

        # ── WEEKEND INTELLIGENCE ─────────────────────────────────────────────
        # Saturday operations
        if now.weekday() == 5:  # Saturday
            # 09:00 — Weekend Deep Research (all watchlist stocks)
            if now.hour == 9 and now.minute == 0 and last_weekend_research != today_str:
                try:
                    research_summary = weekend_deep_research_batch()
                    if research_summary:
                        _send_telegram(f"📊 <b>Weekend Research Complete</b>\n\n{research_summary}")
                    last_weekend_research = today_str
                except Exception as e:
                    logging.error(f"Weekend research failed: {e}")
            
            # 23:00 — Weekly ML Model Retraining
            if now.hour == 23 and now.minute == 0 and last_ml_retrain != today_str:
                try:
                    logging.info("Starting weekly ML model retraining...")
                    results = run_weekly_retrain()
                    report = generate_retrain_report(results)
                    _send_telegram(report)
                    last_ml_retrain = today_str
                except Exception as e:
                    logging.error(f"ML retraining failed: {e}")
                    _send_telegram(f"⚠️ ML Model Retraining Failed\n\nError: {str(e)}")

        # Sunday operations
        if now.weekday() == 6:  # Sunday
            # 15:00 — Weekly Trading Plan
            if now.hour == 15 and now.minute == 0 and last_trading_plan != today_str:
                try:
                    plan = weekly_trading_plan()
                    if plan:
                        _send_telegram(f"📋 <b>Weekly Trading Plan</b>\n\n{plan}")
                    last_trading_plan = today_str
                except Exception as e:
                    logging.error(f"Weekly trading plan failed: {e}")
            
            # 16:00 — Weekly Performance Review
            if now.hour == 16 and now.minute == 0 and last_weekly_review != today_str:
                try:
                    review = generate_weekly_performance_review()
                    if review:
                        _send_telegram(f"📊 <b>Weekly Performance Review</b>\n\n{review}")
                    last_weekly_review = today_str
                except Exception as e:
                    logging.error(f"Weekly review failed: {e}")

        # ── VOLATILITY REGIME DETECTION (Every 4 hours, 24/7) ────────────
        if now.hour % 4 == 0 and now.minute == 0:
            hour_key = f"{now.hour}"
            if last_volatility_check != hour_key:
                try:
                    regime_alert = detect_volatility_regime()
                    if regime_alert:
                        _send_telegram(regime_alert)
                    last_volatility_check = hour_key
                except Exception as e:
                    logging.error(f"Volatility regime detection failed: {e}")

        time.sleep(30)  # Heartbeat — check every 30 seconds


if __name__ == "__main__":
    run_scheduler()
