"""
FinClaw Telegram Bot — Interactive Command + LLM Chat Handler
=============================================================
Two modes:
  1. /commands — fast data lookups (no LLM cost)
  2. Plain text — routed to Gemini Flash with live market context

Commands:
  /start     — Welcome message
  /help      — List all commands
  /scan      — Trigger an intraday scalp scan now
  /portfolio — Show portfolio summary
  /alerts    — Show latest alerts
  /status    — Show server health
"""

import os
import sys
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] telegram_bot: %(message)s",
    filename="server.log",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = "http://localhost:5055/api"


def _api(path, method="GET", json=None, timeout=30):
    """Helper to call the local FinClaw API."""
    try:
        if method == "POST":
            r = requests.post(f"{API_BASE}{path}", json=json, timeout=timeout)
        else:
            r = requests.get(f"{API_BASE}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _fmt_change(val):
    if val is None:
        return "—"
    sign = "▲" if val >= 0 else "▼"
    return f"{sign} {abs(val):.2f}%"


# ============================================================
# /start
# ============================================================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🦾 <b>FinClaw Bot Active</b>\n\n"
        "I can give you live market data right here in Telegram.\n\n"
        "Use /help to see all available commands.",
        parse_mode="HTML",
    )


# ============================================================
# /help
# ============================================================
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🦾 <b>FinClaw Commands</b>\n\n"
        "🧠 <b>AI & Institutional Research:</b>\n"
        "/analyze &lt;ticker&gt; — Institutional Deep-Dive Research Memo (via Qwen 2.5)\n"
        "/redteam &lt;ticker&gt; — Adversarial Risk Audit to catch bull traps (via Qwen 2.5)\n\n"
        "📈 <b>Market & Screener Scans:</b>\n"
        "/scan — Run an intraday scalp scan now\n"
        "/delivery — Run delivery volume confluence scan now\n"
        "/portfolio — Your portfolio P&amp;L summary\n"
        "/alerts — Last 5 market alerts\n"
        "/status — Server &amp; scheduler health\n"
        "/insiders &lt;ticker&gt; — Show recent insider trading\n"
        "/feargreed — Show Fear &amp; Greed Index\n"
        "/movers — Show today's market movers\n"
        "/sectors — Show sector rotation performance\n"
        "/news &lt;ticker&gt; — Show latest news for a ticker\n"
        "/restart — Hard restart all FinClaw background daemons\n"
        "/help — This message",
        parse_mode="HTML",
    )


# ============================================================
# /restart
# ============================================================
async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 <b>Initiating full stack restart...</b>\n"
        "I will be offline for a few seconds while I kill and restart all background processes.",
        parse_mode="HTML",
    )
    import subprocess
    cmd = """
    sleep 2
    pkill -9 -f "python.*server.py" || true
    pkill -9 -f "python.*scheduler.py" || true
    pkill -9 -f "python.*telegram_bot.py" || true
    ./start.sh
    """
    subprocess.Popen(cmd, shell=True, cwd="/Users/adgroup/.gemini/antigravity/scratch/openclaw-financial-assistant", start_new_session=True)

# ============================================================
# /status
# ============================================================
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Checking server health...")
    data = _api("/health")
    if data.get("error"):
        await update.message.reply_text(f"❌ Server unreachable: {data['error']}")
    else:
        await update.message.reply_text(
            f"✅ <b>FinClaw Server Healthy</b>\n\n"
            f"Status: {data.get('status', 'unknown')}\n"
            f"Version: {data.get('version', '—')}\n"
            f"Time: {data.get('timestamp', '—')}",
            parse_mode="HTML",
        )


