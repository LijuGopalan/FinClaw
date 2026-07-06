import yaml

with open('openclaw.config.yml', 'r') as f:
    config = yaml.safe_load(f)

# Extract old flat list and split
flat_list = config['monitoring'].pop('watchlist', [])
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

config['monitoring']['watchlists'] = {
    "Technology": tech_tickers,
    "AI Infrastructure": ai_infra_tickers
}

with open('openclaw.config.yml', 'w') as f:
    yaml.dump(config, f, sort_keys=False)

print("Updated config with watchlists dictionary.")
