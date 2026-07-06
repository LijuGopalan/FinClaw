import re

with open('dashboard/index.html', 'r') as f:
    content = f.read()

# Patch 1: Replace portfolio table with container
old_portfolio_html = """        <div class="card" style="grid-column: span 2">
          <div class="card-title"><span class="icon">💼</span> Current Holdings</div>
          <table class="portfolio-table">
            <thead>
              <tr><th>Holding</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Return</th><th>Weight</th><th>Today</th></tr>
            </thead>
            <tbody id="portfolioBody">
              <tr><td colspan="8"><div class="loading-overlay"><div class="spinner"></div> Loading portfolio...</div></td></tr>
            </tbody>
          </table>"""
new_portfolio_html = """        <div class="card" style="grid-column: span 2">
          <div class="card-title"><span class="icon">💼</span> Current Holdings</div>
          <div id="portfolioTablesContainer">
            <table class="portfolio-table">
              <thead>
                <tr><th>Holding</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Return</th><th>Weight</th><th>Today</th></tr>
              </thead>
              <tbody>
                <tr><td colspan="8"><div class="loading-overlay"><div class="spinner"></div> Loading portfolio...</div></td></tr>
              </tbody>
            </table>
          </div>"""
content = content.replace(old_portfolio_html, new_portfolio_html)

# Patch 2: Update loadPortfolio JS
old_js = """  if (holdings.length === 0) {
    document.getElementById("portfolioBody").innerHTML = `<tr><td colspan="8" style="text-align:center;padding:36px;color:var(--text-tertiary)">
      📂 No holdings found. Add your stocks to <code style="color:var(--accent)">data/portfolio.json</code>
    </td></tr>`;
  } else {
    document.getElementById("portfolioBody").innerHTML = holdings.map(h => `
      <tr class="portfolio-row" onclick="loadChart('${h.ticker}')">
        <td><div class="ticker-cell"><span class="symbol">${h.ticker}</span><span class="name">${h.sector || ''}</span></div></td>
        <td class="price-mono">${h.shares}</td>
        <td class="price-mono">$${h.avg_cost.toFixed(2)}</td>
        <td class="price-mono">$${(h.current_price || 0).toFixed(2)}</td>
        <td class="price-mono">$${(h.current_value || 0).toFixed(2)}</td>
        <td class="price-mono ${h.gain_loss >= 0 ? 'up' : 'down'}">${h.gain_loss >= 0 ? '+' : ''}${(h.gain_loss || 0).toFixed(2)} (${h.gain_loss_pct >= 0 ? '+' : ''}${(h.gain_loss_pct || 0).toFixed(1)}%)</td>
        <td class="price-mono" style="color:var(--text-tertiary)">${(h.weight_pct || 0).toFixed(1)}%</td>
        <td class="price-mono ${(h.change_today || 0) >= 0 ? 'up' : 'down'}">${(h.change_today || 0) >= 0 ? '+' : ''}${(h.change_today || 0).toFixed(2)}%</td>
      </tr>
    `).join("");
  }"""

new_js = """  if (holdings.length === 0) {
    document.getElementById("portfolioTablesContainer").innerHTML = `
      <table class="portfolio-table">
        <tbody>
          <tr><td colspan="8" style="text-align:center;padding:36px;color:var(--text-tertiary)">
            📂 No holdings found. Add your stocks to <code style="color:var(--accent)">data/portfolio.json</code>
          </td></tr>
        </tbody>
      </table>
    `;
  } else {
    const holdingsBySector = holdings.reduce((acc, h) => {
      const sector = h.sector || 'Other';
      if (!acc[sector]) acc[sector] = [];
      acc[sector].push(h);
      return acc;
    }, {});

    let tablesHTML = "";
    for (const [sector, sectorHoldings] of Object.entries(holdingsBySector)) {
      const rowsHTML = sectorHoldings.map(h => `
        <tr class="portfolio-row" onclick="loadChart('${h.ticker}')">
          <td><div class="ticker-cell"><span class="symbol">${h.ticker}</span></div></td>
          <td class="price-mono">${h.shares}</td>
          <td class="price-mono">$${h.avg_cost.toFixed(2)}</td>
          <td class="price-mono">$${(h.current_price || 0).toFixed(2)}</td>
          <td class="price-mono">$${(h.current_value || 0).toFixed(2)}</td>
          <td class="price-mono ${h.gain_loss >= 0 ? 'up' : 'down'}">${h.gain_loss >= 0 ? '+' : ''}${(h.gain_loss || 0).toFixed(2)} (${h.gain_loss_pct >= 0 ? '+' : ''}${(h.gain_loss_pct || 0).toFixed(1)}%)</td>
          <td class="price-mono" style="color:var(--text-tertiary)">${(h.weight_pct || 0).toFixed(1)}%</td>
          <td class="price-mono ${(h.change_today || 0) >= 0 ? 'up' : 'down'}">${(h.change_today || 0) >= 0 ? '+' : ''}${(h.change_today || 0).toFixed(2)}%</td>
        </tr>
      `).join("");

      tablesHTML += `
        <div style="margin-top: 24px; margin-bottom: 8px; font-weight: 600; font-size: 15px; color: var(--text-primary); border-bottom: 1px solid rgba(0,0,0,0.06); padding-bottom: 4px;">${sector}</div>
        <table class="portfolio-table">
          <thead>
            <tr><th>Holding</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Return</th><th>Weight</th><th>Today</th></tr>
          </thead>
          <tbody>
            ${rowsHTML}
          </tbody>
        </table>
      `;
    }
    document.getElementById("portfolioTablesContainer").innerHTML = tablesHTML;
  }"""

content = content.replace(old_js, new_js)

with open('dashboard/index.html', 'w') as f:
    f.write(content)

print("index.html patched.")
