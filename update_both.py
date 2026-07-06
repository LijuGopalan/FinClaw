import json
import yaml

tech_tickers = [
    "OPEN", "AAPL", "GOOG", "META", "MSFT", "ORCL", "AMZN", "VRT", "PLTR", 
    "QCOM", "ARM", "SOUN", "ANET", "DELL", "NVDA", "CRWV", "TSM", "AVGO", 
    "TSLA", "AMD", "SNDK", "MSTR", "SMCI", "CLSK", "ASML", "COHR", "IREN", 
    "MU", "INTC"
]

ai_infra_tickers = [
    "NBIS", "VRT", "FN", "ANET", "DELL", "AXTI", "CRWV", 
    "TSM", "AVGO", "LITE", "COHR", "CRDO", "MRVL", "AAOI"
]

# Create combined watchlist without duplicates
combined_watchlist = list(dict.fromkeys(ai_infra_tickers + tech_tickers))

# Update portfolio.json
with open('data/portfolio.json', 'r') as f:
    portfolio = json.load(f)

# Clear existing holdings to rebuild properly
new_holdings = []
added = set()

for t in ai_infra_tickers:
    new_holdings.append({
        "ticker": t,
        "shares": 10,
        "avg_cost": 100.0,
        "date_added": "2026-06-09",
        "horizon": "long-term",
        "sector": "AI Infrastructure",
        "notes": "Added from AI Infra list"
    })
    added.add(t)

for t in tech_tickers:
    if t not in added:
        new_holdings.append({
            "ticker": t,
            "shares": 10,
            "avg_cost": 100.0,
            "date_added": "2026-06-09",
            "horizon": "long-term",
            "sector": "Technology",
            "notes": "Added from Tech list"
        })
        added.add(t)

portfolio['holdings'] = new_holdings
portfolio['sector_targets'] = {
    "AI Infrastructure": 50,
    "Technology": 50
}

with open('data/portfolio.json', 'w') as f:
    json.dump(portfolio, f, indent=2)

# Update openclaw.config.yml watchlist
with open('openclaw.config.yml', 'r') as f:
    config = yaml.safe_load(f)

config['monitoring']['watchlist'] = combined_watchlist

with open('openclaw.config.yml', 'w') as f:
    yaml.dump(config, f, sort_keys=False)

print("Both portfolios restored and combined.")
