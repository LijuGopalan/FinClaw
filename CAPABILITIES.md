# FinClaw AI: Application Capabilities

FinClaw is a highly advanced, institutional-grade AI financial assistant and automated trading terminal. Below is a comprehensive breakdown of its complete capabilities, encompassing the backend intelligence, API integrations, and the front-end Bloomberg-style dashboard.

---

## 🧠 1. Advanced Screening & Trading Models
FinClaw does not just track prices; it actively hunts for complex algorithmic setups using custom mathematical models:
- **Episodic Pivots (Gap & Go):** Automatically detects when a stock gaps up >10% on 3x average volume, identifying explosive earnings reactions right at the market open.
- **Minervini VCP (Volatility Contraction Pattern):** Scans for consolidating price action and volume dry-ups to pinpoint high-probability breakout buy points.
- **Mean Reversion (Rubber Band):** Identifies stocks that are stretched too far (>15%) below their 10-day Exponential Moving Average (EMA) with an RSI < 25 for quick bounce scalps.
- **Options Gamma Walls (GEX):** Utilizing a local Black-Scholes pricing model, FinClaw downloads live open interest to calculate precise Gamma Exposure, identifying hidden Market Maker Support and Resistance levels.
- **Dark Pool Proxy Detection:** Scans 5-minute intraday charts for massive volume anomalies (>5x standard deviation) to reverse-engineer institutional off-exchange block trades.

## 🛡️ 2. Dynamic Portfolio Management
FinClaw actively protects your wealth rather than just providing buy signals:
- **Live P&L Tracking:** Syncs with your portfolio to track real-time cost basis and performance.
- **Dynamic Trailing Stops (Chandelier Exit):** Employs Average True Range (ATR) mathematics to dynamically raise your stop-loss as your stocks climb in profit, locking in gains automatically.
- **Interactive Rebalancer:** Analyzes your current sector weighting and suggests exact allocation changes (e.g., "Reduce NVDA by 5%, Increase PLTR by 5%") to mathematically lower your portfolio's Beta and Risk Score.

## 📊 3. The Dashboard (UI/UX)
The FinClaw Web Dashboard (`http://localhost:5001`) operates as a modern Bloomberg Terminal replacement, featuring multiple interactive modules:
- **Live Alerts Feed:** A scrolling, color-coded feed of all active signals (🟢 BUY, 🔴 SELL, 🟣 REBALANCE).
- **The Fear Matrix (Sentiment Heatmap):** A live visual grid that scrapes the latest news for your watchlists and runs AI sentiment analysis, glowing bright green for bullish momentum or deep red for bearish news.
- **Options PnL Payoff Visualizer:** Dynamically graphs your theoretical Profit & Loss and exact break-even point for any options trade before you execute it.
- **Backtesting Sandbox:** A simulation engine allowing you to test FinClaw's logic against historical data to find the theoretical Win Rate, ROI, and Max Drawdown of any strategy.
- **AI Accountability Report Card:** The system mathematically grades its own past alerts (Target vs. Stop Hit Ratio), providing full transparency into the AI's actual Win Rate.

## 🔍 4. Fundamental & Macro Analysis
FinClaw pulls and interprets vast amounts of market data:
- **Congressional & Insider Trading:** Tracks daily disclosures from politicians (e.g., Nancy Pelosi) and corporate insiders to spot "Smart Money" accumulation.
- **ARK Invest Tracking:** Monitors daily ETF trades from Cathie Wood and ARK funds.
- **Macro Environment:** Analyzes Treasury Yields, the Dollar Index (DXY), VIX, and Sector Rotation data to adjust its risk tolerance (e.g., moving to defensive mode during inverted yield curves).

## 🤖 5. Telegram Integration
FinClaw can push its highest-conviction alerts directly to your mobile device via Telegram, ensuring you never miss a breakout or a critical stop-loss liquidation while away from the terminal.
