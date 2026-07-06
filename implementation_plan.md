# Scheduler Daemon Fix Plan

## Goal Description
You reported that your cron jobs are not running. After investigating the codebase, I discovered the root cause: while the cron schedules are perfectly defined in your `openclaw.config.yml` (e.g. `intraday_scan: '*/15 9-16 * * 1-5'`), and the backend endpoints exist to handle them, **there is currently no actual scheduler script running to trigger them!** 

The previous setup assumed an external system cron was hitting the API, but nothing was actually triggering it.

## Proposed Changes
I will build a dedicated, lightweight background daemon (`scheduler.py`) that will act as the heartbeat of FinClaw.

### Phase 1: Build the Scheduler Daemon
- I will create `scheduler.py` in your project root.
- It will parse the exact schedules defined in `openclaw.config.yml`.
- It will use the `schedule` library (which is already in your `requirements.txt`) to translate the config schedules into actual Python background threads.
- When a schedule triggers (like the 15-minute `opportunity_intraday`), the script will automatically ping the `http://localhost:5001/api/opportunities/scan` endpoint.

# Implementation Plan: LLM-Powered FinClaw

## What We're Building

Two parallel intelligence layers running simultaneously:
- **Layer 1 (existing):** Algorithmic `server.py` — pure math, zero cost, handles alerts ✅
- **Layer 2 (new):** Gemini Flash LLM — intelligent analysis, scheduled briefings, chat

---

## Changes

### 1. `skills/llm.py` [NEW]
A shared Gemini Flash wrapper with **retry logic** (3 attempts, exponential backoff).
All LLM calls go through here — scheduler AND Telegram bot both use it.

### 2. `scheduler.py` [MODIFY]
Add LLM-powered scheduled tasks alongside the existing algorithmic scans:
- `08:15 CST` — Pre-market LLM brief (Gemini Flash analyzes market + portfolio)
- `12:00 CST` — Midday LLM swing analysis
- `16:05 CST` — Close summary LLM report with portfolio review

> **Note:** The `08:30–16:00 CST` intraday scalp scans stay **algorithmic only** (no LLM cost — these fire 26x/day).

### 3. `telegram_bot.py` [MODIFY]
Replace the keyword matcher with a real Gemini Flash chat handler:
- System prompt: Full `SOUL.md` personality loaded at startup
- Context: Portfolio + market overview pre-fetched and injected per message
- The LLM sees your real portfolio, real prices, and real technical data before answering

### 4. `openclaw.config.yml` [NO CHANGE]
Keep `schedule: {}` — our `scheduler.py` owns the schedule with full retry control.
This prevents the OpenClaw app from firing duplicate LLM calls independently.

---

## Cost Estimate

| Task | Frequency | Approx tokens | Daily cost |
|------|-----------|--------------|------------|
| Pre-market brief | 1x/day | ~3K | ~$0.001 |
| Midday analysis | 1x/day | ~3K | ~$0.001 |
| Close summary | 1x/day | ~3K | ~$0.001 |
| Telegram chat | On demand | ~2K/msg | ~$0.00015/msg |

**Total background cost: ~$0.003/day (~$1/month)**

---

## Open Questions

> [!IMPORTANT]
> The OpenClaw app (`ai.openclaw.gateway`) has its own internal LLM schedule. If we re-enable it, it will ALSO fire LLM calls independently — potentially sending duplicate Telegram alerts and causing the `FailoverError` again if there's a network blip.
> **Recommendation:** Keep OpenClaw schedule disabled. Our `scheduler.py` owns all scheduling with retry logic we fully control.
> If you still want the OpenClaw app's internal schedule re-enabled separately, let me know and I can do that as an additional step.

## Verification Plan
1. I will run the `scheduler.py` script manually and force-trigger one of the jobs (like `close_summary`) to ensure it hits the API.
2. We will check the `Scan History` tab on your dashboard to verify the cron job executed and logged its result successfully.
