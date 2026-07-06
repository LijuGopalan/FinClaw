# FinClaw — OpenClaw Financial Assistant
# ============================================
# Your AI-powered financial intelligence agent

**FinClaw** is an OpenClaw agent configured as a personal financial assistant. It monitors markets daily, analyzes options flow, tracks your portfolio, and provides AI-driven buy/sell/hold recommendations.

---

## 📁 Project Structure

```
openclaw-financial-assistant/
├── SOUL.md                    ← Agent persona & rules (the "brain")
├── openclaw.config.yml        ← All configuration settings
├── .env.example               ← API keys template (copy to .env)
├── requirements.txt           ← Python dependencies
├── README.md                  ← This file
│
├── skills/
│   └── financial_skills.py   ← Python tools the agent calls
│
├── data/
│   └── portfolio.json         ← YOUR portfolio holdings (edit this!)
│
└── dashboard/
    └── index.html             ← Interactive web dashboard (open in browser)
```

---

## 🚀 Quick Start

### Step 1 — Install OpenClaw
```bash
git clone https://github.com/openclaw/openclaw.git
cd openclaw
corepack enable && pnpm install
```

### Step 2 — Set up this project
```bash
# Copy this folder into your OpenClaw agents directory
cp -r openclaw-financial-assistant/ <path-to-openclaw>/agents/

# Set up environment
cd <path-to-openclaw>/agents/openclaw-financial-assistant
cp .env.example .env
# Edit .env with your actual API keys
```

### Step 3 — Install Python dependencies
```bash
pip install -r requirements.txt

# Test the skills work
python skills/financial_skills.py
```

### Step 4 — Add your portfolio
Edit `data/portfolio.json` with your actual stock holdings, cost basis, and investment horizon.

### Step 5 — Start the Backend Server & Open the Dashboard
```bash
# Start the Flask API server
python server.py

# Then open the dashboard in your browser:
# http://localhost:5001
```

### Step 6 — Launch the Agent
```bash
cd <path-to-openclaw>
pnpm openclaw start \
  --agent agents/openclaw-financial-assistant \
  --soul agents/openclaw-financial-assistant/SOUL.md \
  --config agents/openclaw-financial-assistant/openclaw.config.yml
```

---

## 💳 Recommended API Subscriptions

| Service | Plan | Monthly Cost | What You Get |
|---------|------|-------------|--------------|
| **Anthropic** (Claude) | Pay-as-you-go | ~$15–30 | AI reasoning & analysis |
| **Alpha Vantage** | Free | $0 | Stock quotes, 25 calls/day |
| **Alpha Vantage** | Premium | $50 | Options data + fundamentals |
| **Tradier** | Free* | $0* | Real-time + full options chains |
| **NewsAPI** | Dev (free) | $0 | 100 news calls/day |

> 💡 **Best deal:** Open a Tradier brokerage account (funded) → get their API free. This gives you real-time options chains at no monthly cost.

> 💡 **Minimum viable setup:** Anthropic API key + Alpha Vantage free key = ~$15–30/mo total.

---

## 🧠 Recommended AI Model Configuration

For financial analysis, use a **tiered model strategy**:

| Task | Model | Why |
|------|-------|-----|
| Complex analysis, portfolio advice, options interpretation | **Claude Sonnet 4.5** (Primary) | Best nuance, long context, avoids hallucination |
| Quick quotes, alerts, news summaries | **Claude Haiku 3.5** (Secondary) | Fast, cheap ($0.80/MTok) |
| Complex quantitative math (optional) | **GPT-5.4** (Alt) | Strongest multi-step reasoning |

### Model Settings for Finance
```yaml
temperature: 0.1    # Low = consistent, factual outputs (critical for finance)
max_tokens: 8192    # Enough for full portfolio analysis
```

---

## 🎯 What the Agent Does

