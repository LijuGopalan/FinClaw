"""
FinClaw Signal Resolver — Auto-resolve WIN/LOSS/EXPIRED signals
================================================================
Checks all OPEN signals against current prices and resolves them
based on target/stop-loss hit or time expiration.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("finclaw.resolver")


def resolve_open_signals(get_stock_quote_fn, get_signals_fn, resolve_signal_fn,
                          max_age_days=30):
    """
    Scan all OPEN signals and auto-resolve them:
    - WIN: current price >= target_price
    - LOSS: current price <= stop_loss
    - EXPIRED: signal older than max_age_days without hitting target/stop

    Args:
        get_stock_quote_fn: callable to fetch current price
        get_signals_fn: callable to fetch signals from DB
        resolve_signal_fn: callable to update signal outcome in DB
        max_age_days: number of days before an unresolved signal expires
    """
    open_signals = get_signals_fn(include_resolved=False, limit=200)
    resolved_count = {"win": 0, "loss": 0, "expired": 0, "still_open": 0}

    for sig in open_signals:
        if sig.get("outcome") and sig["outcome"] not in ("OPEN", None):
            continue

        ticker = sig.get("ticker")
        if not ticker:
            continue

        signal_id = sig.get("id")
        price_at_signal = sig.get("price_at_signal") or 0
        target_price = sig.get("target_price")
        stop_loss = sig.get("stop_loss")
        created_at = sig.get("created_at", "")

        # Fetch current price
        quote = get_stock_quote_fn(ticker)
        current_price = quote.get("price")
        if not current_price:
            logger.warning("Could not fetch price for %s — skipping signal #%s", ticker, signal_id)
            continue

        # Check WIN
        if target_price and current_price >= target_price:
            return_pct = ((current_price - price_at_signal) / price_at_signal * 100) if price_at_signal else 0
            resolve_signal_fn(signal_id, "WIN", current_price, round(return_pct, 2))
            resolved_count["win"] += 1
            logger.info("Signal #%s %s → WIN (target $%.2f hit, current $%.2f, return %.1f%%)",
                        signal_id, ticker, target_price, current_price, return_pct)
            continue

        # Check LOSS
        if stop_loss and current_price <= stop_loss:
            return_pct = ((current_price - price_at_signal) / price_at_signal * 100) if price_at_signal else 0
            resolve_signal_fn(signal_id, "LOSS", current_price, round(return_pct, 2))
            resolved_count["loss"] += 1
            logger.info("Signal #%s %s → LOSS (stop $%.2f hit, current $%.2f, return %.1f%%)",
                        signal_id, ticker, stop_loss, current_price, return_pct)
            continue

        # Check EXPIRED
        try:
            signal_date = datetime.fromisoformat(created_at.replace("Z", "+00:00").replace("+00:00", ""))
            age = (datetime.utcnow() - signal_date).days
            if age > max_age_days:
                return_pct = ((current_price - price_at_signal) / price_at_signal * 100) if price_at_signal else 0
                outcome = "WIN" if return_pct > 0 else "LOSS"
                resolve_signal_fn(signal_id, outcome, current_price, round(return_pct, 2))
                resolved_count["expired"] += 1
                logger.info("Signal #%s %s → %s (expired after %d days, return %.1f%%)",
                            signal_id, ticker, outcome, age, return_pct)
                continue
        except (ValueError, TypeError):
            pass

        resolved_count["still_open"] += 1

    logger.info("Signal resolution complete: %s", resolved_count)
    return resolved_count
