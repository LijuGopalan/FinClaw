#!/bin/bash
# Script to restart FinClaw services and apply the price refresh fix

set -e

echo "🔧 Applying Telegram Alert Price Fix..."
echo ""

# Check if processes are running
if pgrep -f "python.*server.py" > /dev/null; then
    echo "✅ FinClaw server is running"
else
    echo "⚠️  FinClaw server is not running"
fi

if pgrep -f "python.*telegram_bot.py" > /dev/null; then
    echo "✅ Telegram bot is running"
else
    echo "⚠️  Telegram bot is not running"
fi

if pgrep -f "python.*scheduler.py" > /dev/null; then
    echo "✅ Scheduler is running"
else
    echo "⚠️  Scheduler is not running"
fi

echo ""
echo "🔄 Restarting all services to apply the fix..."
echo ""

# Stop all services
echo "Stopping services..."
pkill -9 -f "python.*server.py" 2>/dev/null || echo "  (server not running)"
pkill -9 -f "python.*telegram_bot.py" 2>/dev/null || echo "  (telegram_bot not running)"
pkill -9 -f "python.*scheduler.py" 2>/dev/null || echo "  (scheduler not running)"

sleep 2

# Start services
echo ""
echo "Starting services with the price refresh fix..."
cd "$(dirname "$0")"

if [ -f "start.sh" ]; then
    ./start.sh
    echo ""
    echo "✅ Services restarted successfully!"
else
    echo "⚠️  start.sh not found. Starting manually..."
    nohup python3 server.py > server.log 2>&1 &
    nohup python3 scheduler.py > scheduler.log 2>&1 &
    nohup python3 telegram_bot.py > telegram.log 2>&1 &
    echo "✅ Services started manually"
fi

sleep 3

echo ""
echo "📊 Verifying services..."
if pgrep -f "python.*server.py" > /dev/null; then
    echo "✅ Server: Running"
else
    echo "❌ Server: Not running"
fi

if pgrep -f "python.*telegram_bot.py" > /dev/null; then
    echo "✅ Telegram Bot: Running"
else
    echo "❌ Telegram Bot: Not running"
fi

if pgrep -f "python.*scheduler.py" > /dev/null; then
    echo "✅ Scheduler: Running"
else
    echo "❌ Scheduler: Not running"
fi

echo ""
echo "🎯 Price Alert Fix Applied!"
echo ""
echo "What changed:"
echo "  • Alerts now fetch fresh prices before sending"
echo "  • Entry/target/stop levels recalculated with current prices"
echo "  • Detailed logging added for debugging"
echo ""
echo "To verify it's working:"
echo "  1. Send /scan in Telegram"
echo "  2. Check server.log for 'Refreshing price' messages"
echo "  3. Compare alert prices to live market data"
echo ""
echo "To monitor: tail -f server.log | grep 'Refreshing price'"
echo ""
