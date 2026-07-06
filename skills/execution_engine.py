import os
import yaml
from skills.portfolio_manager import calculate_trailing_stop
# We use FinClaw's notification system for alerts
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "openclaw.config.yml")

def load_execution_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f) or {}
            return config.get("execution", {})
    except Exception:
        return {}

def execute_trade_from_signal(opportunity):
    """
    Takes a high-probability ML opportunity and generates a detailed manual trading alert.
    No live execution is performed.
    """
    config = load_execution_config()
    
    score = opportunity.get("score", 0)
    if score < 70:
        return {"status": "skipped", "reason": f"Score {score} too low for priority alert"}

    ticker = opportunity.get("ticker")
    price = opportunity.get("current_price") or opportunity.get("entry_high")
    if not price:
        return {"status": "skipped", "reason": "No valid entry price found"}

    # Mock buying power to give a suggested size
    buying_power = 100000 
    max_pct = config.get("max_position_size_pct", 0.05)
    trade_size_dollars = buying_power * max_pct
    
    quantity = int(trade_size_dollars / price)

    stop_data = calculate_trailing_stop(ticker)
    stop_loss = round(price * 0.95, 2)
    if stop_data and "trailing_stop" in stop_data:
        stop_loss = stop_data["trailing_stop"]
        
    # Ensure stop loss is actually below the entry price for a long position
    if stop_loss >= price:
        stop_loss = round(price * 0.95, 2)
        
    risk = price - stop_loss
    take_profit = round(price + (risk * 2), 2)
    
    # Format the alert
    alert_msg = f"🔥 HIGH CONVICTION ML SIGNAL 🔥\n\n"
    alert_msg += f"Ticker: {ticker}\n"
    alert_msg += f"Action: BUY LIMIT @ ${price}\n"
    alert_msg += f"Suggested Quantity: {quantity} shares (Based on 5% sizing)\n"
    alert_msg += f"Stop Loss: ${stop_loss} (Dynamic ATR)\n"
    alert_msg += f"Take Profit: ${take_profit} (2:1 R/R)\n"
    alert_msg += f"ML Score: {score}/100"
    
    print("\n[MANUAL TRADING ALERT GENERATED]")
    print("==========================================")
    print(alert_msg)
    print("==========================================\n")
    
    # Here you would route to telegram using your notifications module, 
    # e.g., notifications.send_telegram_message(alert_msg)
    
    return {"status": "alert_sent", "message": alert_msg}
