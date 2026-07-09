import os
import sys

# Ensure the skills directory is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))

from schwab_client import (
    get_client,
    get_quote,
    get_price_history,
    get_intraday_history,
    schwab_available
)

def test_schwab():
    print("--- Testing Schwab API Integration ---")
    
    if not schwab_available():
        print("❌ Schwab is NOT available. This usually means the token is invalid or missing.")
        print("To fix this, the OAuth flow needs to be completed.")
        return
        
    print("✅ Schwab is available (Token is loaded)")
    
    ticker = "AAPL"
    
    print(f"\n1. Fetching Quote for {ticker}...")
    quote = get_quote(ticker)
    if quote:
        print(f"✅ Success! Quote: {quote}")
    else:
        print("❌ Failed to fetch quote.")
        
    print(f"\n2. Fetching Daily Price History for {ticker} (Last 5 days)...")
    history = get_price_history(ticker, days=5)
    if history:
        print(f"✅ Success! Fetched {len(history)} daily candles.")
        print(f"   Latest candle: {history[-1]}")
    else:
        print("❌ Failed to fetch daily history.")
        
    print(f"\n3. Fetching Intraday History for {ticker} (5m interval)...")
    intraday = get_intraday_history(ticker, days=1, interval="5m")
    if intraday:
        print(f"✅ Success! Fetched {len(intraday)} intraday candles.")
        print(f"   Latest candle: {intraday[-1]}")
    else:
        print("❌ Failed to fetch intraday history.")

if __name__ == "__main__":
    test_schwab()
