import re

with open('dashboard/index.html', 'r') as f:
    content = f.read()

# Add CSS for inner tabs
css_injection = """    .nav-btn.active {
      background: var(--bg-pill-active);
      color: #FFFFFF;
      box-shadow: 0 1px 4px rgba(0,0,0,0.12);
    }

    /* Inner Tabs */
    .inner-nav {
      display: inline-flex;
      background: var(--bg-page);
      border-radius: 8px;
      padding: 3px;
      margin-bottom: 12px;
    }
    .inner-nav-btn {
      padding: 4px 12px;
      border-radius: 6px;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
    }
    .inner-nav-btn.active {
      background: var(--bg-white);
      color: var(--text-primary);
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
"""
content = content.replace("    .nav-btn.active {\n      background: var(--bg-pill-active);\n      color: #FFFFFF;\n      box-shadow: 0 1px 4px rgba(0,0,0,0.12);\n    }\n", css_injection)

# Add JS functions for tab switching
js_functions = """// ================================================
// INNER TABS
// ================================================
function switchWatchlistTab(tabId) {
  document.querySelectorAll('.watchlist-tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.watchlist-tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('watchlist-' + tabId).style.display = 'block';
  document.getElementById('btn-watchlist-' + tabId).classList.add('active');
}

function switchPortfolioTab(tabId) {
  document.querySelectorAll('.portfolio-tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.portfolio-tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('portfolio-' + tabId).style.display = 'block';
  document.getElementById('btn-portfolio-' + tabId).classList.add('active');
}

// ================================================
// MARKET STATUS"""
content = content.replace("// ================================================\n// MARKET STATUS", js_functions)

with open('dashboard/index.html', 'w') as f:
    f.write(content)

print("CSS and generic JS functions injected.")
