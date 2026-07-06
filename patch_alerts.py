import os

def patch_dashboard():
    with open('dashboard/index.html', 'r') as f:
        content = f.read()
        
    # 1. Add Navigation Buttons
    nav_buttons = """      <button class="nav-btn" id="nav-setup" onclick="showPage('setup')">⚙️ Setup</button>
      <button class="nav-btn" id="nav-alerts" onclick="showPage('alerts')">Live Alerts</button>
      <button class="nav-btn" id="nav-report" onclick="showPage('report')">AI Report Card</button>"""
    if "nav-alerts" not in content:
        content = content.replace('<button class="nav-btn" id="nav-setup" onclick="showPage(\'setup\')">⚙️ Setup</button>', nav_buttons)
        
    # 2. Add the Pages HTML
    pages_html = """
    <!-- ==========================================
         PAGE: ALERTS
    =========================================== -->
    <div class="page" id="page-alerts">
      <div class="card">
        <div class="card-title"><span class="icon">🔔</span> Live Action Alerts Feed</div>
        <div id="alertsFeedContainer">
          <div class="loading-overlay"><div class="spinner"></div></div>
        </div>
      </div>
    </div>

    <!-- ==========================================
         PAGE: REPORT CARD
    =========================================== -->
    <div class="page" id="page-report">
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">AI Win Rate</div>
          <div class="metric-value green" id="perfWinRate">—</div>
          <div class="metric-delta">Target vs Stop Hit Ratio</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Total Signals Generated</div>
          <div class="metric-value" id="perfTotalSignals">—</div>
          <div class="metric-delta">All time</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Pending Trades</div>
          <div class="metric-value yellow" id="perfPending">—</div>
          <div class="metric-delta">Currently Active</div>
        </div>
      </div>

      <div class="card" style="margin-top: 16px;">
        <div class="card-title"><span class="icon">📜</span> Signal Accountability History</div>
        <div id="performanceHistoryContainer">
          <div class="loading-overlay"><div class="spinner"></div></div>
        </div>
      </div>
    </div>
  </main>"""
    if "id=\"page-alerts\"" not in content:
        content = content.replace("  </main>", pages_html)
        
    # 3. Add JS functions
    js_functions = """
// ================================================
// ALERTS & PERFORMANCE
// ================================================
async function loadAlerts() {
  const container = document.getElementById("alertsFeedContainer");
  container.innerHTML = '<div class="loading-overlay"><div class="spinner"></div></div>';
  try {
    const res = await fetch("/api/alerts");
    const data = await res.json();
    if (!data.alerts || data.alerts.length === 0) {
      container.innerHTML = '<div style="color:var(--text-secondary);padding:20px;">No alerts generated yet.</div>';
      return;
    }
    
    // Sort by timestamp descending
    data.alerts.sort((a,b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    let html = '';
    data.alerts.forEach(alert => {
      // Determine colors based on action
      let actionColor = "var(--text-primary)";
      if (alert.message.includes("BUY")) actionColor = "var(--green)";
      if (alert.message.includes("SELL") || alert.message.includes("LIQUIDATE")) actionColor = "var(--red)";
      if (alert.message.includes("REBALANCE")) actionColor = "var(--purple)";
      
      html += `
        <div style="background:var(--bg-white); border-radius:12px; padding:16px; margin-bottom:12px; border-left:4px solid ${actionColor}; box-shadow:0 2px 8px rgba(0,0,0,0.2);">
          <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
            <strong style="color:${actionColor}; font-size:16px;">${alert.message.split('\\n')[0]}</strong>
            <span style="color:var(--text-secondary); font-size:12px;">${new Date(alert.timestamp).toLocaleString()}</span>
          </div>
          <div style="color:var(--text-secondary); font-size:14px; white-space:pre-wrap; line-height:1.5;">${alert.message.substring(alert.message.indexOf('\\n') + 1)}</div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div style="color:var(--red)">Failed to load alerts: ${err.message}</div>`;
  }
}

async function loadPerformance() {
  try {
    const res = await fetch("/api/signals/performance");
    const data = await res.json();
    
    document.getElementById("perfTotalSignals").textContent = data.total_signals;
    document.getElementById("perfPending").textContent = data.pending;
    
    if (data.resolved > 0) {
      const winRate = (data.wins / data.resolved) * 100;
      const el = document.getElementById("perfWinRate");
      el.textContent = winRate.toFixed(1) + "%";
      el.className = winRate >= 50 ? "metric-value green" : "metric-value red";
    } else {
      document.getElementById("perfWinRate").textContent = "N/A";
    }
    
    // Load history
    const container = document.getElementById("performanceHistoryContainer");
    if (!data.history || data.history.length === 0) {
      container.innerHTML = '<div style="color:var(--text-secondary);padding:20px;">No historical trades to grade yet.</div>';
      return;
    }
    
    let html = '';
    data.history.forEach(sig => {
      let badge = `<span style="background:var(--bg-pill); padding:4px 8px; border-radius:4px; font-size:12px; color:var(--text-secondary);">PENDING</span>`;
      if (sig.status === 'WIN') badge = `<span style="background:rgba(46,204,113,0.2); color:var(--green); padding:4px 8px; border-radius:4px; font-size:12px; font-weight:bold;">WIN (Hit Target)</span>`;
      if (sig.status === 'LOSS') badge = `<span style="background:rgba(231,76,60,0.2); color:var(--red); padding:4px 8px; border-radius:4px; font-size:12px; font-weight:bold;">LOSS (Hit Stop)</span>`;
      
      html += `
        <div style="padding:12px 0; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
          <div>
            <strong style="font-size:16px;">${sig.ticker}</strong> <span style="color:var(--text-secondary); font-size:13px; margin-left:8px;">${sig.action} @ $${sig.entry_price}</span>
            <div style="font-size:13px; color:var(--text-secondary); margin-top:4px;">
              Target: $${sig.target_price} | Stop: $${sig.stop_loss}
            </div>
            <div style="font-size:11px; color:var(--text-secondary); margin-top:4px;">Generated: ${new Date(sig.generated_at).toLocaleDateString()}</div>
          </div>
          <div>${badge}</div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    document.getElementById("performanceHistoryContainer").innerHTML = `<div style="color:var(--red)">Failed to load performance: ${err.message}</div>`;
  }
}

// ================================================
// INIT
// ================================================
"""
    if "loadAlerts()" not in content:
        content = content.replace("// ================================================\n// INIT\n// ================================================", js_functions)

    # 4. Add to showPage
    show_page_injection = """  if (name === 'setup') loadSystemStatus();
  if (name === 'alerts') loadAlerts();
  if (name === 'report') loadPerformance();"""
    if "name === 'alerts'" not in content:
        content = content.replace("  if (name === 'setup') loadSystemStatus();", show_page_injection)
        
    with open('dashboard/index.html', 'w') as f:
        f.write(content)
        
    print("Dashboard patched successfully!")

if __name__ == "__main__":
    patch_dashboard()
