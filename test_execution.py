from skills.execution_engine import execute_trade_from_signal

mock_opportunity = {
    "ticker": "AAPL",
    "score": 95,
    "current_price": 225.50
}

print("Running Paper Trade Execution Test...")
result = execute_trade_from_signal(mock_opportunity)
print("\nResult:", result)
