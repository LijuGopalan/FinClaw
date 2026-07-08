## 2024-07-08 - Parallelize backend API calls
**Learning:** Found an N+1 query problem in the `/api/quotes` endpoint. It fetched up to 20 quotes sequentially from either Tradier or yfinance, causing high latency.
**Action:** Replaced sequential loop with `ThreadPoolExecutor` to fetch quotes in parallel, significantly dropping response time (e.g. from 6.31s to 0.79s for 15 tickers).