### Daily Routine
| Time (ET) | Task |
|-----------|------|
| 9:15 AM | Pre-market scan — futures, overnight news, earnings |
| 9:30 AM | **Morning Brief** — top movers, sector flow, portfolio check |
| 12:00 PM | Midday scan — unusual options activity |
| 4:00 PM | **Market Close Summary** — winners/losers, next-day watchlist |

### Capabilities
- ✅ Real-time stock price quotes
- ✅ Options chain analysis (calls/puts, volume, OI, put/call ratio)
- ✅ Unusual options activity detection (> 3x normal volume)
- ✅ Technical analysis (RSI, MACD, Bollinger Bands, moving averages)
- ✅ Fundamental analysis (Valuation, profitability, growth, debt)
- ✅ Insider trading activity & smart money tracking
- ✅ Macro indicators (Yield curve, commodities, sector rotation)
- ✅ Fear & Greed index for market sentiment
- ✅ Portfolio P&L tracking with enriched live prices
- ✅ Market news aggregation
- ✅ Earnings calendar
- ✅ Buy/sell/hold recommendations with confidence scores
- ✅ Ranked opportunity scans for pre-market, intraday scalp, post-market, swing, and long-term ideas
- ✅ Telegram / Email / Slack notifications
- ✅ Interactive web dashboard powered by a Flask REST API & SQLite
- ✅ Interactive TradingView charts

### Opportunity Scanner API
```bash
# Ranked watchlist scan for the current market session
curl "http://localhost:5001/api/opportunities?session=auto&horizon=auto"

# Intraday scalp scan
curl "http://localhost:5001/api/opportunities?session=regular&horizon=scalp&min_score=45"

# Save a scheduled-style scan and optionally send an alert
curl -X POST "http://localhost:5001/api/opportunities/scan" \
  -H "Content-Type: application/json" \
  -d '{"session":"premarket","horizon":"swing","notify":false}'
```

---

## ⚡ Performance & AI Architecture

FinClaw is built for speed and efficiency, utilizing a **Hybrid AI Pipeline** and **Aggressive Multithreading** to maximize the hardware utilization of modern machines (like Apple Silicon Mac Minis).

### 1. Hardware Utilization (Multithreading)
Instead of processing financial data sequentially, FinClaw uses Python's `ThreadPoolExecutor` (configured with up to 40 concurrent workers) to blast through I/O-bound tasks. It concurrently fetches live quotes, options chains, and technical indicators for your entire watchlist simultaneously, reducing scan times from minutes to seconds.

### 2. Hybrid AI (XGBoost + LLM)
To save on expensive LLM token costs and reduce latency, FinClaw uses a **two-stage filtering pipeline**:
1. **Local ML Model (Pre-filter):** An internal XGBoost classifier (`finclaw_xgb.json`) instantly evaluates hundreds of technical indicators (RSI, MACD, Volume Spikes) locally on your machine, assigning a probability score to every setup.
2. **Generative LLM (Analysis):** Only the highest-conviction opportunities (the "cream of the crop") are packaged and sent to the LLM (Gemini/Claude). The LLM is then used exclusively for what it does best: qualitative reasoning, analyzing fundamental context, interpreting market sentiment, and writing the final human-readable brief.

---

## ⚠️ Disclaimer

FinClaw is an AI-powered analysis tool for **educational and informational purposes only**. It is **NOT** a licensed financial advisor. All outputs, signals, and recommendations should be verified independently. **Never make investment decisions based solely on AI output.** Always consult a licensed financial advisor before making investment decisions.

---

## 📬 Notifications Setup

### Telegram (Recommended — free, mobile alerts)
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Create a new bot → get your token
3. Start a chat with your bot → get your `chat_id`
4. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

---

## 🔒 Security Notes

- **Never commit your `.env` file** — it's gitignored by default
- Run this agent on an **isolated machine or VPS**, not your main computer
- Use Docker or a virtual environment for isolation
- Never give the agent permission to execute actual trades
