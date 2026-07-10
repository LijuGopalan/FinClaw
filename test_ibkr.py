import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'skills')))

from skills.ibkr_client import (
    ibkr_available, 
    get_quote, 
    get_price_history,
    get_intraday_history,
    get_option_chain
)

def test_ibkr():
    print("Checking IBKR Connection...")
    if not ibkr_available():
        print("❌ Could not connect to IBKR. Make sure IB Gateway is running on port 4001.")
        sys.exit(1)
        
    print("✅ Connected to IBKR!\n")
    
    ticker = "AAPL"
    
    print(f"Fetching Quote for {ticker}...")
    quote = get_quote(ticker)
    print(f"Quote: {quote}\n")
    
    print(f"Fetching 5-Day Historical Data for {ticker}...")
    hist = get_price_history(ticker, days=5)
    print(hist.head() if hist is not None else "None")
    print()
    
    print(f"Fetching 1-Day Intraday Data for {ticker}...")
    intra = get_intraday_history(ticker, days=1, interval="5m")
    print(intra.head() if intra is not None else "None")
    print()
    
    print(f"Fetching Option Chain for {ticker}...")
    chain = get_option_chain(ticker)
    print(f"Expiry: {chain.get('expiry')}")
    print(f"Strikes: {chain.get('strikes')[:5]} ... (truncated)")
    
if __name__ == "__main__":
    test_ibkr()
