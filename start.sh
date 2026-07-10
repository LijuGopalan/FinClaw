#!/bin/bash
# start.sh — Launch all FinClaw services
# =========================================
# 1. API Server    (server.py)     — Flask on :5055
# 2. Scheduler     (scheduler.py)  — Algorithmic + LLM cron
# 3. Telegram Bot  (telegram_bot.py) — Commands + Gemini chat
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Trap SIGTERM/SIGINT and kill all child processes
trap 'echo "Shutting down FinClaw..."; kill 0' SIGTERM SIGINT

echo "🦾 Starting FinClaw Stack..."

# ── Kill any stale orphans from previous runs ─────────────────
echo "  → Cleaning up any stale processes..."
pkill -f "python.*scheduler\.py"   2>/dev/null && sleep 0.5 || true
pkill -f "python.*telegram_bot\.py" 2>/dev/null && sleep 0.5 || true
pkill -f "python.*server\.py"       2>/dev/null && sleep 0.5 || true
rm -f /tmp/finclaw_telegram_bot.pid

echo "  → Scheduler Daemon (algorithmic + LLM briefs)"
./venv/bin/python scheduler.py &

echo "  → Telegram Bot (commands + Gemini chat)"
./venv/bin/python telegram_bot.py &



echo "  → API Server (Flask :5055)"
exec ./venv/bin/python server.py
