import yfinance as yf
import pandas as pd
import numpy as np

def detect_vcp_setup(ticker):
    """
    Scans a ticker for Mark Minervini's Volatility Contraction Pattern (VCP).
    Step 1: Validates the Minervini Trend Template.
    Step 2: Checks for Volatility Contraction and Volume Dry-up on the right side of the base.
    """
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if df.empty or len(df) < 200:
            return {"vcp_detected": False, "reason": "Not enough data"}

        # Calculate moving averages
        df['SMA50'] = df['Close'].rolling(window=50).mean()
        df['SMA150'] = df['Close'].rolling(window=150).mean()
        df['SMA200'] = df['Close'].rolling(window=200).mean()
        
        current_close = df['Close'].iloc[-1]
        current_50 = df['SMA50'].iloc[-1]
        current_150 = df['SMA150'].iloc[-1]
        current_200 = df['SMA200'].iloc[-1]
        
        # 52-week highs and lows
        low_52wk = df['Low'].min()
        high_52wk = df['High'].max()

        # Phase 1: Trend Template Conditions
        cond_1 = current_close > current_150 and current_close > current_200
        cond_2 = current_150 > current_200
        
        # Check if 200 SMA is trending up for at least 1 month (approx 21 trading days)
        sma200_20days_ago = df['SMA200'].iloc[-22]
        cond_3 = current_200 > sma200_20days_ago
        
        cond_4 = current_50 > current_150 and current_50 > current_200
        cond_5 = current_close > current_50
        cond_6 = current_close >= (low_52wk * 1.30)
        cond_7 = current_close >= (high_52wk * 0.75) # within 25% of 52w high

        trend_template_passed = cond_1 and cond_2 and cond_3 and cond_4 and cond_5 and cond_6 and cond_7
        
        if not trend_template_passed:
            return {"vcp_detected": False, "reason": "Failed Minervini Trend Template"}

        # Phase 2: Volatility Contraction & Volume Dry-up
        recent_df = df.tail(60).copy()
        recent_df['Vol_SMA50'] = recent_df['Volume'].rolling(window=50).mean()
        
        # Calculate True Range for volatility measurement
        recent_df['Previous_Close'] = recent_df['Close'].shift(1)
        recent_df['TR'] = np.maximum.reduce([
            recent_df['High'] - recent_df['Low'],
            (recent_df['High'] - recent_df['Previous_Close']).abs(),
            (recent_df['Low'] - recent_df['Previous_Close']).abs()
        ])
        
        # Split into two 30-day windows to check if TR is compressing
        first_half_tr = recent_df['TR'].iloc[1:30].mean() # skip first NaN
        second_half_tr = recent_df['TR'].iloc[-30:].mean()
        
        volatility_contracting = second_half_tr < (first_half_tr * 0.90) # At least 10% tighter
        
        # Volume dry-up check on recent down days
        last_10 = recent_df.tail(10)
        down_days = last_10[last_10['Close'] < last_10['Open']]
        
        volume_dry_up = True
        if not down_days.empty:
            avg_down_vol = down_days['Volume'].mean()
            current_vol_sma = last_10['Vol_SMA50'].iloc[-1]
            if pd.notna(current_vol_sma) and avg_down_vol > current_vol_sma * 1.1:
                # Down volume shouldn't be significantly above 50d avg
                volume_dry_up = False
                
        if volatility_contracting and volume_dry_up:
            return {
                "vcp_detected": True,
                "reason": "Passed Trend Template + Volatility Contraction + Volume Dry-up",
                "buy_point": round(high_52wk, 2)
            }
        else:
            return {"vcp_detected": False, "reason": "Failed Volatility Contraction checks"}
            
    except Exception as e:
        return {"vcp_detected": False, "error": str(e)}

if __name__ == "__main__":
    import json
    # Run a test against PLTR or NVDA
    print(json.dumps(detect_vcp_setup("PLTR"), indent=2))
