# FinClaw Quick Reference

## 🎯 Your 75-Ticker Watchlist

### By Sector
```
Tech (27):       AAPL MSFT GOOG GOOGL META AMZN NFLX ORCL PYPL SNAP 
                 SOFI PLTR SOUN ANET DELL CRWV COHR NBIS AXTI LITE 
                 CRDO AAOI VRT FN SNDK SKHY SMCI

Semis (14):      NVDA AMD INTC TSM AVGO MU QCOM NXPI ARM LRCX MRVL 
                 RMBS STX WDC

Crypto (5):      CLSK MARA COIN IREN MSTR

Energy (6):      XOM CVX COP SLB HAL USO

Finance (4):     BAC WFC SCHW V

Auto/EV (6):     TSLA NIO XPEV RIVN F CVNA

Consumer (4):    LULU DIS BA JNJ

Metals (7):      WPM RGLD AEM HMY NEM KGC FNV

Other (2):       BABA BRK.A
```

## ⚡ Common Commands

### Telegram
```
/scan              - Run full scan of your 75 tickers
/opps              - Show top opportunities
/portfolio         - Your portfolio summary
/alerts            - Recent alerts
/analyze TICKER    - Deep dive analysis
/redteam TICKER    - Risk audit
```

### Terminal
```bash
# Check services
ps aux | grep "server\|telegram\|scheduler" | grep -v grep

# View logs
tail -f server.log

# Restart services
./apply_price_fix.sh

# Check API
curl localhost:5055/api/health
```

## 📊 Expected Scan Times

```
Pre-market:  2-3 minutes
Intraday:    3-5 minutes
Post-market: 2-3 minutes
```

## 🔧 Quick Fixes

### Services Not Responding
```bash
pkill -9 -f python
./start.sh
```

### Wrong Tickers Being Scanned
```bash
# Verify universe
cat data/universe.json | wc -l  # Should be 77 lines (75 tickers + brackets)

# Restart
./apply_price_fix.sh
```

### Stale Prices
Check logs for price refresh:
```bash
tail -f server.log | grep "Refreshing price"
```

## 📁 Key Files

```
data/universe.json         - Your 75 tickers
openclaw.config.yml        - Main configuration
server.log                 - Runtime logs
data/stock-watchlist.csv   - Your original CSV
```

## ✅ Health Check

Run this to verify everything:
```bash
cd /Users/adgroup/.gemini/antigravity/scratch/openclaw-financial-assistant

echo "1. Services:"
ps aux | grep -E "server.py|telegram_bot.py|scheduler.py" | grep -v grep | wc -l
echo "   (Should be 3)"

echo "2. Ticker count:"
cat data/universe.json | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
echo "   (Should be 75)"

echo "3. API status:"
curl -s localhost:5055/api/health | grep -o '"status":"[^"]*"'
echo "   (Should be healthy)"
```

## 🆘 Support

If issues persist:
1. Check CONFIGURATION_COMPLETE.md
2. Check WATCHLIST_UPDATE.md
3. Review server.log for errors
4. Verify Schwab API is connected

---
**Quick Start:** Send `/scan` in Telegram to test your configuration!
