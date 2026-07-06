"""
FinClaw Database Layer — SQLite Persistence
=============================================
Stores signal history, scan results, portfolio snapshots,
and options flow data for trend analysis over time.
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

# Database location
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "finclaw.db")


@contextmanager
def get_db():
    """Context manager for database connections."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database tables."""
    with get_db() as conn:
        conn.executescript("""
            -- AI Signal recommendations with outcome tracking
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL,          -- BUY, SELL, HOLD, WATCH
                horizon TEXT,                  -- SHORT-TERM, LONG-TERM
                confidence INTEGER,
                entry_low REAL,
                entry_high REAL,
                target_price REAL,
                stop_loss REAL,
                thesis TEXT,
                price_at_signal REAL,
                outcome TEXT,                  -- WIN, LOSS, OPEN, EXPIRED
                outcome_price REAL,
                outcome_return_pct REAL,
                created_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT
            );

            -- Daily scan results
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_type TEXT NOT NULL,        -- morning_brief, midday, close_summary
                data JSON,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Portfolio value snapshots for performance charting
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_value REAL,
                total_cost REAL,
                total_gain_loss REAL,
                total_return_pct REAL,
                spy_price REAL,                -- benchmark
                holdings_json JSON,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Unusual options activity log
            CREATE TABLE IF NOT EXISTS options_flow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                option_type TEXT,               -- call, put
                strike REAL,
                expiry TEXT,
                volume INTEGER,
                open_interest INTEGER,
                premium REAL,
                volume_multiplier REAL,
                sentiment TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Alert history
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT,               -- info, warning, critical
                title TEXT,
                message TEXT,
                ticker TEXT,
                acknowledged INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
            CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
            CREATE INDEX IF NOT EXISTS idx_options_ticker ON options_flow(ticker);
            CREATE INDEX IF NOT EXISTS idx_options_created ON options_flow(created_at);
            CREATE INDEX IF NOT EXISTS idx_snapshots_created ON portfolio_snapshots(created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
        """)


# ============================================================
# SIGNALS CRUD
# ============================================================
def save_signal(ticker, action, horizon, confidence, entry_low=None,
                entry_high=None, target_price=None, stop_loss=None,
                thesis=None, price_at_signal=None):
    """Save an AI-generated signal."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO signals (ticker, action, horizon, confidence,
                entry_low, entry_high, target_price, stop_loss,
                thesis, price_at_signal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, action, horizon, confidence, entry_low, entry_high,
              target_price, stop_loss, thesis, price_at_signal))


def resolve_signal(signal_id, outcome, outcome_price, outcome_return_pct):
    """Mark a signal as resolved (WIN/LOSS/EXPIRED)."""
    with get_db() as conn:
        conn.execute("""
            UPDATE signals SET outcome=?, outcome_price=?,
                outcome_return_pct=?, resolved_at=datetime('now')
            WHERE id=?
        """, (outcome, outcome_price, outcome_return_pct, signal_id))


def get_signals(ticker=None, limit=50, include_resolved=True):
    """Get signal history."""
    with get_db() as conn:
        query = "SELECT * FROM signals"
        params = []
        conditions = []

        if ticker:
            conditions.append("ticker=?")
            params.append(ticker.upper())

        if not include_resolved:
            conditions.append("outcome IS NULL OR outcome='OPEN'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_signal_performance():
    """Get overall signal win/loss statistics."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN outcome IS NULL OR outcome='OPEN' THEN 1 ELSE 0 END) as open_positions,
                AVG(CASE WHEN outcome='WIN' THEN outcome_return_pct END) as avg_win_pct,
                AVG(CASE WHEN outcome='LOSS' THEN outcome_return_pct END) as avg_loss_pct,
                AVG(outcome_return_pct) as avg_return_pct
            FROM signals
        """).fetchone()
        result = dict(row)
        total_resolved = (result["wins"] or 0) + (result["losses"] or 0)
        result["win_rate_pct"] = round(result["wins"] / total_resolved * 100, 1) if total_resolved > 0 else None
        return result


# ============================================================
# PORTFOLIO SNAPSHOTS
# ============================================================
def save_portfolio_snapshot(total_value, total_cost, total_gain_loss,
                            total_return_pct, spy_price, holdings_json=None):
    """Save a daily portfolio snapshot."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO portfolio_snapshots
                (total_value, total_cost, total_gain_loss, total_return_pct,
                 spy_price, holdings_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (total_value, total_cost, total_gain_loss, total_return_pct,
              spy_price, json.dumps(holdings_json) if holdings_json else None))


def get_portfolio_history(days=90):
    """Get portfolio value history for charting."""
    with get_db() as conn:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT total_value, total_return_pct, spy_price, created_at
            FROM portfolio_snapshots
            WHERE created_at >= ?
            ORDER BY created_at ASC
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# OPTIONS FLOW
# ============================================================
def save_options_flow(ticker, option_type, strike, expiry, volume,
                      open_interest, premium, volume_multiplier, sentiment):
    """Save unusual options activity."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO options_flow
                (ticker, option_type, strike, expiry, volume,
                 open_interest, premium, volume_multiplier, sentiment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, option_type, strike, expiry, volume,
              open_interest, premium, volume_multiplier, sentiment))


def get_options_flow_history(ticker=None, days=7, limit=100):
    """Get options flow history."""
    with get_db() as conn:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        query = "SELECT * FROM options_flow WHERE created_at >= ?"
        params = [cutoff]

        if ticker:
            query += " AND ticker=?"
            params.append(ticker.upper())

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_options_flow_summary(ticker, days=5):
    """Get options flow summary for a ticker over N days."""
    with get_db() as conn:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        row = conn.execute("""
            SELECT
                COUNT(*) as total_alerts,
                SUM(CASE WHEN option_type='call' THEN 1 ELSE 0 END) as call_alerts,
                SUM(CASE WHEN option_type='put' THEN 1 ELSE 0 END) as put_alerts,
                SUM(premium) as total_premium,
                AVG(volume_multiplier) as avg_multiplier
            FROM options_flow
            WHERE ticker=? AND created_at >= ?
        """, (ticker.upper(), cutoff)).fetchone()
        return dict(row) if row else {}


# ============================================================
# ALERTS
# ============================================================
def save_alert(alert_type, title, message, ticker=None):
    """Save an alert to history."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO alerts (alert_type, title, message, ticker)
            VALUES (?, ?, ?, ?)
        """, (alert_type, title, message, ticker))


def get_alerts(limit=50, unread_only=False):
    """Get alert history."""
    with get_db() as conn:
        query = "SELECT * FROM alerts"
        if unread_only:
            query += " WHERE acknowledged=0"
        query += " ORDER BY created_at DESC LIMIT ?"
        rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]


def acknowledge_alert(alert_id):
    """Mark an alert as read."""
    with get_db() as conn:
        conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))


# ============================================================
# SCAN HISTORY
# ============================================================
def save_scan(scan_type, data):
    """Save scan results."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO scan_history (scan_type, data)
            VALUES (?, ?)
        """, (scan_type, json.dumps(data, default=str)))


def get_scan_history(scan_type=None, days=7, limit=20):
    """Get scan history."""
    with get_db() as conn:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        query = "SELECT * FROM scan_history WHERE created_at >= ?"
        params = [cutoff]
        if scan_type:
            query += " AND scan_type=?"
            params.append(scan_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("data"):
                d["data"] = json.loads(d["data"])
            results.append(d)
        return results

# NOTE: init_db() is called explicitly by server.py on startup.
# Do NOT call it here to avoid side effects on import.
