"""
FinClaw LLM Layer — Hybrid Local Qwen 2.5 + Cloud Gemini Flash
==============================================================
Shared module used by scheduler.py (briefings) and telegram_bot.py (chat).

Priority:
1. Local Qwen 2.5 (Alibaba) via Ollama (100% private, zero cost, runs on Apple M4)
2. Cloud Google Gemini Flash as resilient fallback
"""

import os
import re
import time
import logging
import requests
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("finclaw.llm")

# Local LLM settings (Qwen 2.5 via Ollama)
USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "true").lower() in ("true", "1", "yes")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")

# Cloud Gemini settings
_API_KEY = os.getenv("GOOGLE_API_KEY")
_MODEL_NAME = "gemini-2.5-flash"
_MAX_RETRIES = 3
_RETRY_BASE  = 2   # seconds
_REQUEST_TIMEOUT = 120  # seconds

client = None
if _API_KEY:
    try:
        import google.genai as genai
        client = genai.Client(api_key=_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize Google GenAI client: {e}")
else:
    logger.warning("GOOGLE_API_KEY not set — Gemini cloud fallback will be disabled.")


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

# Names the pre-market brief is most likely to invent if the calendar is missing.
DEFAULT_EARNINGS_TICKERS = ["AAPL", "NVDA", "MSFT", "AMZN", "TSLA", "META", "GOOGL"]

EARNINGS_TASK_LINE = (
    "Earnings: use only the REPORTING TODAY line in the live data. "
    "If it says none, say that none of the covered companies report today. "
    "Never name a company as reporting today from memory. "
    "An upcoming date is not today's report."
)

_EARNINGS_TODAY_CLAIM = re.compile(
    r"(scheduled to report|"
    r"report(?:s|ing)?\s+(?:earnings|results).{0,40}\btoday\b|"
    r"\btoday\b.{0,50}report(?:s|ing)?\s+(?:earnings|results)|"
    r"report(?:s|ing)?\s+(?:earnings|results)\s+(?:this morning|after the (?:close|bell)|before the (?:open|bell))|"
    r"earnings\s+(?:are|is)\s+(?:due|scheduled).{0,30}\btoday\b)",
    re.IGNORECASE,
)
_EARNINGS_NEGATION = re.compile(r"\b(no|none|not|n't|without|nobody|no one|do not)\b", re.IGNORECASE)
_TICKER_IN_PARENS = re.compile(r"\(([A-Z]{1,5})\)")


def earnings_watch_tickers(portfolio: dict = None, extra: list = None) -> list:
    """Portfolio holdings plus the mega-caps the brief tends to guess about."""
    seen = []
    holdings = (portfolio or {}).get("holdings") or []
    for holding in holdings:
        ticker = str(holding.get("ticker") or "").upper().strip()
        if ticker and ticker not in seen:
            seen.append(ticker)
    for ticker in list(extra or []) + DEFAULT_EARNINGS_TICKERS:
        ticker = str(ticker or "").upper().strip()
        if ticker and ticker not in seen:
            seen.append(ticker)
    return seen


def _market_today(api_data: dict) -> date:
    raw = (api_data or {}).get("as_of")
    if raw:
        return date.fromisoformat(str(raw)[:10])
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return datetime.utcnow().date()


def _coerce_context_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _entry_dates(entry: dict) -> list:
    raw = entry.get("earnings_dates")
    if not raw:
        raw = entry.get("earnings_date")
    if raw in (None, "", "Unknown"):
        return []
    values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    dates = []
    for value in values:
        parsed = _coerce_context_date(value)
        if parsed and parsed not in dates:
            dates.append(parsed)
    return dates


def _earnings_entries(api_data: dict):
    """None when the calendar was not fetched or failed. [] when it returned nothing."""
    if not isinstance(api_data, dict) or "earnings" not in api_data:
        return None
    raw = api_data.get("earnings")
    if not isinstance(raw, dict):
        return None
    rows = raw.get("earnings")
    if not isinstance(rows, list):
        return None
    if raw.get("error") and not rows:
        return None
    return rows


def classify_earnings(entries, as_of: date) -> dict:
    """Split calendar rows into confirmed today / upcoming / already reported."""
    reporting = []
    upcoming = []
    already = []
    unconfirmed = []
    for entry in entries or []:
        ticker = str(entry.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        dates = _entry_dates(entry)
        if not dates:
            unconfirmed.append(ticker)
            continue
        future = [d for d in dates if d > as_of]
        on_today = [d for d in dates if d == as_of]
        past = [d for d in dates if d < as_of]
        # A single date equal to today is the only confirmed "reports today" case.
        # A window that merely includes today is an estimate, not a scheduled print.
        if len(set(dates)) == 1 and on_today:
            reporting.append(ticker)
        elif on_today and future:
            unconfirmed.append(
                f"{ticker} estimated window {min(dates).isoformat()} to {max(dates).isoformat()} (not confirmed for today)"
            )
        elif future:
            upcoming.append((min(future), ticker, max(future)))
        elif past:
            already.append((max(past), ticker))
        else:
            unconfirmed.append(ticker)
    upcoming.sort(key=lambda item: (item[0], item[1]))
    already.sort(key=lambda item: item[0], reverse=True)
    return {
        "reporting_today": reporting,
        "upcoming": upcoming,
        "already": already,
        "unconfirmed": unconfirmed,
    }


def format_earnings_block(entries, as_of: date) -> str:
    """Authoritative earnings section for brief prompts."""
    rule = (
        "  RULE: Name a company as reporting earnings today only if it is on REPORTING TODAY. "
        "If that line says none, do not say anyone reports today."
    )
    if entries is None:
        return (
            "EARNINGS CALENDAR: unavailable\n"
            "  REPORTING TODAY: none\n"
            + rule
        )
    classified = classify_earnings(entries, as_of)
    lines = [
        "EARNINGS CALENDAR (Yahoo estimate; authoritative for this brief):",
        "  REPORTING TODAY: " + (", ".join(classified["reporting_today"]) or "none"),
    ]
    if classified["upcoming"]:
        lines.append("  UPCOMING (not today):")
        for start, ticker, end in classified["upcoming"][:12]:
            if start != end:
                lines.append(f"    {ticker} estimated window {start.isoformat()} to {end.isoformat()}")
            else:
                lines.append(f"    {ticker} {start.isoformat()}")
    else:
        lines.append("  UPCOMING (not today): none listed")
    if classified["already"]:
        lines.append("  ALREADY REPORTED (not today):")
        for when, ticker in classified["already"][:8]:
            lines.append(f"    {ticker} last listed {when.isoformat()}")
    if classified["unconfirmed"]:
        lines.append("  UNCONFIRMED:")
        for item in classified["unconfirmed"][:8]:
            lines.append(f"    {item}")
    lines.append(rule)
    return "\n".join(lines)


def apply_earnings_guard(text: str, api_data: dict) -> str:
    """
    Drop sentences that say someone reports today when the calendar disagrees.

    The brief model has invented AAPL/MSFT earnings days that were not in the
    data. The calendar line is the constraint; this removes a sentence that
    violates it instead of shipping the claim.
    """
    if not text:
        return text
    as_of = _market_today(api_data or {})
    entries = _earnings_entries(api_data or {})
    classified = classify_earnings(entries or [], as_of)
    reporting = set(classified["reporting_today"])
    known = set(reporting)
    known.update(ticker for _, ticker, _ in classified["upcoming"])
    known.update(ticker for _, ticker in classified["already"])

    kept = []
    removed = False
    chunks = re.split(r"(\n+)", text)
    for chunk in chunks:
        if not chunk or chunk.startswith("\n"):
            kept.append(chunk)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", chunk)
        kept_sentences = []
        for sentence in sentences:
            if not sentence:
                continue
            if _sentence_claims_earnings_today(sentence, reporting, known):
                removed = True
                continue
            kept_sentences.append(sentence)
        kept.append(" ".join(kept_sentences))

    cleaned = "".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not removed:
        return cleaned
    if reporting:
        note = "Earnings check: only " + ", ".join(sorted(reporting)) + " report today on the calendar."
    else:
        note = "Earnings check: no covered company reports today."
        if classified["upcoming"]:
            bits = []
            for start, ticker, end in classified["upcoming"][:4]:
                when = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
                bits.append(f"{ticker} {when}")
            note += " Next calendar dates: " + ", ".join(bits) + "."
    return (cleaned + "\n\n" + note).strip()


def _sentence_claims_earnings_today(sentence: str, reporting: set, known: set) -> bool:
    if not _EARNINGS_TODAY_CLAIM.search(sentence):
        return False
    if _EARNINGS_NEGATION.search(sentence):
        return False
    mentioned = set(_TICKER_IN_PARENS.findall(sentence))
    for token in re.findall(r"\b[A-Z]{1,5}\b", sentence):
        if token in known or token in reporting:
            mentioned.add(token)
    if mentioned & reporting:
        # Keep the sentence when every named covered ticker really reports today.
        outsiders = (mentioned & known) - reporting
        return bool(outsiders)
    return True


def _ask_local_qwen(prompt: str, system: str, max_tokens: int):
    """Query local Qwen 2.5 model via Ollama running on Apple Silicon."""
    if not USE_LOCAL_LLM:
        return None
    try:
        # Increase token limit to 4096 for market briefs and research reports
        local_predict = min(max_tokens, 4096) if max_tokens else 2048
        payload = {
            "model": LOCAL_LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.15,
                "num_predict": local_predict
            }
        }
        resp = requests.post(
            f"{LOCAL_LLM_URL}/api/chat",
            json=payload,
            timeout=60
        )
        if resp.status_code == 200:
            content = resp.json().get("message", {}).get("content", "").strip()
            if content:
                logger.info(f"Generated response using Local Model: {LOCAL_LLM_MODEL}")
                return content
        logger.warning(f"Local Ollama returned status {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        logger.warning(f"Local Ollama query failed ({e}) — falling back to Gemini")
    return None


def _extract_gemini_text(response):
    """
    Safely extract text from a Gemini response object.

    gemini-2.5-flash is a *thinking* model — it spends tokens on internal
    reasoning before writing the visible reply. If max_output_tokens is too
    small the model hits the limit during the thinking phase and returns a
    candidate whose content.parts is None, making response.text return None.
    This helper walks the parts list directly so we never silently swallow
    an empty response.
    """
    # Fast path: the SDK already assembled the text for us.
    if response.text is not None:
        return response.text

    # Slow path: reconstruct from parts (handles MAX_TOKENS on thinking models).
    for candidate in response.candidates or []:
        parts = (candidate.content.parts or []) if candidate.content else []
        assembled = "".join(
            part.text for part in parts if getattr(part, "text", None)
        )
        if assembled:
            return assembled

        finish = getattr(candidate, "finish_reason", None)
        logger.warning(
            "Gemini candidate had no text parts (finish_reason=%s). "
            "Consider raising max_output_tokens so the thinking model has "
            "room to write its reply.",
            finish,
        )

    return None


def _ask_gemini(prompt: str, system: str, max_tokens: int) -> str:
    """Query Google Gemini Flash cloud model."""
    if not client:
        return "⚠️ Cloud LLM not configured — set GOOGLE_API_KEY in .env"

    from google.genai import types

    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=0.15,
                    http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT * 1000),
                ),
            )
            text = _extract_gemini_text(response)
            if text is not None:
                logger.info("Generated response using Cloud Gemini Flash")
                return text
            # Empty reply — treat as a soft failure and retry.
            last_error = ValueError(
                f"Empty Gemini response (finish_reason="
                f"{response.candidates[0].finish_reason if response.candidates else 'unknown'})"
            )
            logger.warning(
                "Gemini attempt %d/%d returned empty text (%s). Retrying…",
                attempt, _MAX_RETRIES, last_error,
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "Gemini attempt %d/%d failed (%s). Retrying in %ds…",
                attempt, _MAX_RETRIES, e, _RETRY_BASE ** attempt,
            )
        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_BASE ** attempt)

    logger.error("Gemini permanently failed after %d attempts: %s", _MAX_RETRIES, last_error)
    return f"⚠️ LLM temporarily unavailable ({last_error})"


