import re

with open('dashboard/index.html', 'r') as f:
    content = f.read()

old_js = """  let watchlistsHTML = "";

  for (const [listName, tickers] of Object.entries(watchlists)) {
    // Parallel fetch quotes and technicals for this list
    const quotePromises = tickers.map(t => api(`/quote/${t}`));
    const techPromises = tickers.map(t => api(`/technicals/${t}`));
    
    const [quotes, technicals] = await Promise.all([
      Promise.all(quotePromises),
      Promise.all(techPromises)
    ]);

    const watchlistRows = tickers.map((t, i) => {
      const q = quotes[i];
      const ta = technicals[i];
      
      // Check for offline/error
      if (q?.error || ta?.error) {
        return `
          <tr class="watchlist-row">
            <td><div class="ticker-cell"><span class="symbol">${t}</span></div></td>
            <td colspan="4" style="color:var(--text-tertiary)">Data unavailable</td>
          </tr>
        `;
      }

      const rsi = ta?.rsi_14 || 50;
      const macdH = ta?.macd_histogram || 0;
      let signal = "HOLD", sigClass = "hold";
      if (rsi < 35 && macdH > 0) { signal = "BUY"; sigClass = "buy"; }
      else if (rsi > 65 && macdH < 0) { signal = "SELL"; sigClass = "sell"; }
      else if (rsi < 40) { signal = "WATCH"; sigClass = "watch"; }
      else if (rsi > 60 && macdH > 0) { signal = "BUY"; sigClass = "buy"; }

      return `
        <tr class="watchlist-row" onclick="loadChart('${t}')">
          <td><div class="ticker-cell"><span class="symbol">${t}</span></div></td>
          <td class="price-mono">$${(q?.price || 0).toFixed(2)}</td>
          <td class="price-mono ${(q?.change_pct || 0) >= 0 ? 'up' : 'down'}">${(q?.change_pct || 0) >= 0 ? "+" : ""}${(q?.change_pct || 0).toFixed(2)}%</td>
          <td class="price-mono" style="color:${rsi < 35 ? 'var(--color-green)' : rsi > 65 ? 'var(--color-red)' : 'var(--text-secondary)'}">${rsi.toFixed(0)}</td>
          <td><span class="signal-action ${sigClass}">${signal}</span></td>
        </tr>
      `;
    });

    watchlistsHTML += `
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title"><span class="icon">👁</span> ${listName}</div>
        <table class="watchlist-table">
          <thead>
            <tr><th>Ticker</th><th>Price</th><th>Chg %</th><th>RSI</th><th>Signal</th></tr>
          </thead>
          <tbody>
            ${watchlistRows.join("")}
          </tbody>
        </table>
      </div>
    `;
  }
  document.getElementById("watchlistsContainer").innerHTML = watchlistsHTML;"""

new_js = """  let tabsHTML = '<div class="inner-nav">';
  let contentHTML = "";
  let isFirst = true;

  for (const [listName, tickers] of Object.entries(watchlists)) {
    const safeId = listName.replace(/\s+/g, '-').toLowerCase();
    
    tabsHTML += `<button class="inner-nav-btn watchlist-tab-btn ${isFirst ? 'active' : ''}" id="btn-watchlist-${safeId}" onclick="switchWatchlistTab('${safeId}')">${listName}</button>`;
    
    // Parallel fetch quotes and technicals for this list
    const quotePromises = tickers.map(t => api(`/quote/${t}`));
    const techPromises = tickers.map(t => api(`/technicals/${t}`));
    
    const [quotes, technicals] = await Promise.all([
      Promise.all(quotePromises),
      Promise.all(techPromises)
    ]);

    const watchlistRows = tickers.map((t, i) => {
      const q = quotes[i];
      const ta = technicals[i];
      
      // Check for offline/error
      if (q?.error || ta?.error) {
        return `
          <tr class="watchlist-row">
            <td><div class="ticker-cell"><span class="symbol">${t}</span></div></td>
            <td colspan="4" style="color:var(--text-tertiary)">Data unavailable</td>
          </tr>
        `;
      }

      const rsi = ta?.rsi_14 || 50;
      const macdH = ta?.macd_histogram || 0;
      let signal = "HOLD", sigClass = "hold";
      if (rsi < 35 && macdH > 0) { signal = "BUY"; sigClass = "buy"; }
      else if (rsi > 65 && macdH < 0) { signal = "SELL"; sigClass = "sell"; }
      else if (rsi < 40) { signal = "WATCH"; sigClass = "watch"; }
      else if (rsi > 60 && macdH > 0) { signal = "BUY"; sigClass = "buy"; }

      return `
        <tr class="watchlist-row" onclick="loadChart('${t}')">
          <td><div class="ticker-cell"><span class="symbol">${t}</span></div></td>
          <td class="price-mono">$${(q?.price || 0).toFixed(2)}</td>
          <td class="price-mono ${(q?.change_pct || 0) >= 0 ? 'up' : 'down'}">${(q?.change_pct || 0) >= 0 ? "+" : ""}${(q?.change_pct || 0).toFixed(2)}%</td>
          <td class="price-mono" style="color:${rsi < 35 ? 'var(--color-green)' : rsi > 65 ? 'var(--color-red)' : 'var(--text-secondary)'}">${rsi.toFixed(0)}</td>
          <td><span class="signal-action ${sigClass}">${signal}</span></td>
        </tr>
      `;
    });

    contentHTML += `
      <div class="watchlist-tab-content" id="watchlist-${safeId}" style="display: ${isFirst ? 'block' : 'none'};">
        <table class="watchlist-table">
          <thead>
            <tr><th>Ticker</th><th>Price</th><th>Chg %</th><th>RSI</th><th>Signal</th></tr>
          </thead>
          <tbody>
            ${watchlistRows.join("")}
          </tbody>
        </table>
      </div>
    `;
    isFirst = false;
  }
  tabsHTML += '</div>';
  
  document.getElementById("watchlistsContainer").innerHTML = `
    <div class="card">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <div><span class="icon">👁</span> Watchlists</div>
        ${tabsHTML}
      </div>
      ${contentHTML}
    </div>
  `;"""

content = content.replace(old_js, new_js)

with open('dashboard/index.html', 'w') as f:
    f.write(content)

print("Watchlists JS patched.")