# ============================================================
# /portfolio
# ============================================================
async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching your portfolio...")
    data = _api("/portfolio", timeout=60)
    if data.get("error"):
        await update.message.reply_text(f"❌ Error: {data['error']}")
        return

    summary = data.get("summary", {})
    holdings = data.get("holdings", [])

    total_val = summary.get("total_value", 0)
    total_gl = summary.get("total_gain_loss", 0)
    total_ret = summary.get("total_return_pct", 0)
    gl_emoji = "📈" if total_gl >= 0 else "📉"

    lines = [
        f"💼 <b>Portfolio Summary</b>",
        f"",
        f"Total Value:  <b>${total_val:,.2f}</b>",
        f"Total P&amp;L:    <b>{gl_emoji} ${total_gl:+,.2f} ({total_ret:+.2f}%)</b>",
        f"Positions:    {summary.get('position_count', 0)}",
        f"Cash:         ${summary.get('cash', 0):,.2f}",
        f"",
        f"<b>Holdings:</b>",
    ]

    for h in holdings:
        g = h.get("gain_loss", 0)
        gp = h.get("gain_loss_pct", 0)
        em = "🟢" if g >= 0 else "🔴"
        lines.append(
            f"{em} <b>{h['ticker']}</b> — ${h.get('current_price', 0):.2f} "
            f"({gp:+.1f}%) | P&amp;L: ${g:+,.0f}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ============================================================
# /alerts
# ============================================================
async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching latest alerts...")
    data = _api("/alerts?limit=5")
    alerts = data.get("alerts", []) if isinstance(data, dict) else []

    if not alerts:
        await update.message.reply_text("📭 No alerts found yet.")
        return

    lines = ["🔔 <b>Latest Alerts</b>", ""]
    for a in alerts:
        ts = a.get("timestamp", "")[:16].replace("T", " ")
        ticker = f"[{a['ticker']}] " if a.get("ticker") else ""
        lines.append(f"<b>{ticker}{a.get('title', 'Alert')}</b>")
        lines.append(f"<i>{ts}</i>")
        msg = (a.get("message") or "")[:200]
        lines.append(msg)
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ============================================================
# /scan
# ============================================================
async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 Starting intraday scalp scan across 40 tickers...\n"
        "This takes 3-5 minutes. You'll get an alert here if I find something good!"
    )
    data = _api(
        "/opportunities/scan",
        method="POST",
        json={"session": "regular", "horizon": "scalp", "notify": True},
        timeout=10,
    )
    if data.get("error"):
        await update.message.reply_text(f"❌ Scan failed: {data['error']}")
    else:
        await update.message.reply_text(
            "✅ Scan started in background. "
            "I'll send you an alert as soon as I find a high-conviction opportunity!"
        )

# ============================================================
# /delivery
# ============================================================
async def cmd_delivery(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 Starting Delivery Volume Confluence scan across your portfolio...\n"
        "You'll receive alerts here if any strong institutional accumulation/distribution patterns are found."
    )
    def _run():
        import logging
        try:
            from skills.delivery_volume import scan_and_alert_portfolio
            portfolio = _api("/portfolio")
            if isinstance(portfolio, dict):
                holdings = portfolio.get("holdings", [])
                tickers = [h["ticker"] for h in holdings if "ticker" in h]
            else:
                tickers = []
                
            if not tickers:
                logging.warning("No tickers found in portfolio for delivery volume scan")
                return
            scan_and_alert_portfolio(tickers)
        except Exception as e:
            logging.error(f"Failed to run delivery volume scan: {e}")
            
    import threading
    threading.Thread(target=_run, daemon=True).start()

# ============================================================
# /insiders
# ============================================================
async def cmd_insiders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("⚠️ Please provide a ticker: `/insiders AAPL`", parse_mode="Markdown")
        return
    ticker = ctx.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching insider activity for {ticker}...")
    data = _api(f"/insider/{ticker}", timeout=15)
    if data.get("error"):
        await update.message.reply_text(f"❌ Error: {data['error']}")
        return
    
    insiders = data.get("insider_trades", [])
    if not insiders:
        await update.message.reply_text(f"📭 No recent insider trades found for {ticker}.")
        return

    lines = [f"👔 <b>{ticker} Insider Activity</b>\n"]
    for trade in insiders[:5]:
        tx_type = trade.get("transaction_type", "")
        shares = trade.get("shares", 0)
        price = trade.get("price", 0)
        name = trade.get("insider_name", "Unknown")
        em = "🟢" if "Buy" in tx_type else "🔴" if "Sell" in tx_type else "⚪"
        lines.append(f"{em} <b>{tx_type}</b> by {name}")
        lines.append(f"   {shares:,.0f} shares @ ${price:.2f}")
    
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

