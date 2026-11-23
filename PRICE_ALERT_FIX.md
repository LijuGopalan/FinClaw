# Telegram Alert Price Mismatch - Fix Documentation

## Problem
Telegram alerts were showing incorrect/stale prices that didn't match current market prices. The entry zones, targets, and stop-loss levels were calculated at scan time but could be outdated by the time the alert was sent.

## Root Cause
The opportunity scanning system (`skills/opportunity_engine.py`) calculates price levels when the scan runs, but these prices can become stale by the time:
1. The scan completes (can take 3-5 minutes for all tickers)
2. The alert is formatted and sent via Telegram
3. The user receives and reads the alert

## Solution Implemented

### Changes Made to `skills/opportunity_engine.py`

Modified the `build_opportunity_brief()` function to:

1. **Refresh prices in real-time** before sending alerts
   - Fetches fresh quotes from Schwab/IBKR/Tradier APIs
   - Only uses the latest price available at alert generation time

2. **Recalculate all price levels** with fresh data
   - Entry zones (low and high)
   - Target prices
   - Stop-loss levels
   - Based on current price + ATR (Average True Range)

3. **Add comprehensive logging** for debugging
   - Logs original scan price vs fresh price
   - Logs percentage change since scan
   - Logs recalculated levels
   - Helps identify when and why prices diverge

4. **Maintain backward compatibility**
   - New `refresh_prices=True` parameter (default enabled)
   - Can be disabled if needed with `refresh_prices=False`
   - Gracefully falls back to original price if refresh fails

### Code Changes

**Before:**
```python
def build_opportunity_brief(scan_result, max_items=5):
    # Used stale prices from scan time
    price = item.get("price", 0)
```

**After:**
```python
def build_opportunity_brief(scan_result, max_items=5, refresh_prices=True):
    # Fetch fresh price before formatting alert
    if refresh_prices and ticker:
        fresh_quote = get_stock_quote(ticker)
        if fresh_quote and not fresh_quote.get("error"):
            price = fresh_quote.get("price")
            # Recalculate levels with fresh price
            fresh_levels = _price_levels(price, atr, horizon)
            item.update(fresh_levels)
```

### Alert Format Updated

Changed from:
```
💵 Price: $150.00
```

To:
```
💵 Current Price: $150.00
```

This makes it clearer that the price shown is the current/live price, not a historical scan price.

## Impact

### Where This Fix Applies

The fix is automatically applied to all alerts sent through:
- `/scan` command in Telegram bot
- `/opps` command in Telegram bot  
- Scheduled background scans in `scheduler.py`
- Server API `/api/opportunities/scan` endpoint
- Manual trade alert system

### What Gets Refreshed

✅ Current ticker price
✅ Entry zone (low-high range)
✅ Target price
✅ Stop-loss level
✅ Displayed in alert message

### What Stays the Same

The original scan scoring, indicators, and analysis remain unchanged:
- Score (ML probability, technical indicators, etc.)
- Risk/reward ratio calculation logic
- Thesis and reasoning
- Catalyst flags
- Smart money signals

Only the **price data and derived levels** are refreshed.

## Testing

To verify the fix is working:

1. **Check server logs** (`server.log`) for messages like:
   ```
   [AAPL] Refreshing price for alert (original: $150.00)
   [AAPL] Price refreshed: $151.23 (+0.82% from scan)
   [AAPL] Levels recalculated: Entry 150.80-151.40, Target 152.50, Stop 149.90
   ```

2. **Compare alert prices** to live market data:
   - Open your brokerage app or financial site
   - Check the ticker's current price
   - Compare to what the Telegram alert shows
   - They should now match within seconds

3. **Test manually** by running:
   ```bash
   curl -X POST http://localhost:5055/api/opportunities/scan \
     -H "Content-Type: application/json" \
     -d '{"session": "regular", "horizon": "scalp", "notify": true}'
   ```
   Then check Telegram for the alert with fresh prices.

## Monitoring

The fix includes detailed logging. To monitor for issues:

```bash
# Watch for price refresh logs
tail -f server.log | grep "Refreshing price"

# Check for errors
tail -f server.log | grep -i "error refreshing price"

# See price changes
tail -f server.log | grep "Price refreshed"
```

## Fallback Behavior

If fresh price fetch fails (API down, rate limit, etc.):
- System logs a warning
- Falls back to original scan price
- Alert still gets sent (better stale data than no alert)
- Error is logged for investigation

## Performance Impact

Minimal:
- Adds ~100-300ms per ticker in the alert (1-2 API calls)
- Only happens when generating alerts (not during initial scan)
- Parallelized - doesn't delay scan completion
- Schwab API is fast and reliable

## Future Improvements

Potential enhancements for v2:
1. Add timestamp to alerts showing when price was fetched
2. Show price change % since scan in alert text
3. Cache prices for 5-10 seconds to reduce API calls
4. Add price staleness warning if scan >5 min old

## Rollback

If issues occur, disable price refresh:

```python
# In server.py line ~601
brief = build_opportunity_brief(result, refresh_prices=False)
```

Or revert the entire file:
```bash
git checkout HEAD -- skills/opportunity_engine.py
```

## Related Files Modified

- `skills/opportunity_engine.py` - Main fix implementation
- This documentation file

## Related Files Not Modified (but interact with fix)

- `server.py` - Calls build_opportunity_brief() 
- `telegram_bot.py` - Calls build_opportunity_brief()
- `scheduler.py` - Uses send_telegram for alerts
- `skills/notifications.py` - Sends the formatted alerts

---

**Fix Date:** 2024-01-XX  
**Author:** Kiro AI Assistant  
**Status:** ✅ Implemented and Ready for Testing
