import os
import requests
import json
from datetime import datetime

class TradierClient:
    def __init__(self, paper_trading=True):
        self.paper_trading = paper_trading
        
        # Load API keys and Account ID from env
        self.api_key = self._load_env("TRADIER_API_KEY")
        self.account_id = self._load_env("TRADIER_ACCOUNT_ID")
        
        # Determine Base URL
        if self.paper_trading:
            self.base_url = "https://sandbox.tradier.com/v1"
        else:
            self.base_url = "https://api.tradier.com/v1"
            
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json'
        }

    def _load_env(self, key):
        val = os.environ.get(key)
        if not val:
            try:
                # Fallback to .env file reading
                env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
                with open(env_path, "r") as f:
                    for line in f:
                        if line.startswith(f"{key}="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except:
                pass
        return val

    def get_account_balances(self):
        """Fetch current account balances and purchasing power."""
        if not self.api_key or not self.account_id:
            return {"error": "Tradier API Key or Account ID missing"}
            
        url = f"{self.base_url}/accounts/{self.account_id}/balances"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json().get('balances', {})
        except Exception as e:
            return {"error": str(e)}

    def place_equity_order(self, symbol, side, quantity, order_type="market", price=None, stop=None, time_in_force="day"):
        """
        Place an equity order. 
        Supported order_types: market, limit, stop, stop_limit, market_on_close
        """
        if not self.api_key or not self.account_id:
            return {"error": "Tradier API Key or Account ID missing"}
            
        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        
        data = {
            'class': 'equity',
            'symbol': symbol,
            'side': side,  # 'buy', 'buy_to_cover', 'sell', 'sell_short'
            'quantity': str(quantity),
            'type': order_type,
            'duration': time_in_force
        }
        
        if price is not None:
            data['price'] = str(price)
        if stop is not None:
            data['stop'] = str(stop)

        try:
            response = requests.post(url, headers=self.headers, data=data)
            response.raise_for_status()
            return response.json().get('order', {})
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f" - {e.response.text}"
            return {"error": error_msg}

    def place_oco_bracket(self, symbol, quantity, limit_price, take_profit, stop_loss):
        """
        Place an OCO (One-Cancels-Other) Bracket order.
        Usually used to enter a position with a limit order, and immediately attach a take-profit and stop-loss.
        """
        if not self.api_key or not self.account_id:
            return {"error": "Tradier API Key or Account ID missing"}
            
        url = f"{self.base_url}/accounts/{self.account_id}/orders"
        
        # In a real Tradier OCO/OTOCO integration, we use the multileg/advanced orders endpoint.
        # For simplicity in this demo, we simulate a basic multi-leg API payload.
        # A true OTOCO (One-Triggers-One-Cancels-Other) payload looks like:
        data = {
            'class': 'otoco',
            'duration': 'day',
            'symbol': symbol,
            'type[0]': 'limit',
            'price[0]': str(limit_price),
            'side[0]': 'buy',
            'quantity[0]': str(quantity),
            
            'type[1]': 'limit',
            'price[1]': str(take_profit),
            'side[1]': 'sell',
            'quantity[1]': str(quantity),
            
            'type[2]': 'stop',
            'stop[2]': str(stop_loss),
            'side[2]': 'sell',
            'quantity[2]': str(quantity)
        }

        try:
            response = requests.post(url, headers=self.headers, data=data)
            response.raise_for_status()
            return response.json().get('order', {})
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f" - {e.response.text}"
            return {"error": error_msg}
