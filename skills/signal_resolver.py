"""Record observations for open signals without implying an unverified fill."""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("finclaw.resolver")


def resolve_open_signals(
    get_stock_quote_fn,
    get_signals_fn,
    resolve_signal_fn,
    record_observation_fn=None,
    max_age_days=30,
):
    """
    Record current marks and target/stop observations. Only the explicit
    resolution endpoint may record a realized win/loss with fill details.

    Args:
        get_stock_quote_fn: callable to fetch current price
        get_signals_fn: callable to fetch signals from DB
        resolve_signal_fn: callable retained for backward compatibility
        record_observation_fn: callable to persist a mark-to-market observation
        max_age_days: number of days before an unresolved signal expires
    """
    open_signals = get_signals_fn(include_resolved=False, limit=200)
    counts = {
        "target_observed": 0,
        "stop_observed": 0,
        "expired_unfilled": 0,
        "awaiting_fill": 0,
        "open_filled": 0,
        "unavailable": 0,
    }

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
        if not current_price or not record_observation_fn:
            logger.warning("Could not fetch price for %s — skipping signal #%s", ticker, signal_id)
            counts["unavailable"] += 1
            continue

        is_filled = sig.get("entry_filled") == 1 and sig.get("fill_price")
        observed_return = None
        if is_filled and sig.get("fill_price"):
            observed_return = (current_price - sig["fill_price"]) / sig["fill_price"] * 100

        outcome = "mark_to_market"
        if not is_filled:
            outcome = "awaiting_fill"
            counts["awaiting_fill"] += 1
        elif target_price and current_price >= target_price:
            outcome = "target_level_observed"
            counts["target_observed"] += 1
        elif stop_loss and current_price <= stop_loss:
            outcome = "stop_level_observed"
            counts["stop_observed"] += 1
        else:
            counts["open_filled"] += 1

        method = "quote_observation_not_execution"
        try:
            signal_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if signal_date.tzinfo:
                signal_date = signal_date.astimezone().replace(tzinfo=None)
            age = (datetime.utcnow() - signal_date).days
            if age > max_age_days:
                if not is_filled:
                    outcome = "unfilled_expired"
                    counts["expired_unfilled"] += 1
                    counts["awaiting_fill"] -= 1
                method = "quote_observation_expired"
        except (ValueError, TypeError):
            logger.warning("Invalid signal timestamp for #%s; recording current mark only", signal_id)

        record_observation_fn(
            signal_id,
            current_price,
            outcome=outcome,
            outcome_return_pct=round(observed_return, 2) if observed_return is not None else None,
            outcome_method=method,
        )

    logger.info("Signal observation pass complete: %s", counts)
    return counts
