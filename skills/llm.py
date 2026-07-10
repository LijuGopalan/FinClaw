"""
FinClaw LLM Layer — Gemini Flash Wrapper with Retry Logic
==========================================================
Shared module used by scheduler.py (briefings) and telegram_bot.py (chat).
All LLM calls route through here so retry logic is centralised.

Model: gemini-2.0-flash-lite  (cheapest, ~$0.00015/1K tokens output)
Retry: 3 attempts with exponential backoff (2s → 4s → 8s)
"""

import os
import time
import logging

import google.genai as genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("finclaw.llm")

_API_KEY = os.getenv("GOOGLE_API_KEY")
_MODEL_NAME = "gemini-2.5-flash"
_MAX_RETRIES = 3
_RETRY_BASE  = 2   # seconds
_REQUEST_TIMEOUT = 150  # seconds

client = None
if _API_KEY:
    client = genai.Client(api_key=_API_KEY)
else:
    logger.warning("GOOGLE_API_KEY not set — LLM features will be disabled.")


def _load_soul() -> str:
    """Load the SOUL.md personality file as system prompt."""
    soul_path = os.path.join(os.path.dirname(__file__), "..", "SOUL.md")
    try:
        with open(soul_path, "r") as f:
            return f.read()
    except Exception:
        return (
            "You are FinClaw, a precision AI financial assistant. "
            "Be sharp, data-driven, and concise. Never fabricate numbers."
        )


SOUL_PROMPT = _load_soul()


def ask(prompt: str, system: str = None, max_tokens: int = 2048) -> str:
    """
    Send a prompt to Gemini Flash and return the response text.
    Retries up to _MAX_RETRIES times on transient network errors.

    Args:
        prompt:     The user/task prompt.
        system:     Override system prompt (defaults to SOUL.md).
        max_tokens: Maximum output tokens.

    Returns:
        The model's text response, or an error string on permanent failure.
    """
    if not client:
        return "⚠️ LLM not configured — set GOOGLE_API_KEY in .env"

    sys_prompt = system or SOUL_PROMPT

    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    max_output_tokens=max_tokens,
                    temperature=0.15,
                    # Hard HTTP timeout — prevents indefinite hang on slow/idle model
                    # Moved inside GenerateContentConfig for google-genai >= 1.0
                    http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT * 1000),
                ),
            )
            return response.text
        except Exception as e:
            last_error = e
            wait = _RETRY_BASE ** attempt
            logger.warning(
                "Gemini attempt %d/%d failed (%s). Retrying in %ds…",
                attempt, _MAX_RETRIES, e, wait,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(wait)

    logger.error("Gemini permanently failed after %d attempts: %s", _MAX_RETRIES, last_error)
    return f"⚠️ LLM temporarily unavailable ({last_error})"


def build_market_context(api_data: dict) -> str:
    """
    Convert live FinClaw API data into a concise text context block
    that can be injected into LLM prompts.
    """
    lines = ["=== LIVE MARKET DATA (as of now) ==="]

    # Portfolio
    portfolio = api_data.get("portfolio", {})
    summary = portfolio.get("summary", {})
    if summary:
        lines.append(
            f"\nPORTFOLIO SUMMARY:\n"
            f"  Total Value:  ${summary.get('total_value', 0):,.2f}\n"
            f"  Total P&L:    ${summary.get('total_gain_loss', 0):+,.2f} "
            f"({summary.get('total_return_pct', 0):+.2f}%)\n"
            f"  Positions:    {summary.get('position_count', 0)}\n"
            f"  Cash:         ${summary.get('cash', 0):,.2f}"
        )
        holdings = portfolio.get("holdings", [])
        if holdings:
            lines.append("\nHOLDINGS:")
            for h in holdings:
                g = h.get("gain_loss", 0)
                gp = h.get("gain_loss_pct", 0)
                lines.append(
                    f"  {h['ticker']:6s} | Price: ${h.get('current_price', 0):.2f} | "
                    f"P&L: ${g:+,.0f} ({gp:+.1f}%) | Shares: {h.get('shares', 0)}"
                )

    # Market indices
    indices = api_data.get("market_indices", {})
    if indices:
        lines.append("\nMARKET INDICES:")
        for sym, d in indices.items():
            chg = d.get("change_pct")
            chg = chg if chg is not None else 0
            price = d.get("price")
            price = price if price is not None else 0
            lines.append(f"  {sym:5s} | ${price:.2f} | {chg:+.2f}%")

    # Fear & Greed
    fg = api_data.get("fear_greed", {})
    if fg and not fg.get("error"):
        lines.append(f"\nFEAR & GREED INDEX: {fg.get('value', '—')} — {fg.get('label', '')}")

    # Top opportunities
    opps = api_data.get("opportunities", [])
    if opps:
        lines.append("\nTOP OPPORTUNITIES (algorithmic scan):")
        for o in opps[:5]:
            lines.append(
                f"  {o.get('ticker'):6s} | Score: {o.get('score')} | "
                f"Action: {o.get('action')} | ${o.get('price', 0):.2f}"
            )

    # Latest alerts
    alerts = api_data.get("alerts", [])
    if alerts:
        lines.append("\nRECENT ALERTS:")
        for a in alerts[:3]:
            ts = (a.get("timestamp") or "")[:16].replace("T", " ")
            lines.append(f"  [{ts}] {a.get('title', '')}")

    # User requested quotes
    user_quotes = api_data.get("user_quotes", {})
    if user_quotes:
        lines.append("\nUSER REQUESTED DATA:")
        for t, q in user_quotes.items():
            if "error" in q:
                lines.append(f"  {t:6s} | Data unavailable")
            else:
                lines.append(f"  {t:6s} | ${q.get('price', 0):.2f} | {q.get('change_pct', 0):+.2f}% | Vol: {q.get('volume', 0):,}")

    lines.append("\n=== END MARKET DATA ===")
    return "\n".join(lines)
