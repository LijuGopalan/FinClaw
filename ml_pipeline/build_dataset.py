import os
import json
import time
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UNIVERSE_PATH = os.path.join(DATA_DIR, "universe.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "ml_dataset.csv")

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def process_ticker(ticker):
    try:
        # Fetch 60 days of 5m data (max allowed by Yahoo Finance)
        hist = yf.Ticker(ticker).history(period="60d", interval="5m")
        if hist.empty or len(hist) < 100:
            return None
            
        hist = hist.dropna()
        
        # Calculate features
        hist['rsi'] = calculate_rsi(hist['Close'])
        
        # MACD
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist['macd_hist'] = macd - signal
        
        # ATR %
        atr = calculate_atr(hist)
        hist['atr_pct'] = atr / hist['Close'] * 100
        
        # Relative Volume (compared to rolling 40 periods)
        hist['rvol'] = hist['Volume'] / hist['Volume'].rolling(40).mean()
        
        # VWAP (resets daily)
        # Convert index to timezone-naive if it's tz-aware to safely extract date
        idx = hist.index
        if idx.tz is not None:
            idx = idx.tz_convert('America/New_York')
        hist['date'] = idx.date
        
        typical_price = (hist['High'] + hist['Low'] + hist['Close']) / 3
        hist['vol_price'] = typical_price * hist['Volume']
        
        # Group by date to calculate daily VWAP
        daily_cum_vol = hist.groupby('date')['Volume'].cumsum()
        daily_cum_vol_price = hist.groupby('date')['vol_price'].cumsum()
        
        hist['vwap'] = daily_cum_vol_price / daily_cum_vol
        hist['vwap_dist'] = (hist['Close'] - hist['vwap']) / hist['vwap'] * 100
        
        # Target: Max high in next 12 periods (1 hour) relative to current close
        # Shift -12, take rolling max backwards (by reversing or shifting)
        indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=12)
        future_high = hist['High'].rolling(window=indexer, min_periods=1).max()
        
        hist['future_move'] = (future_high - hist['Close']) / hist['Close'] * 100
        hist['target'] = (hist['future_move'] >= 1.0).astype(int)
        
        # Drop NaNs created by rolling windows
        hist = hist.dropna()
        
        # Select final columns
        features = ['rsi', 'macd_hist', 'atr_pct', 'rvol', 'vwap_dist', 'target']
        result = hist[features].copy()
        result['ticker'] = ticker
        
        return result
    except Exception as e:
        return None

def build_dataset():
    print("🚀 Starting dataset build...")
    
    if os.path.exists(UNIVERSE_PATH):
        with open(UNIVERSE_PATH, 'r') as f:
            universe = json.load(f)
    else:
        universe = ["AAPL", "MSFT", "NVDA", "TSLA"]
        
    # Take top 150 to keep the demo dataset build fast (under 20-30s)
    universe = universe[:150]
    
    all_data = []
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        for res in executor.map(process_ticker, universe):
            if res is not None:
                all_data.append(res)
                
    end = time.time()
    print(f"⏱️ Data fetch complete in {end-start:.2f} seconds.")
    
    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        print(f"📊 Dataset size: {len(df)} rows")
        print(f"🎯 Target distribution:\n{df['target'].value_counts(normalize=True) * 100}")
        
        df.to_csv(OUTPUT_PATH, index=False)
        print(f"💾 Saved to {OUTPUT_PATH}")
    else:
        print("❌ No data collected.")

if __name__ == "__main__":
    build_dataset()
