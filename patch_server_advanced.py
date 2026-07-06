import os

def patch_server():
    with open('server.py', 'r') as f:
        lines = f.readlines()
        
    injection_code = """
# =====================================================================
# ADVANCED DASHBOARD ENDPOINTS (Heatmap, Rebalancer, Payoff, Sandbox)
# =====================================================================
@app.route("/api/portfolio/rebalance_simulation", methods=["POST"])
def api_portfolio_rebalance_simulation():
    try:
        from skills.financial_skills import get_portfolio
        from skills.opportunity_engine import get_opportunities
        
        portfolio = get_portfolio()
        holdings = portfolio.get("holdings", [])
        
        # Simple math logic to simulate moving allocations
        # In a real scenario we use actual Opportunity scores, here we mock the simulation logic
        
        return jsonify({
            "status": "success",
            "current_allocation": [{"ticker": h["ticker"], "shares": h["shares"], "value": h.get("current_value", 0)} for h in holdings],
            "ai_suggestion": "Reduce NVDA by 5%, Increase PLTR by 5% to reduce beta.",
            "risk_score_before": 85,
            "risk_score_after": 72
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/market/heatmap")
def api_market_heatmap():
    try:
        from skills.financial_skills import get_news
        # We will mock a quick sentiment analysis loop for the top 6 tickers
        tickers = ["NVDA", "PLTR", "AAPL", "TSLA", "CRWD", "ARM"]
        heatmap = []
        for t in tickers:
            # We mock the sentiment score to simulate the UI
            import random
            score = random.randint(-100, 100)
            heatmap.append({"ticker": t, "sentiment": score})
        return jsonify({"heatmap": heatmap})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/options/payoff", methods=["POST"])
def api_options_payoff():
    try:
        data = request.json
        ticker = data.get("ticker", "NVDA")
        strike = float(data.get("strike", 150.0))
        premium = float(data.get("premium", 5.0))
        opt_type = data.get("type", "call").lower()
        
        # Generate payoff array
        prices = [strike * (0.8 + 0.02 * i) for i in range(21)]
        payoff = []
        for p in prices:
            if opt_type == "call":
                profit = max(0, p - strike) - premium
            else:
                profit = max(0, strike - p) - premium
            payoff.append({"price": round(p, 2), "profit": round(profit * 100, 2)}) # *100 for contract multiplier
            
        return jsonify({
            "ticker": ticker,
            "strike": strike,
            "premium": premium,
            "type": opt_type,
            "payoff": payoff,
            "breakeven": strike + premium if opt_type == "call" else strike - premium
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    try:
        data = request.json
        ticker = data.get("ticker", "NVDA")
        strategy = data.get("strategy", "episodic_pivot")
        
        # In a real scenario we run historical simulation over 1 year of data.
        # We will mock the output to simulate the UI.
        import random
        win_rate = round(random.uniform(45.0, 85.0), 1)
        roi = round(random.uniform(10.0, 150.0), 1)
        
        return jsonify({
            "ticker": ticker,
            "strategy": strategy,
            "trades_executed": random.randint(5, 50),
            "win_rate": win_rate,
            "roi_pct": roi,
            "max_drawdown_pct": round(random.uniform(5.0, 25.0), 1)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

"""
    
    # Find the injection point
    for i, line in enumerate(lines):
        if 'if __name__ == "__main__":' in line:
            if "api_portfolio_rebalance_simulation" not in "".join(lines):
                lines.insert(i, injection_code)
            break
            
    with open('server.py', 'w') as f:
        f.writelines(lines)
        
    print("server.py patched with advanced endpoints.")

if __name__ == "__main__":
    patch_server()
