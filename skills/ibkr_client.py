"""
ibkr_client.py — Interactive Brokers (ib_async) Market Data API Integration
Replaces schwab_client.py
"""

import os
import logging
import pandas as pd
from datetime import datetime, timedelta
import asyncio
from dotenv import load_dotenv

import ib_async as iba

load_dotenv()
logger = logging.getLogger("finclaw.ibkr")

IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", 4001)) # 4001 for IB Gateway, 7496 for TWS
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", 1))

import time

_ib = None
_ibkr_available = False
_last_attempt = 0
_COOLDOWN_SECONDS = 60

# Apply nest_asyncio to allow ib_async to run synchronously in existing event loops
# iba.util.patchAsyncio() # REMOVED: Causes "Timeout should be used inside a task" in Python 3.11+

def _ensure_client():
    global _ib, _ibkr_available, _last_attempt
    if _ib is not None and _ib.isConnected():
        _ibkr_available = True
        return
        
    now = time.time()
    # If we recently tried and failed, don't spam connections. Fail fast to trigger yfinance fallback.
    if now - _last_attempt < _COOLDOWN_SECONDS:
        _ibkr_available = False
        return
        
    _last_attempt = now
    
    try:
        ib = iba.IB()
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=4.0)
        _ib = ib
        _ibkr_available = True
        logger.info(f"✅ IBKR client connected to {IBKR_HOST}:{IBKR_PORT}")
    except Exception as exc:
        _ibkr_available = False
        logger.warning(f"IBKR connection failed (Ensure IB Gateway is running on port {IBKR_PORT}). Falling back to Yahoo Finance. Error: {exc}")

def ibkr_available() -> bool:
    _ensure_client()
    return _ibkr_available

def get_quote(ticker: str) -> dict:
    if not ibkr_available(): return None
    try:
        contract = iba.Stock(ticker, 'SMART', 'USD')
        _ib.qualifyContracts(contract)
        [ticker_data] = _ib.reqTickers(contract)
        
        # IBKR doesn't always provide full data instantly without subscriptions,
        # but reqTickers provides a snapshot.
        import math
        
        last_price = ticker_data.last if ticker_data.last is not None and not math.isnan(ticker_data.last) else 0
        close_price = ticker_data.close if ticker_data.close is not None and not math.isnan(ticker_data.close) else 0
        
        price = last_price if last_price > 0 else close_price
        
        if price == 0:
            logger.warning(f"IBKR returned no valid price for {ticker}. Check data subscriptions.")
            return None
            
        change = (price - close_price) / close_price * 100 if close_price and close_price > 0 else 0.0
        
        return {
            "ticker": ticker,
            "price": price,
            "change_percent": change,
            "volume": ticker_data.volume if ticker_data.volume is not None and not math.isnan(ticker_data.volume) else 0,
            "market_cap": None
        }
    except Exception as e:
        logger.error(f"IBKR get_quote error for {ticker}: {e}")
        return None

def get_quotes_batch(tickers: list) -> dict:
    if not ibkr_available(): return {}
    results = {}
    try:
        contracts = [iba.Stock(t, 'SMART', 'USD') for t in tickers]
        _ib.qualifyContracts(*contracts)
        tickers_data = _ib.reqTickers(*contracts)
        
        import math
        for t_data in tickers_data:
            t_name = t_data.contract.symbol
            last_price = t_data.last if t_data.last is not None and not math.isnan(t_data.last) else 0
            close_price = t_data.close if t_data.close is not None and not math.isnan(t_data.close) else 0
            price = last_price if last_price > 0 else close_price
            
            if price > 0:
                results[t_name] = {
                    "ticker": t_name,
                    "price": price,
                    "volume": t_data.volume if t_data.volume is not None and not math.isnan(t_data.volume) else 0
                }
            else:
                logger.warning(f"IBKR returned no valid price for {t_name} in batch. Check data subscriptions.")
        return results
    except Exception as e:
        logger.error(f"IBKR get_quotes_batch error: {e}")
        return {}

def get_price_history(ticker: str, days: int = 90) -> pd.DataFrame:
    if not ibkr_available(): return None
    try:
        contract = iba.Stock(ticker, 'SMART', 'USD')
        _ib.qualifyContracts(contract)
        duration = f"{days} D"
        bars = _ib.reqHistoricalData(
            contract, endDateTime='', durationStr=duration,
            barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
        )
        if not bars: return None
        df = iba.util.df(bars)
        df.rename(columns={'date': 'date'}, inplace=True)
        return df
    except Exception as e:
        logger.error(f"IBKR get_price_history error: {e}")
        return None

def get_intraday_history(ticker: str, days: int = 1, interval: str = "5m") -> pd.DataFrame:
    if not ibkr_available(): return None
    # Map interval '5m' to '5 mins' for IBKR
    bar_size = '5 mins'
    if interval == '1m': bar_size = '1 min'
    elif interval == '15m': bar_size = '15 mins'
    
    try:
        contract = iba.Stock(ticker, 'SMART', 'USD')
        _ib.qualifyContracts(contract)
        duration = f"{days} D"
        bars = _ib.reqHistoricalData(
            contract, endDateTime='', durationStr=duration,
            barSizeSetting=bar_size, whatToShow='TRADES', useRTH=True
        )
        if not bars: return None
        df = iba.util.df(bars)
        return df
    except Exception as e:
        logger.error(f"IBKR get_intraday_history error: {e}")
        return None

def get_option_chain(ticker: str, expiry: str = None) -> dict:
    if not ibkr_available(): return None
    try:
        contract = iba.Stock(ticker, 'SMART', 'USD')
        _ib.qualifyContracts(contract)
        chains = _ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
        if not chains: return None
        
        # Pick the SMART exchange chain
        chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
        
        # Find closest expiry
        expirations = sorted(chain.expirations)
        target_expiry = expiry if expiry and expiry.replace("-", "") in expirations else expirations[0]
        
        return {
            "expiry": target_expiry,
            "strikes": sorted(chain.strikes),
            "calls": [],
            "puts": []
        }
    except Exception as e:
        logger.error(f"IBKR get_option_chain error: {e}")
        return None
