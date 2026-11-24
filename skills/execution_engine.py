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

    risk_gate = opportunity.get("risk_gate")
    if not isinstance(risk_gate, dict) or risk_gate.get("passed") is not True:
        vetoes = risk_gate.get("vetoes", ["Risk gate missing"]) if isinstance(risk_gate, dict) else ["Risk gate missing"]
        return {"status": "skipped", "reason": "; ".join(vetoes)}

    ticker = opportunity.get("ticker")
    price = opportunity.get("current_price") or opportunity.get("entry_high")
    if not price:
        return {"status": "skipped", "reason": "No valid entry price found"}

    # Mock buying power to give a suggested size
    buying_power = 100000 
    max_pct = config.get("max_position_size_pct", 0.05)
    try:
        from skills.volatility_regime import get_current_regime_settings
    except ImportError:
        from .volatility_regime import get_current_regime_settings
    regime = get_current_regime_settings()
    sizing_multiplier = {
        "aggressive": 1.0,
        "normal": 0.75,
        "defensive": 0.5,
    }.get(regime.get("position_sizing"), 0.5)
    cash_allocation_pct = regime.get("cash_allocation_pct", 20)
    deployable_fraction = (100 - cash_allocation_pct) / 100
    trade_size_dollars = buying_power * max_pct * sizing_multiplier * deployable_fraction
    
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
    alert_msg += (
        f"Suggested Quantity: {quantity} shares "
        f"(regime sizing: {regime.get('position_sizing', 'defensive')}, "
        f"cash reserve: {cash_allocation_pct}%)\n"
    )
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