# ============================================================
# /feargreed
# ============================================================
async def cmd_feargreed(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching Fear & Greed index...")
    data = _api("/market/fear-greed", timeout=10)
    if data.get("error"):
        await update.message.reply_text(f"❌ Error: {data['error']}")
        return
    
    score = data.get("score", "N/A")
    rating = data.get("rating", "Unknown")
    await update.message.reply_text(f"🧭 <b>Fear & Greed Index</b>\n\nScore: {score}/100\nStatus: <b>{rating}</b>", parse_mode="HTML")

# ============================================================
# /movers
# ============================================================
async def cmd_movers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching market movers...")
    data = _api("/market/movers", timeout=15)
    if data.get("error"):
        await update.message.reply_text(f"❌ Error: {data['error']}")
        return
    
    lines = ["🚀 <b>Top Market Movers</b>\n"]
    gainers = data.get("gainers", [])
    if gainers:
        lines.append("<b>🟢 Gainers:</b>")
        for g in gainers[:3]:
            lines.append(f"• {g.get('ticker')}: {g.get('change_pct', 0):+.2f}%")
        lines.append("")
        
    losers = data.get("losers", [])
    if losers:
        lines.append("<b>🔴 Losers:</b>")
        for l in losers[:3]:
            lines.append(f"• {l.get('ticker')}: {l.get('change_pct', 0):+.2f}%")
            
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

# ============================================================
# /sectors
# ============================================================
async def cmd_sectors(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching sector performance...")
    data = _api("/market/sectors", timeout=15)
    if data.get("error"):
        await update.message.reply_text(f"❌ Error: {data['error']}")
        return
        
    sectors = data.get("sectors", {})
    if not sectors:
        await update.message.reply_text("📭 No sector data available.")
        return
        
    lines = ["🏢 <b>Sector Rotation</b>\n"]
    for sec, perf in sorted(sectors.items(), key=lambda x: x[1], reverse=True):
        em = "🟢" if perf >= 0 else "🔴"
        lines.append(f"{em} {sec}: {perf:+.2f}%")
        
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

# ============================================================
# /news
# ============================================================
async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("⚠️ Please provide a ticker: `/news AAPL`", parse_mode="Markdown")
        return
    ticker = ctx.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching latest news for {ticker}...")
    data = _api(f"/news/{ticker}", timeout=15)
    if data.get("error"):
        await update.message.reply_text(f"❌ Error: {data['error']}")
        return
        
    news = data.get("articles", [])
    if not news:
        await update.message.reply_text(f"📭 No recent news found for {ticker}.")
        return
        
    lines = [f"📰 <b>{ticker} Latest News</b>\n"]
    for article in news[:3]:
        lines.append(f"• <a href='{article.get('url', '')}'>{article.get('title', 'No Title')}</a>")
        lines.append(f"  <i>{article.get('publisher', 'Unknown')}</i>\n")
        
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ============================================================
# /analyze <ticker> — Institutional Deep Dive Memo via Qwen 2.5
# ============================================================
async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("⚠️ Please provide a ticker: `/analyze NVDA`", parse_mode="Markdown")
        return
    ticker = ctx.args[0].upper().strip().replace("$", "")
    await update.message.reply_text(
        f"🏛️ <b>Synthesizing Institutional Research Memo for ${ticker}...</b>\n"
        f"<i>Fetching real-time Schwab quotes, technicals, valuation, and running Red Team audit via local Qwen 2.5...</i>",
        parse_mode="HTML"
    )

    import asyncio
    def _fetch_memo():
        from skills.deep_analysis import generate_institutional_report
        return generate_institutional_report(ticker)

    try:
        data = await asyncio.to_thread(_fetch_memo)
        memo = data.get("memo", "")
        if not memo:
            await update.message.reply_text(f"❌ Failed to generate report for {ticker}.")
            return

        import html
        memo = html.escape(memo)
        import re
        memo = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', memo)
        memo = re.sub(r'\*(.*?)\*', r'<i>\1</i>', memo)

        if len(memo) > 4000:
            parts = [memo[i:i+4000] for i in range(0, len(memo), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode="HTML")
        else:
            await update.message.reply_text(memo, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Analysis failed: {e}")


# ============================================================
# /redteam <ticker> — Adversarial Risk Officer Audit via Qwen 2.5
# ============================================================
async def cmd_redteam(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("⚠️ Please provide a ticker: `/redteam NVDA`", parse_mode="Markdown")
        return
    ticker = ctx.args[0].upper().strip().replace("$", "")
    await update.message.reply_text(
        f"🛡️ <b>Running Red Team Adversarial Risk Audit for ${ticker}...</b>\n"
        f"<i>Hunting for bull traps, overhead resistance, and impending binary risks via local Qwen 2.5...</i>",
        parse_mode="HTML"
    )

    import asyncio
    def _run_audit():
        from skills.deep_analysis import red_team_validate
        return red_team_validate(ticker)

    try:
        audit = await asyncio.to_thread(_run_audit)
        verdict = audit.get("verdict", "CAUTION")
        risk_score = audit.get("risk_score", 5)
        raw = audit.get("raw_critique", "")

        v_emoji = "🟢" if verdict == "PASS" else ("🟡" if verdict == "CAUTION" else "🔴")
        header = f"{v_emoji} <b>RED TEAM AUDIT: ${ticker}</b>\n<b>Verdict:</b> {verdict} | <b>Risk Score:</b> {risk_score}/10\n\n"

        import html
        raw = html.escape(raw)
        import re
        raw = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', raw)
        raw = re.sub(r'\*(.*?)\*', r'<i>\1</i>', raw)

        msg = header + raw
        if len(msg) > 4000:
            msg = msg[:4000]
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Red Team audit failed: {e}")

# ============================================================
# LLM Free-Text Chat
# ============================================================
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route all plain-text messages through Gemini Flash with live market context."""
    text = update.message.text or ""
    if not text.strip():
        return

    await update.message.reply_text("🧠 Thinking...")

    try:
        from llm import ask, build_market_context, earnings_watch_tickers, apply_earnings_guard
    except ImportError:
        await update.message.reply_text(
            "⚠️ LLM module not available. Use /help to see command options."
        )
        return

    # Pre-fetch live context in parallel
    import asyncio
    loop = asyncio.get_event_loop()

    def fetch_context():
        import re
        potential_tickers = set(re.findall(r'\$([a-zA-Z]{1,5})\b', text))
        for word in re.findall(r'\b([A-Z]{2,5})\b', text):
            if word not in {"I", "A", "THE", "IS", "ON", "IN", "AT", "TO", "FOR", "OF", "AND", "BUY", "SELL", "HOLD", "CALL", "PUT"}:
                potential_tickers.add(word)
                
        user_quotes = {}
        for t in potential_tickers:
            t = t.upper()
            q = _api(f"/quote/{t}", timeout=5)
            if q and not q.get("error"):
                user_quotes[t] = q

        portfolio = _api("/portfolio", timeout=30)
        movers    = _api("/market/movers", timeout=20)
        fg        = _api("/market/fear-greed", timeout=10)
        alerts    = _api("/alerts?limit=3", timeout=10)
        opps      = _api("/opportunities?limit=6&session=auto", timeout=20)
        earnings_tickers = earnings_watch_tickers(
            portfolio if isinstance(portfolio, dict) else {},
            extra=sorted(potential_tickers),
        )
        earnings = _api("/earnings/calendar?tickers=" + ",".join(earnings_tickers), timeout=30)
        
        # /alerts returns a list directly, not a dict
        alerts_list = alerts if isinstance(alerts, list) else alerts.get("alerts", []) if isinstance(alerts, dict) else []
        
        return {
            "portfolio":      portfolio,
            "market_indices": (movers.get("market_indices") or {}),
            "fear_greed":     fg,
            "alerts":         alerts_list,
            "opportunities":  (opps.get("opportunities") or []),
            "user_quotes":    user_quotes,
            "earnings":       earnings if isinstance(earnings, dict) else {},
        }

    api_data = await asyncio.to_thread(fetch_context)
    context = build_market_context(api_data)

    prompt = (
        f"{context}\n\n"
        f"---\n"
        f"USER MESSAGE: {text}\n"
        f"---\n"
        f"Respond as FinClaw. Be concise (under 300 words). "
        f"Use the live data above to ground your answer. "
        f"If the question is about a ticker not in the data, say so and give general analysis. "
        f"Never say a company reports earnings today unless it is on REPORTING TODAY."
    )

    import logging
    logging.getLogger("telegram_bot").info("Sending prompt to Gemini Flash...")
    
    # Run LLM in thread (blocking) so we don't block the event loop
    try:
        response = await asyncio.to_thread(ask, prompt, None, 4096)
        response = apply_earnings_guard(response, api_data)
        logging.getLogger("telegram_bot").info(f"Gemini responded: {len(response)} chars")
    except Exception as e:
        logging.getLogger("telegram_bot").error(f"Gemini call crashed: {e}")
        response = f"⚠️ LLM Error: {e}"

    # Escape HTML tags generated by LLM so Telegram doesn't crash on unclosed `<`
    import html
    response = html.escape(str(response or "⚠️ No response generated."))
    
    # Convert basic markdown to HTML
    import re
    response = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', response)
    response = re.sub(r'\*(.*?)\*', r'<i>\1</i>', response)

    # Telegram 4096 char limit
    if len(response) > 4000:
        response = response[:3980] + "\n\n<i>[truncated]</i>"

    await update.message.reply_text(response, parse_mode="HTML")


# ============================================================
# MAIN
# ============================================================
PID_FILE = "/tmp/finclaw_telegram_bot.pid"


def main():
    if not BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN not set in .env — bot cannot start.")
        sys.exit(1)

    # ── Singleton guard — prevent duplicate instances ──────────────────────
    import os as _os
    my_pid = str(_os.getpid())
    if _os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE).read().strip())
            # Check if that PID is still alive
            _os.kill(old_pid, 0)  # signal 0 = existence check, no kill
            logging.error(
                "Another telegram_bot instance is running (PID %d). Exiting.", old_pid
            )
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            pass  # Stale PID file — safe to continue
    with open(PID_FILE, "w") as f:
        f.write(my_pid)
    import atexit
    atexit.register(lambda: _os.path.exists(PID_FILE) and _os.remove(PID_FILE))
    # ──────────────────────────────────────────────────────────────────────

    logging.info("Starting FinClaw Telegram Bot (polling)...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("delivery", cmd_delivery))
    app.add_handler(CommandHandler("insiders", cmd_insiders))
    app.add_handler(CommandHandler("feargreed", cmd_feargreed))
    app.add_handler(CommandHandler("movers", cmd_movers))
    app.add_handler(CommandHandler("sectors", cmd_sectors))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("a", cmd_analyze))
    app.add_handler(CommandHandler("redteam", cmd_redteam))
    app.add_handler(CommandHandler("rt", cmd_redteam))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Polling mode — no public server needed
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
