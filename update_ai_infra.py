import json
import yaml

tickers = [
    "NBIS", "VRT", "FN", "ANET", "DELL", "AXTI", "CRWV", 
    "TSM", "AVGO", "LITE", "COHR", "CRDO", "MRVL", "AAOI"
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
        "sector": "AI Infrastructure",
        "notes": "Added from AI Infra list"
    })

portfolio['holdings'] = new_holdings
portfolio['sector_targets'] = {"AI Infrastructure": 100}

with open('data/portfolio.json', 'w') as f:
    json.dump(portfolio, f, indent=2)

# Update openclaw.config.yml watchlist
with open('openclaw.config.yml', 'r') as f:
    config = yaml.safe_load(f)

config['monitoring']['watchlist'] = tickers

with open('openclaw.config.yml', 'w') as f:
    yaml.dump(config, f, sort_keys=False)

print("AI Infra portfolio and config updated.")
