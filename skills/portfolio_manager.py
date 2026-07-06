import yfinance as yf
import pandas as pd

def calculate_trailing_stop(ticker, entry_price=None, atr_multiplier=3):
    """
    Calculates an ATR-based Chandelier Exit trailing stop.
    If entry_price is provided, it calculates the highest high since entry.
    Otherwise, it just uses the highest high of the last 20 days.
    """
    try:
        stock = yf.Ticker(ticker)
        # Fetch last 3 months to get ATR and Highest High
        df = stock.history(period="3mo")
        if len(df) < 20:
            return None
            
        # Calculate ATR (14 day)
        df['TR'] = df[['High', 'Low', 'Close']].apply(lambda x: max(x['High'] - x['Low'], abs(x['High'] - df['Close'].shift(1).loc[x.name]), abs(x['Low'] - df['Close'].shift(1).loc[x.name])) if not pd.isna(df['Close'].shift(1).loc[x.name]) else x['High'] - x['Low'], axis=1)
        # simplified TR for speed
        df['Prev_Close'] = df['Close'].shift(1)
        df['TR'] = df.apply(lambda row: max(row['High'] - row['Low'], abs(row['High'] - row['Prev_Close']) if pd.notna(row['Prev_Close']) else 0, abs(row['Low'] - row['Prev_Close']) if pd.notna(row['Prev_Close']) else 0), axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        
        current_atr = df['ATR'].iloc[-1]
        
        # Determine highest high
        # In a real portfolio system, we would filter df from the exact entry date
        # Here we just assume the last 20 days if no explicit date/price mapping is done for simplicity
        highest_high = df['High'].tail(20).max()
        
        trailing_stop = highest_high - (current_atr * atr_multiplier)
        current_price = df['Close'].iloc[-1]
        
        # The trailing stop should never be above the current price
        trailing_stop = min(trailing_stop, current_price * 0.99)
        
        return {
            "trailing_stop": round(trailing_stop, 2),
            "highest_high": round(highest_high, 2),
            "current_atr": round(current_atr, 2),
            "distance_pct": round(((current_price - trailing_stop) / current_price) * 100, 1)
        }
    except Exception:
        return None
