import json
import os
import urllib.request
import pandas as pd

def fetch_wiki_table(url, table_index=0, column='Symbol'):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read()
        tables = pd.read_html(html)
        return tables[table_index][column].tolist()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

def build():
    tickers = set()
    
    # S&P 500
    sp500 = fetch_wiki_table('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 0, 'Symbol')
    tickers.update(sp500)
    
    # Nasdaq 100
    nasdaq = fetch_wiki_table('https://en.wikipedia.org/wiki/Nasdaq-100', 4, 'Ticker')
    tickers.update(nasdaq)
    
    # Add some popular ETFs and extra tech names
    fallback = ["SPY", "QQQ", "IWM", "DIA", "SMH", "ARKK", "XLK", "XLF", "XLE", "PLTR", "SOFI", "RIVN", "LCID", "MARA", "RIOT", "COIN", "U", "DKNG", "PTON", "HOOD", "BABA", "JD", "BIDU", "PDD", "NIO", "XPEV", "LI", "MSTR", "CVNA"]
    tickers.update(fallback)

    # Clean tickers
    clean_tickers = []
    for t in tickers:
        if isinstance(t, str) and len(t) <= 5:
            clean_tickers.append(t.replace('.', '-').strip().upper())

    data_dir = "/Users/adgroup/.gemini/antigravity/scratch/openclaw-financial-assistant/data"
    os.makedirs(data_dir, exist_ok=True)
    out_file = os.path.join(data_dir, "universe.json")
    
    with open(out_file, "w") as f:
        json.dump(clean_tickers, f)
        
    print(f"Saved {len(clean_tickers)} tickers to {out_file}")

if __name__ == "__main__":
    build()
