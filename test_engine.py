import sys
import json
from skills.opportunity_engine import get_smart_money_watchlist, score_ticker_opportunity

def test():
    print("Fetching Smart Money Watchlist...")
    smart = get_smart_money_watchlist()
    print("Smart Money Tickers:", smart)
    
    if smart:
        ticker = smart[0]
        print(f"\nScoring ticker: {ticker}")
        res = score_ticker_opportunity(ticker)
        print("Score:", res.get("score"))
        print("Smart Money Flags:", res.get("smart_money_flags"))

if __name__ == "__main__":
    test()
