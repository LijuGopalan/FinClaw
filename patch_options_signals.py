import re

with open('dashboard/index.html', 'r') as f:
    content = f.read()

# Patch loadOptionsFlow
old_options = """async function loadOptionsFlow() {
  const tickers = ["NVDA","AAPL","MSFT","TSLA","AMZN","META","GOOGL","SPY"];
  const allOptions = [];"""

new_options = """async function loadOptionsFlow() {
  const configRes = await api('/config/watchlist');
  const watchlists = configRes?.watchlists || {};
  let tickers = [];
  for (const list of Object.values(watchlists)) {
    tickers = tickers.concat(list);
  }
  tickers = [...new Set(tickers)];
  if (tickers.length === 0) tickers = ["NVDA","AAPL","MSFT","TSLA","AMZN","META","GOOGL","SPY"];

  const allOptions = [];"""
content = content.replace(old_options, new_options)

# Patch loadSignals
old_signals = """async function loadSignals() {
  const watchlist = ["NVDA","AAPL","MSFT","TSLA","META","GOOGL"];
  const signals = [];

  for (const t of watchlist) {"""

new_signals = """async function loadSignals() {
  const configRes = await api('/config/watchlist');
  const watchlists = configRes?.watchlists || {};
  let tickers = [];
  for (const list of Object.values(watchlists)) {
    tickers = tickers.concat(list);
  }
  tickers = [...new Set(tickers)];
  if (tickers.length === 0) tickers = ["NVDA","AAPL","MSFT","TSLA","META","GOOGL"];

  const signals = [];

  for (const t of tickers) {"""
content = content.replace(old_signals, new_signals)

with open('dashboard/index.html', 'w') as f:
    f.write(content)

print("Options and Signals JS patched.")
