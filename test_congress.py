import sys
from capitolgains import CapitolGains

def test_congress():
    try:
        print("Testing CapitolGains...")
        cg = CapitolGains()
        trades = cg.get_trades(days=7) # Get trades from the last 7 days
        print("CONGRESSIONAL TRADES:")
        print(trades.head())
    except Exception as e:
        print(f"Congress Error: {e}")

if __name__ == "__main__":
    test_congress()
