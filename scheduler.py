"""
FinClaw Scheduler — Algorithmic + LLM-Powered Market Intelligence
=================================================================
Two layers run in parallel every market day:

  ALGORITHMIC (zero cost, always on):
  - 08:30–16:00 CST  Every 15 min  Intraday scalp scan  (server.py math engine)

  LLM-POWERED (Gemini Flash, ~$0.003/day):
  - 08:15 CST  Pre-market LLM brief
  - 12:00 CST  Midday LLM swing analysis
  - 16:05 CST  Close summary + portfolio review
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
            from llm import ask, build_market_context
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

        api_data = {
            "portfolio":      portfolio,
            "market_indices": (movers.get("market_indices") if isinstance(movers, dict) else {}),
            "fear_greed":     fg,
            "alerts":         (alerts if isinstance(alerts, list) else alerts.get("alerts", []) if isinstance(alerts, dict) else []),
            "opportunities":  (opps.get("opportunities", []) if isinstance(opps, dict) else opps if isinstance(opps, list) else []),
        }

        context = build_market_context(api_data)

        # Build the prompt for this brief type
        if brief_type == "premarket":
            task = (
                "It is pre-market (8:15 AM CST). Write a sharp pre-market brief covering:\n"
                "1. Market overnight context and key index levels\n"
                "2. Key risks for today\n"
                "3. Top 2-3 portfolio holdings to watch today with entry/exit levels\n"
                "4. Fear & Greed interpretation\n"
                "Keep it under 350 words. Format with clear section headers."
            )
        elif brief_type == "midday":
            task = (
                "It is midday (12:00 PM CST). Write a concise midday market update covering:\n"
                "1. How the morning session went (indices, sentiment)\n"
                "2. Portfolio holdings that need attention (up big, down big, near stop loss)\n"
                "3. Top 1-2 afternoon scalp or swing setups from the opportunity scan\n"
                "4. Any action needed (hold, trail stop, add, trim)\n"
                "Keep it under 300 words."
            )
        elif brief_type == "close":
            task = (
                "Market is closed (4:05 PM CST). Write an end-of-day portfolio review:\n"
                "1. How the portfolio performed today (winners, losers)\n"
                "2. Any positions near their stop-loss that need monitoring overnight\n"
                "3. Top 2 overnight/next-day watchlist ideas from the scan\n"
                "4. One-sentence macro read for tomorrow\n"
                "5. Rebalancing suggestion if any position exceeds 8% of portfolio\n"
                "Keep it under 400 words."
            )
        else:
            task = "Write a brief market summary based on the data provided."

        prompt = f"{context}\n\n---\nYOUR TASK:\n{task}"

        response = ask(prompt, max_tokens=8192)

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
    logging.info("Starting FinClaw Scheduler Daemon (Algorithmic + LLM)...")

    last_intraday        = None
    last_premarket_day   = None
    last_midday_day      = None
    last_close_day       = None
    last_delivery_10_day = None
    last_delivery_14_day = None

    while True:
        # Enforce CST timezone for all scheduling logic
        cst_tz = pytz.timezone('America/Chicago')
        now = datetime.now(cst_tz)

        # Only run on weekdays (Mon=0 … Fri=4)
        if now.weekday() <= 4:
            today_str = now.strftime("%Y-%m-%d")

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

        time.sleep(30)  # Heartbeat — check every 30 seconds


if __name__ == "__main__":
    run_scheduler()
