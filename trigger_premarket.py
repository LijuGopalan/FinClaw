#!/usr/bin/env python3
"""
One-shot Pre-Market Brief Trigger
Runs the LLM pre-market analysis directly (no API dependency).
"""

import os, sys, logging, requests

# Add skills to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] premarket: %(message)s",
)

API_BASE = "http://127.0.0.1:5050/api"

def _api_get(path, timeout=30):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.warning("API GET %s failed: %s — using empty dict", path, e)
        return {}


def _send_telegram(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logging.warning("Telegram not configured — printing to stdout instead")
        print("\n" + "="*60)
        print(message)
        print("="*60)
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.ok:
            logging.info("✅ Telegram message sent (msg_id=%s)", resp.json().get("result", {}).get("message_id"))
        else:
            logging.error("Telegram error: %s", resp.text)
    except Exception as e:
        logging.error("Telegram send failed: %s", e)


def run_premarket_brief():
    try:
        from llm import ask, build_market_context
    except ImportError as e:
        logging.error("Cannot import LLM module: %s", e)
        sys.exit(1)

    logging.info("🌅 Triggering Pre-Market Analysis...")

    # Gather live context — gracefully degrade if API unavailable
    portfolio = _api_get("/portfolio", timeout=60)
    movers    = _api_get("/market/movers", timeout=30)
    fg        = _api_get("/market/fear-greed", timeout=15)
    alerts    = _api_get("/alerts?limit=5", timeout=15)
    opps      = _api_get("/opportunities?limit=8&session=auto", timeout=30)

    api_data = {
        "portfolio":      portfolio,
        "market_indices": (movers.get("market_indices") or {}),
        "fear_greed":     fg,
        "alerts":         (alerts.get("alerts") or []),
        "opportunities":  (opps.get("opportunities") or []),
    }

    context = build_market_context(api_data)

    task = (
        "It is pre-market (8:15 AM CST). Write a sharp pre-market brief covering:\n"
        "1. Market overnight context and key index levels\n"
        "2. Key risks for today\n"
        "3. Top 2-3 portfolio holdings to watch today with entry/exit levels\n"
        "4. Fear & Greed interpretation\n"
        "Keep it under 350 words. Format with clear section headers."
    )

    prompt = f"{context}\n\n---\nYOUR TASK:\n{task}"

    logging.info("Sending prompt to LLM...")
    response = ask(prompt, max_tokens=1500)

    header = "🌅 <b>FinClaw Pre-Market Brief</b>"
    message = f"{header}\n\n{response}"
    if len(message) > 4000:
        message = message[:3980] + "\n\n<i>[truncated — see dashboard for full report]</i>"

    logging.info("Sending to Telegram...")
    _send_telegram(message)
    logging.info("✅ Pre-market brief complete.")


if __name__ == "__main__":
    run_premarket_brief()
