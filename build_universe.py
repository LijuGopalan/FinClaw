import json
import os
import yaml

def build():
    """
    Build universe from openclaw.config.yml watchlists instead of fetching SP500.
    This keeps the tracking focused on your personal watchlist.
    """
    # Read watchlists from config
    config_path = os.path.join(
        os.path.dirname(__file__), 
        "openclaw.config.yml"
    )
    
    tickers = set()
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            
        # Extract all tickers from monitoring.watchlists
        watchlists = config.get('monitoring', {}).get('watchlists', {})
        
        for category, ticker_list in watchlists.items():
            if ticker_list:
                tickers.update(ticker_list)
                print(f"Added {len(ticker_list)} tickers from {category}")
        
        # Also add portfolio holdings if they exist
        portfolio_path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "portfolio.json"
        )
        if os.path.exists(portfolio_path):
            try:
                with open(portfolio_path, 'r') as f:
                    portfolio = json.load(f)
                holdings = portfolio.get('holdings', [])
                for holding in holdings:
                    ticker = holding.get('ticker')
                    if ticker:
                        tickers.add(ticker)
                print(f"Added {len(holdings)} tickers from portfolio")
            except Exception as e:
                print(f"Could not read portfolio: {e}")
                
    except Exception as e:
        print(f"Error reading config: {e}")
        # Fallback to a minimal set if config fails
        tickers = {"AAPL", "MSFT", "NVDA", "GOOGL"}

    # Clean and sort tickers
    clean_tickers = sorted([
        t.replace('.', '-').strip().upper() 
        for t in tickers 
        if isinstance(t, str) and t.strip()
    ])

    # Write to universe.json
    data_dir = os.path.join(
        os.path.dirname(__file__),
        "data"
    )
    os.makedirs(data_dir, exist_ok=True)
    out_file = os.path.join(data_dir, "universe.json")
    
    with open(out_file, "w") as f:
        json.dump(clean_tickers, f, indent=2)
        
    print(f"\n✅ Saved {len(clean_tickers)} tickers to {out_file}")
    print(f"Tickers: {', '.join(clean_tickers[:10])}{'...' if len(clean_tickers) > 10 else ''}")

if __name__ == "__main__":
    build()