def ask(prompt: str, system: str = None, max_tokens: int = 8192) -> str:
    """
    Send a prompt to the AI layer.
    Tries Local Qwen 2.5 first (100% private on Apple M4),
    then seamlessly falls back to Google Gemini Flash.

    max_tokens defaults to 8192 — gemini-2.5-flash is a thinking model that
    consumes tokens for internal reasoning before writing its reply; a default
    of 2048 was too small and caused response.text to return None.
    """
    sys_prompt = system or SOUL_PROMPT

    # 1. Try local Qwen 2.5 via Ollama
    local_response = _ask_local_qwen(prompt, sys_prompt, max_tokens)
    if local_response:
        return local_response

    # 2. Resilient Cloud Fallback (Gemini)
    return _ask_gemini(prompt, sys_prompt, max_tokens)


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
            f"  Total Value:             ${summary.get('total_value', 0):,.2f}\n"
            f"  Total P&L (All-Time):    ${summary.get('total_gain_loss', 0):+,.2f} ({summary.get('total_return_pct', 0):+.2f}%)\n"
            f"  Positions:               {summary.get('position_count', 0)}\n"
            f"  Cash:                    ${summary.get('cash', 0):,.2f}"
        )
        holdings = portfolio.get("holdings", [])
        if holdings:
            lines.append("\nHOLDINGS (Distinguish carefully between Today's Change and All-Time P&L):")
            for h in holdings:
                g = h.get("gain_loss", 0)
                gp = h.get("gain_loss_pct", 0)
                today_chg = h.get("change_today")
                today_str = f"Today: {today_chg:+.2f}%" if today_chg is not None else "Today: N/A"
                stop_str = f"Stop: ${h.get('stop_loss')}" if h.get("stop_loss") else "Stop: None set"
                lines.append(
                    f"  {h['ticker']:6s} | Current Price: ${h.get('current_price', 0):.2f} | "
                    f"{today_str} | Total All-Time P&L: ${g:+,.0f} ({gp:+.1f}%) | "
                    f"Cost Basis: ${h.get('avg_cost', 0):.2f} | {stop_str}"
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

    # Earnings — the only source the brief may use for "reports today"
    lines.append("\n" + format_earnings_block(_earnings_entries(api_data), _market_today(api_data)))

    # Top opportunities
    opps = api_data.get("opportunities", [])
    if opps:
        lines.append("\nTOP OPPORTUNITIES (Live algorithmic scan from Charles Schwab):")
        for o in opps[:5]:
            t = o.get("ticker", "")
            sc = o.get("score", 0)
            act = o.get("action", "")
            pr = o.get("price", 0)
            el = o.get("entry_low")
            eh = o.get("entry_high")
            tp = o.get("target_price")
            sl = o.get("stop_loss")
            rr = o.get("risk_reward")
            th = o.get("thesis", "")
            
            entry_str = f"${el:.2f}–${eh:.2f}" if el and eh else "Market"
            target_str = f"${tp:.2f}" if tp else "N/A"
            stop_str = f"${sl:.2f}" if sl else "N/A"
            rr_str = f"R/R: {rr}:1" if rr is not None else ""
            
            lines.append(
                f"  Ticker: ${t} | Action: {act} | Score: {sc} | Current Price: ${pr:.2f} | "
                f"Entry Zone: {entry_str} | Target: {target_str} | Stop-Loss: {stop_str} | {rr_str}"
            )
            if th:
                lines.append(f"    Thesis: {th}")
    else:
        lines.append(
            "\nTOP OPPORTUNITIES:\n"
            "  None currently flagged by the algorithmic scan.\n"
            "  CRITICAL RULE: DO NOT invent trade setups or make up fake stock prices. State clearly that no setups qualify right now."
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
