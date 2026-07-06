import os

def patch_ui():
    with open('dashboard/index.html', 'r') as f:
        content = f.read()

    # 1. Add Sandbox Tab
    nav_sandbox = """      <button class="nav-btn" id="nav-report" onclick="showPage('report')">AI Report Card</button>
      <button class="nav-btn" id="nav-sandbox" onclick="showPage('sandbox')">🧪 Sandbox</button>"""
    if "nav-sandbox" not in content:
        content = content.replace('<button class="nav-btn" id="nav-report" onclick="showPage(\'report\')">AI Report Card</button>', nav_sandbox)

    sandbox_html = """
    <!-- ==========================================
         PAGE: SANDBOX (Backtesting)
    =========================================== -->
    <div class="page" id="page-sandbox">
      <div class="card">
        <div class="card-title"><span class="icon">🧪</span> AI Backtesting Sandbox</div>
        <div style="margin-bottom:16px;">
          <input type="text" id="sandboxTicker" class="search-bar" placeholder="Ticker (e.g. NVDA)" style="width:120px; display:inline-block; margin-right:8px;">
          <select id="sandboxStrategy" class="search-bar" style="width:200px; display:inline-block; margin-right:8px;">
            <option value="episodic_pivot">Episodic Pivot (Gap & Go)</option>
            <option value="mean_reversion">Mean Reversion</option>
            <option value="vcp">Minervini VCP</option>
          </select>
          <button onclick="runBacktest()" class="action-btn" style="padding:10px 16px;">Run Simulation</button>
        </div>
        <div id="sandboxResults" style="display:none;">
          <div class="metrics-grid">
            <div class="metric-card"><div class="metric-label">Win Rate</div><div class="metric-value green" id="sandboxWinRate">—</div></div>
            <div class="metric-card"><div class="metric-label">Theoretical ROI</div><div class="metric-value green" id="sandboxROI">—</div></div>
            <div class="metric-card"><div class="metric-label">Max Drawdown</div><div class="metric-value red" id="sandboxDrawdown">—</div></div>
          </div>
        </div>
      </div>
    </div>
  </main>"""
    if "id=\"page-sandbox\"" not in content:
        content = content.replace("  </main>", sandbox_html)
        
    # 2. Rebalancer (Inject into Portfolio Tab)
    rebalancer_html = """
        <div class="card" style="margin-top:16px; background: linear-gradient(145deg, var(--bg-white) 0%, rgba(138,43,226,0.05) 100%);">
          <div class="card-title"><span class="icon">⚖️</span> AI Portfolio Rebalancer</div>
          <button onclick="loadRebalancer()" class="action-btn" style="margin-bottom:16px; background:var(--purple);">Generate Simulation</button>
          <div id="rebalancerResults" style="display:none; padding:16px; border:1px solid var(--purple); border-radius:8px;">
            <div style="color:var(--purple); font-weight:bold; margin-bottom:12px;" id="rebalanceSuggestion"></div>
            <div style="display:flex; justify-content:space-between;">
              <div style="color:var(--text-secondary);">Risk Score Before: <strong style="color:var(--red);" id="riskBefore"></strong></div>
              <div style="color:var(--text-secondary);">Risk Score After: <strong style="color:var(--green);" id="riskAfter"></strong></div>
            </div>
          </div>
        </div>
      </div>"""
    if "AI Portfolio Rebalancer" not in content:
        content = content.replace('      </div>\n    </div>\n\n    <!-- ==========================================\n         PAGE: OPTIONS', rebalancer_html + '\n    </div>\n\n    <!-- ==========================================\n         PAGE: OPTIONS')

    # 3. Sentiment Heatmap (Inject into Dashboard Tab)
    heatmap_html = """
        <div class="card" style="grid-column: 1 / -1;">
          <div class="card-title"><span class="icon">🌡️</span> The Fear Matrix (Live Sentiment)</div>
          <button onclick="loadHeatmap()" class="action-btn" style="margin-bottom:12px;">Scan Sentiment</button>
          <div id="heatmapGrid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(100px, 1fr)); gap:8px;"></div>
        </div>
      </div>
    </div>"""
    if "The Fear Matrix" not in content:
        content = content.replace('      </div>\n    </div>\n\n    <!-- ==========================================\n         PAGE: OPPORTUNITIES', heatmap_html + '\n    <!-- ==========================================\n         PAGE: OPPORTUNITIES')
        
    # 4. Options Visualizer (Inject into Options Tab)
    payoff_html = """
        <div class="card" style="margin-top:16px;">
          <div class="card-title"><span class="icon">📈</span> Payoff Visualizer</div>
          <div style="margin-bottom:16px;">
            <input type="text" id="payoffTicker" class="search-bar" placeholder="Ticker" style="width:80px; display:inline-block; margin-right:8px;">
            <input type="number" id="payoffStrike" class="search-bar" placeholder="Strike" style="width:80px; display:inline-block; margin-right:8px;">
            <input type="number" id="payoffPremium" class="search-bar" placeholder="Premium" style="width:80px; display:inline-block; margin-right:8px;">
            <select id="payoffType" class="search-bar" style="width:80px; display:inline-block; margin-right:8px;"><option value="call">Call</option><option value="put">Put</option></select>
            <button onclick="loadPayoff()" class="action-btn" style="padding:10px 16px;">Graph</button>
          </div>
          <div id="payoffContainer" style="display:none; height:150px; border-bottom:1px solid var(--border); display:flex; align-items:flex-end; gap:4px; padding-bottom:2px;"></div>
          <div id="payoffLabels" style="display:none; text-align:center; color:var(--text-secondary); font-size:12px; margin-top:8px;"></div>
        </div>
      </div>"""
    if "Payoff Visualizer" not in content:
        content = content.replace('      </div>\n    </div>\n\n    <!-- ==========================================\n         PAGE: SIGNALS', payoff_html + '\n    <!-- ==========================================\n         PAGE: SIGNALS')

    # 5. JS Functions
    js_functions = """
// ================================================
// ADVANCED TOOLS (Sandbox, Rebalancer, Heatmap, Payoff)
// ================================================
async function loadRebalancer() {
  const btn = event.target;
  btn.innerText = "Simulating...";
  try {
    const res = await fetch("/api/portfolio/rebalance_simulation", {method:"POST"});
    const data = await res.json();
    document.getElementById("rebalancerResults").style.display = "block";
    document.getElementById("rebalanceSuggestion").innerText = data.ai_suggestion;
    document.getElementById("riskBefore").innerText = data.risk_score_before;
    document.getElementById("riskAfter").innerText = data.risk_score_after;
  } catch(e) {}
  btn.innerText = "Generate Simulation";
}

async function loadHeatmap() {
  const btn = event.target;
  btn.innerText = "Scanning...";
  try {
    const res = await fetch("/api/market/heatmap");
    const data = await res.json();
    let html = '';
    data.heatmap.forEach(h => {
      let color = "rgba(46,204,113,0.8)"; // green
      if (h.sentiment < -50) color = "rgba(231,76,60,0.8)"; // red
      else if (h.sentiment < 0) color = "rgba(231,76,60,0.4)"; // light red
      else if (h.sentiment < 50) color = "rgba(46,204,113,0.4)"; // light green
      html += `<div style="background:${color}; padding:16px 8px; border-radius:8px; text-align:center; color:white; font-weight:bold; box-shadow:0 2px 4px rgba(0,0,0,0.2);">${h.ticker}<br><span style="font-size:10px;">${h.sentiment}</span></div>`;
    });
    document.getElementById("heatmapGrid").innerHTML = html;
  } catch(e) {}
  btn.innerText = "Scan Sentiment";
}

async function loadPayoff() {
  const ticker = document.getElementById("payoffTicker").value;
  const strike = document.getElementById("payoffStrike").value;
  const premium = document.getElementById("payoffPremium").value;
  const type = document.getElementById("payoffType").value;
  if (!ticker || !strike || !premium) return;
  
  try {
    const res = await fetch("/api/options/payoff", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ticker, strike, premium, type})
    });
    const data = await res.json();
    const c = document.getElementById("payoffContainer");
    c.style.display = "flex";
    c.innerHTML = "";
    
    // Simple bar chart mapping
    let maxProfit = Math.max(...data.payoff.map(p => p.profit));
    let minProfit = Math.min(...data.payoff.map(p => p.profit));
    let range = maxProfit - minProfit;
    
    data.payoff.forEach(p => {
      let height = Math.abs(p.profit) / (range || 1) * 100;
      let color = p.profit >= 0 ? "var(--green)" : "var(--red)";
      let bar = `<div style="flex:1; background:${color}; height:${Math.max(2, height)}%; border-radius:2px 2px 0 0;" title="Price $${p.price} -> PnL $${p.profit}"></div>`;
      c.innerHTML += bar;
    });
    document.getElementById("payoffLabels").style.display = "block";
    document.getElementById("payoffLabels").innerHTML = `Breakeven: $${data.breakeven} | Hover bars to see PnL`;
  } catch(e) {}
}

async function runBacktest() {
  const ticker = document.getElementById("sandboxTicker").value;
  const strategy = document.getElementById("sandboxStrategy").value;
  const btn = event.target;
  if (!ticker) return;
  
  btn.innerText = "Simulating 1 Year...";
  try {
    const res = await fetch("/api/backtest", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ticker, strategy})
    });
    const data = await res.json();
    document.getElementById("sandboxResults").style.display = "block";
    document.getElementById("sandboxWinRate").innerText = data.win_rate + "%";
    document.getElementById("sandboxROI").innerText = "+" + data.roi_pct + "%";
    document.getElementById("sandboxDrawdown").innerText = "-" + data.max_drawdown_pct + "%";
  } catch(e) {}
  btn.innerText = "Run Simulation";
}

"""
    if "loadHeatmap()" not in content:
        content = content.replace("// ================================================\n// INIT", js_functions + "\n// ================================================\n// INIT")

    # Add to showPage
    if "name === 'sandbox'" not in content:
        content = content.replace("  if (name === 'report') loadPerformance();", "  if (name === 'report') loadPerformance();\n  if (name === 'sandbox') {}")

    with open('dashboard/index.html', 'w') as f:
        f.write(content)

    print("Dashboard UI patched with 4 advanced modules!")

if __name__ == "__main__":
    patch_ui()
