import pytest
from skills.financial_skills import _cache, cached, clear_cache, get_cache_stats
import time

def test_cache_hit_and_miss():
    clear_cache()
    
    call_count = 0
    @cached(ttl_seconds=10)
    def mock_fetch(ticker):
        nonlocal call_count
        call_count += 1
        return {"price": 100}
        
    # First call (miss)
    res1 = mock_fetch("AAPL")
    assert res1["price"] == 100
    assert call_count == 1
    
    # Second call (hit)
    res2 = mock_fetch("AAPL")
    assert res2["price"] == 100
    assert call_count == 1
    
def test_cache_expiration():
    clear_cache()
    
    @cached(ttl_seconds=0.1)
    def mock_fetch(ticker):
        return {"ts": time.time()}
        
    # First call
    res1 = mock_fetch("AAPL")
    
    # Sleep past TTL
    time.sleep(0.2)
    
    # Second call (expired, should miss)
    res2 = mock_fetch("AAPL")
    assert res1["ts"] != res2["ts"]
    
def test_cache_stats():
    clear_cache()
    
    @cached(ttl_seconds=10)
    def mock_fetch(ticker):
        return {"price": 100}
        
    mock_fetch("AAPL")
    mock_fetch("MSFT")
    
    stats = get_cache_stats()
    assert stats["total_entries"] == 2
    assert stats["active"] == 2
    assert stats["expired"] == 0
