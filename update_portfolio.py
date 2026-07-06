import json
import yaml

tickers = [
    "OPEN", "AAPL", "GOOG", "META", "MSFT", "ORCL", "AMZN", "VRT", "PLTR", 
    "QCOM", "ARM", "SOUN", "ANET", "DELL", "NVDA", "CRWV", "TSM", "AVGO", 
    "TSLA", "AMD", "SNDK", "MSTR", "SMCI", "CLSK", "ASML", "COHR", "IREN", 
    "MU", "INTC"
]

# Update portfolio.json
with open('data/portfolio.json', 'r') as f:
    portfolio = json.load(f)

new_holdings = []
for t in tickers:
    new_holdings.append({
        "ticker": t,
        "shares": 10,
        "avg_cost": 100.0,
        "date_added": "2026-06-09",
        "horizon": "long-term",
        "sector": "Technology",
        "notes": "Added from Tech list"
    })

portfolio['holdings'] = new_holdings
portfolio['sector_targets'] = {"Technology": 100}

with open('data/portfolio.json', 'w') as f:
    json.dump(portfolio, f, indent=2)

# Update openclaw.config.yml watchlist
with open('openclaw.config.yml', 'r') as f:
    config = yaml.safe_load(f)

config['monitoring']['watchlist'] = tickers

with open('openclaw.config.yml', 'w') as f:
    yaml.dump(config, f, sort_keys=False)

print("Portfolio and config updated.")
