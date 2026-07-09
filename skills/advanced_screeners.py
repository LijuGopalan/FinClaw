import pandas as pd
import numpy as np
import scipy.stats as si
import datetime

try:
    from financial_skills import get_price_history, get_options_chain
except ImportError:
    from .financial_skills import get_price_history, get_options_chain

def detect_episodic_pivot(ticker):
    """Detects a Gap & Go (Episodic Pivot) - Gap up > 10% on 3x volume."""
    try:
        df = get_price_history(ticker, period="1mo", interval="1d")
        if df is None or len(df) < 2:
            return {"detected": False}
            
        recent = df.iloc[-1]
        prev = df.iloc[-2]
        avg_vol = df['Volume'].mean()
        
        gap_pct = ((recent['Open'] - prev['Close']) / prev['Close']) * 100
        vol_ratio = recent['Volume'] / avg_vol if avg_vol > 0 else 0
        
        if gap_pct >= 10 and vol_ratio >= 3.0 and recent['Close'] > recent['Open']:
            return {
                "detected": True,
                "gap_pct": round(gap_pct, 1),
                "vol_ratio": round(vol_ratio, 1),
                "reason": f"Episodic Pivot: {gap_pct:.1f}% gap on {vol_ratio:.1f}x volume"
            }
        return {"detected": False}
    except Exception:
        return {"detected": False}

def detect_mean_reversion(ticker):
    """Detects Rubber Band setup - stretched >15% below 10 EMA, RSI < 25."""
    try:
        df = get_price_history(ticker, period="3mo", interval="1d")
        if df is None or len(df) < 20:
            return {"detected": False}
            
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        
        # Simple RSI calculation
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        recent = df.iloc[-1]
        stretch_pct = ((recent['Close'] - recent['EMA10']) / recent['EMA10']) * 100
        rsi = recent['RSI']
        
        if stretch_pct <= -15 and rsi < 25:
            return {
                "detected": True,
                "stretch_pct": round(stretch_pct, 1),
                "rsi": round(rsi, 1),
                "reason": f"Mean Reversion: Stretched {stretch_pct:.1f}% below 10EMA, RSI {rsi:.1f}"
            }
        return {"detected": False}
    except Exception:
        return {"detected": False}

def _bs_gamma(S, K, T, r, sigma):
    """Black-Scholes Gamma estimation."""
    if T <= 0 or sigma <= 0:
        return 0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    gamma = si.norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return gamma

def calculate_gamma_walls(ticker):
    """Estimates Gamma Walls using Open Interest and BS Gamma to find Support/Resistance."""
    try:
        df = get_price_history(ticker, period="5d", interval="1d")
        if df is None or df.empty:
            return None
        current_price = df['Close'].iloc[-1]
        
        chain = get_options_chain(ticker)
        if chain is None or chain.get("error"):
            return None
            
        nearest_expiry = chain.get("expiry")
        if not nearest_expiry: return None
        
        calls = pd.DataFrame(chain.get("all_calls", []))
        puts = pd.DataFrame(chain.get("all_puts", []))
        
        # Approximate time to expiry in years
        days_to_expiry = max(1, (datetime.datetime.strptime(nearest_expiry, "%Y-%m-%d") - datetime.datetime.now()).days)
        T = days_to_expiry / 365.0
        
        # Simplified risk-free rate and vol (can be tuned)
        r = 0.05
        
        def _get_iv(row): return row.get('iv', row.get('impliedVolatility', 0.5)) or 0.5
        def _get_oi(row): return row.get('open_interest', row.get('openInterest', 0)) or 0
        
        # Calculate Gamma * OI for calls and puts
        calls['Gamma'] = calls.apply(lambda row: _bs_gamma(current_price, row['strike'], T, r, _get_iv(row)), axis=1)
        calls['GEX'] = calls['Gamma'] * calls.apply(_get_oi, axis=1) * 100 # *100 shares per contract
        
        puts['Gamma'] = puts.apply(lambda row: _bs_gamma(current_price, row['strike'], T, r, _get_iv(row)), axis=1)
        puts['GEX'] = puts['Gamma'] * puts.apply(_get_oi, axis=1) * 100
        
        if calls.empty or puts.empty:
            return None
            
        call_wall_idx = calls['GEX'].idxmax()
        put_wall_idx = puts['GEX'].idxmax()
        
        call_wall_strike = calls.loc[call_wall_idx, 'strike']
        put_wall_strike = puts.loc[put_wall_idx, 'strike']
        
        return {
            "support": put_wall_strike,
            "resistance": call_wall_strike,
            "expiry": nearest_expiry
        }
    except Exception:
        return None

def detect_block_trades(ticker):
    """Proxy for Dark Pool: Detects massive 5-min volume anomalies >5x std dev."""
    try:
        df = get_price_history(ticker, period="5d", interval="5m")
        if df is None or len(df) < 50:
            return {"detected": False}
            
        vol_mean = df['Volume'].mean()
        vol_std = df['Volume'].std()
        
        recent_bars = df.tail(12) # last hour
        max_vol = recent_bars['Volume'].max()
        
        if vol_std > 0 and max_vol > (vol_mean + 5 * vol_std):
            return {
                "detected": True,
                "reason": f"Dark Pool Proxy: Massive volume block detected ({max_vol} shares in 5m)"
            }
        return {"detected": False}
    except Exception:
        return {"detected": False}

