import os

def patch_ui():
    with open('dashboard/index.html', 'r') as f:
        content = f.read()

    # 1. Add Scan History Nav Button
    nav_scans = """      <button class="nav-btn" id="nav-sandbox" onclick="showPage('sandbox')">🧪 Sandbox</button>
      <button class="nav-btn" id="nav-scans" onclick="showPage('scans')">📜 Scan History (Cron)</button>"""
    if "nav-scans" not in content:
        content = content.replace('<button class="nav-btn" id="nav-sandbox" onclick="showPage(\'sandbox\')">🧪 Sandbox</button>', nav_scans)

    # 2. Add Scan History Page
    scans_html = """
    <!-- ==========================================
         PAGE: SCAN HISTORY (CRON JOBS)
    =========================================== -->
    <div class="page" id="page-scans">
      <div class="card">
        <div class="card-title"><span class="icon">📜</span> Automated Cron Job History</div>
        <div style="margin-bottom: 16px; color: var(--text-secondary); font-size: 14px;">
          View the raw output of all automated background tasks and opportunity scans sent to Telegram over the last 7 days.
        </div>
        <div id="scansContainer">
          <div class="loading-overlay"><div class="spinner"></div></div>
        </div>
      </div>
    </div>
  </main>"""
    if "id=\"page-scans\"" not in content:
        content = content.replace("  </main>", scans_html)

    # 3. Add JS Function
    js_functions = """
// ================================================
// SCAN HISTORY (CRON)
// ================================================
async function loadScans() {
  const container = document.getElementById("scansContainer");
  container.innerHTML = '<div class="loading-overlay"><div class="spinner"></div></div>';
  try {
    const res = await fetch("/api/scans?days=7");
    const data = await res.json();
    if (!data.scans || data.scans.length === 0) {
      container.innerHTML = '<div style="color:var(--text-secondary);padding:20px;">No cron job history found for the last 7 days.</div>';
      return;
    }
    
    // Sort by timestamp descending
    data.scans.sort((a,b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    let html = '';
    data.scans.forEach(scan => {
      let payloadStr = "No text output found.";
      if (scan.result_json) {
        try {
          const parsed = JSON.parse(scan.result_json);
          // If the cron job generated a formatted brief for telegram, show it. Otherwise show raw JSON.
          if (parsed.opportunities && parsed.opportunities.length > 0) {
             payloadStr = parsed.opportunities.map(o => `<strong>${o.ticker}</strong>: ${o.reasons ? o.reasons.join(', ') : 'Generated'}`).join('<br>');
          } else {
             payloadStr = `<pre style="font-size:11px; color:var(--text-secondary); background:var(--bg-page); padding:8px; border-radius:4px; max-height:150px; overflow-y:auto;">${JSON.stringify(parsed, null, 2)}</pre>`;
          }
        } catch(e) {
          payloadStr = `<pre style="font-size:11px; color:var(--text-secondary); background:var(--bg-page); padding:8px; border-radius:4px;">${scan.result_json}</pre>`;
        }
      }
      
      html += `
        <div style="background:var(--bg-white); border:1px solid var(--border); border-radius:8px; padding:16px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; margin-bottom:12px; border-bottom:1px solid var(--border); padding-bottom:8px;">
            <strong style="color:var(--text-primary); font-size:15px; text-transform:uppercase;">${scan.scan_type.replace(/_/g, ' ')}</strong>
            <span style="color:var(--text-secondary); font-size:12px;">${new Date(scan.timestamp).toLocaleString()}</span>
          </div>
          <div style="color:var(--text-primary); font-size:13px; line-height:1.6;">${payloadStr}</div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div style="color:var(--red)">Failed to load scan history: ${err.message}</div>`;
  }
}

"""
    if "loadScans()" not in content:
        content = content.replace("// ================================================\n// INIT", js_functions + "\n// ================================================\n// INIT")

    # Add to showPage
    if "name === 'scans'" not in content:
        content = content.replace("  if (name === 'sandbox') {}", "  if (name === 'sandbox') {}\n  if (name === 'scans') loadScans();")

    with open('dashboard/index.html', 'w') as f:
        f.write(content)

    print("Dashboard UI patched with Scan History tab!")

if __name__ == "__main__":
    patch_ui()
