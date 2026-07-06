import re

with open('dashboard/index.html', 'r') as f:
    content = f.read()

old_js = """    let tablesHTML = "";
    for (const [sector, sectorHoldings] of Object.entries(holdingsBySector)) {
      const rowsHTML = sectorHoldings.map(h => `
        <tr class="portfolio-row" onclick="loadChart('${h.ticker}')">
          <td><div class="ticker-cell"><span class="symbol">${h.ticker}</span></div></td>
          <td class="price-mono">${h.shares}</td>
          <td class="price-mono">$${h.avg_cost.toFixed(2)}</td>
          <td class="price-mono">$${(h.current_price || 0).toFixed(2)}</td>
          <td class="price-mono">$${(h.current_value || 0).toFixed(2)}</td>
          <td class="price-mono ${h.gain_loss >= 0 ? 'up' : 'down'}">${h.gain_loss >= 0 ? '+' : ''}$${(h.gain_loss || 0).toFixed(2)} (${h.gain_loss_pct >= 0 ? '+' : ''}${(h.gain_loss_pct || 0).toFixed(1)}%)</td>
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
    document.getElementById("portfolioTablesContainer").innerHTML = tablesHTML;"""

new_js = """    let tabsHTML = '<div class="inner-nav">';
    let contentHTML = "";
    let isFirst = true;

    for (const [sector, sectorHoldings] of Object.entries(holdingsBySector)) {
      const safeId = sector.replace(/\s+/g, '-').toLowerCase();
      tabsHTML += `<button class="inner-nav-btn portfolio-tab-btn ${isFirst ? 'active' : ''}" id="btn-portfolio-${safeId}" onclick="switchPortfolioTab('${safeId}')">${sector}</button>`;

      const rowsHTML = sectorHoldings.map(h => `
        <tr class="portfolio-row" onclick="loadChart('${h.ticker}')">
          <td><div class="ticker-cell"><span class="symbol">${h.ticker}</span></div></td>
          <td class="price-mono">${h.shares}</td>
          <td class="price-mono">$${h.avg_cost.toFixed(2)}</td>
          <td class="price-mono">$${(h.current_price || 0).toFixed(2)}</td>
          <td class="price-mono">$${(h.current_value || 0).toFixed(2)}</td>
          <td class="price-mono ${h.gain_loss >= 0 ? 'up' : 'down'}">${h.gain_loss >= 0 ? '+' : ''}$${(h.gain_loss || 0).toFixed(2)} (${h.gain_loss_pct >= 0 ? '+' : ''}${(h.gain_loss_pct || 0).toFixed(1)}%)</td>
          <td class="price-mono" style="color:var(--text-tertiary)">${(h.weight_pct || 0).toFixed(1)}%</td>
          <td class="price-mono ${(h.change_today || 0) >= 0 ? 'up' : 'down'}">${(h.change_today || 0) >= 0 ? '+' : ''}${(h.change_today || 0).toFixed(2)}%</td>
        </tr>
      `).join("");

      contentHTML += `
        <div class="portfolio-tab-content" id="portfolio-${safeId}" style="display: ${isFirst ? 'block' : 'none'};">
          <table class="portfolio-table">
            <thead>
              <tr><th>Holding</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Return</th><th>Weight</th><th>Today</th></tr>
            </thead>
            <tbody>
              ${rowsHTML}
            </tbody>
          </table>
        </div>
      `;
      isFirst = false;
    }
    tabsHTML += '</div>';

    document.getElementById("portfolioTablesContainer").innerHTML = `
      <div style="display:flex; justify-content:flex-end; align-items:center; margin-bottom:-10px;">
        ${tabsHTML}
      </div>
      ${contentHTML}
    `;"""

content = content.replace(old_js, new_js)

# We need to make sure the card title doesn't look weird with the tabs, but since I am putting the tabs inside portfolioTablesContainer, it should appear right under the title.

with open('dashboard/index.html', 'w') as f:
    f.write(content)

print("Portfolio JS patched.")
