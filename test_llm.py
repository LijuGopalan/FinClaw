import logging
logging.basicConfig(level=logging.INFO)
from skills.llm import ask, build_market_context
from scheduler import _api_get

portfolio = _api_get("/portfolio")
movers    = _api_get("/market/movers")
fg        = _api_get("/market/fear-greed")
alerts    = _api_get("/alerts?limit=5")
opps      = _api_get("/opportunities?limit=8&session=auto")

api_data = {
    "portfolio":      portfolio,
    "market_indices": (movers.get("market_indices") if isinstance(movers, dict) else {}),
    "fear_greed":     fg,
    "alerts":         (alerts if isinstance(alerts, list) else alerts.get("alerts", []) if isinstance(alerts, dict) else []),
    "opportunities":  (opps.get("opportunities", []) if isinstance(opps, dict) else opps if isinstance(opps, list) else []),
}

context = build_market_context(api_data)

task = (
    "Market is closed (4:05 PM CST). Write an end-of-day portfolio review:\n"
    "1. How the portfolio performed today (winners, losers)\n"
    "2. Any positions near their stop-loss that need monitoring overnight\n"
    "3. Top 2 overnight/next-day watchlist ideas from the scan\n"
    "4. One-sentence macro read for tomorrow\n"
    "5. Rebalancing suggestion if any position exceeds 8% of portfolio\n"
    "Keep it under 400 words."
)
prompt = f"{context}\n\n---\nYOUR TASK:\n{task}"

print("=== PROMPT ===")
print(prompt[:500] + "...\n" + prompt[-500:])
print("=== END PROMPT ===")

print("Calling ask()...")
response = ask(prompt, max_tokens=1500)
print("=== RESPONSE ===")
print(response)
print("=== END RESPONSE ===")
