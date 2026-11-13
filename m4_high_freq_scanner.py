import sys
import time
import pandas as pd
import numpy as np
import json
import os
from concurrent.futures import ThreadPoolExecutor

def load_watchlist():
    """Load tickers from universe.json (your personal watchlist)"""
    universe_path = os.path.join(os.path.dirname(__file__), "data", "universe.json")
    try:
        with open(universe_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading universe.json: {e}")
        # Fallback to a minimal set
        return ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD"]

# Load your personal watchlist instead of SP500
WATCHLIST = load_watchlist()

def fetch_data(ticker):
    try:
        import sys
        import os
        # Ensure skills directory is importable
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))
        from financial_skills import get_price_history
        hist = get_price_history(ticker, period="5d", interval="5m")
        if hist is None or hist.empty: return None
        
        hist = hist.dropna()
        latest = hist.iloc[-1]
        volume = latest.get("Volume", 0)
        close = latest.get("Close", 0)
        open_p = hist.iloc[0].get("Open", 0)
        
        # Vectorized VWAP
        typical = (hist["High"] + hist["Low"] + hist["Close"]) / 3
        vwap = (typical * hist["Volume"]).cumsum() / hist["Volume"].cumsum()
        vwap_val = vwap.iloc[-1]
        
        # Avg Vol
        avg_vol = hist["Volume"].mean()
        rvol = volume / avg_vol if avg_vol > 0 else 0
        
        # Move
        move = ((close - open_p) / open_p) * 100 if open_p > 0 else 0
        
        # Score calculation
        score = 0
        if rvol > 2: score += 10
        if move > 2: score += 10
        if close > vwap_val: score += 5
        
        return {
            "ticker": ticker,
            "price": round(close, 2),
            "move_pct": round(move, 2),
            "rvol": round(rvol, 1),
            "vwap_dist": round(((close - vwap_val)/vwap_val)*100, 2) if vwap_val > 0 else 0,
            "score": score
        }
    except Exception:
        return None

def run_high_frequency_scan():
    print(f"🚀 Starting M4 High-Frequency Scan on {len(WATCHLIST)} tickers from your watchlist...")
    start = time.time()
    
    results = []
    # Utilize M4 efficiently
    with ThreadPoolExecutor(max_workers=30) as executor:
        for res in executor.map(fetch_data, WATCHLIST):
            if res:
                results.append(res)
                
    end = time.time()
    print(f"⏱️ Scan complete in {end-start:.2f} seconds!\n")
    
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by="score", ascending=False).head(15)
        print("🔝 Top 15 Setups from Scan:")
        print(df.to_string(index=False))
        
        try:
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))
            from notifications import send_telegram
            
            top_5 = df.head(5)
            msg = "⚡ <b>M4 High-Freq Scan Results</b>\n\n"
            for _, row in top_5.iterrows():
                msg += f"• <b>${row['ticker']}</b>: ${row['price']} | Move: {row['move_pct']}% | RVol: {row['rvol']}x\n"
            send_telegram(msg, parse_mode="HTML")
            print("Telegram alert sent successfully.")
        except Exception as e:
            print(f"Failed to send telegram alert: {e}")
        
if __name__ == "__main__":
    run_high_frequency_scan()
