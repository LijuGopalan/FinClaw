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
                resolved_at TEXT,
                source TEXT DEFAULT 'manual',
                scan_id INTEGER,
                signal_key TEXT,
                evidence_json JSON,
                risk_gate_json JSON,
                inference TEXT,
                recommendation TEXT,
                model_probability REAL,
                model_calibration TEXT,
                regime TEXT,
                entry_filled INTEGER,
                fill_price REAL,
                fees REAL,
                slippage REAL,
                outcome_method TEXT
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

            CREATE TABLE IF NOT EXISTS signal_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL REFERENCES signals(id),
                observed_at TEXT NOT NULL,
                observed_price REAL NOT NULL,
                outcome TEXT,
                outcome_return_pct REAL,
                outcome_method TEXT NOT NULL,
                UNIQUE(signal_id, observed_at)
            );

            -- Indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
            CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
            CREATE INDEX IF NOT EXISTS idx_options_ticker ON options_flow(ticker);
            CREATE INDEX IF NOT EXISTS idx_options_created ON options_flow(created_at);
            CREATE INDEX IF NOT EXISTS idx_snapshots_created ON portfolio_snapshots(created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
            CREATE INDEX IF NOT EXISTS idx_signal_observations_signal ON signal_observations(signal_id, observed_at);
        """)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}
        migrations = {
            "source": "TEXT DEFAULT 'manual'",
            "scan_id": "INTEGER",
            "signal_key": "TEXT",
            "evidence_json": "JSON",
            "risk_gate_json": "JSON",
            "inference": "TEXT",
            "recommendation": "TEXT",
            "model_probability": "REAL",
            "model_calibration": "TEXT",
            "regime": "TEXT",
            "entry_filled": "INTEGER",
            "fill_price": "REAL",
            "fees": "REAL",
            "slippage": "REAL",
            "outcome_method": "TEXT",
        }
        for column, column_type in migrations.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {column} {column_type}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_signal_key "
            "ON signals(signal_key) WHERE signal_key IS NOT NULL"
        )


# ============================================================
# SIGNALS CRUD
# ============================================================
def save_signal(ticker, action, horizon, confidence, entry_low=None,
                entry_high=None, target_price=None, stop_loss=None,
                thesis=None, price_at_signal=None, source="manual",
                scan_id=None, signal_key=None, evidence=None, risk_gate=None,
                inference=None, recommendation=None, model_probability=None,
                model_calibration=None, regime=None, entry_filled=None,
                fill_price=None, fees=None, slippage=None, outcome_method=None):
    """Save an AI-generated signal."""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO signals (ticker, action, horizon, confidence,
                entry_low, entry_high, target_price, stop_loss, thesis,
                price_at_signal, source, scan_id, signal_key, evidence_json,
                risk_gate_json, inference, recommendation, model_probability,
                model_calibration, regime, entry_filled, fill_price, fees,
                slippage, outcome_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, action, horizon, confidence, entry_low, entry_high,
            target_price, stop_loss, thesis, price_at_signal, source, scan_id,
            signal_key, json.dumps(evidence, default=str) if evidence is not None else None,
            json.dumps(risk_gate, default=str) if risk_gate is not None else None,
            inference, recommendation, model_probability, model_calibration,
            regime, entry_filled, fill_price, fees, slippage, outcome_method,
        ))
        return cursor.lastrowid


def resolve_signal(
    signal_id, outcome, outcome_price, outcome_return_pct,
    entry_filled=None, fill_price=None, fees=None, slippage=None, outcome_method=None,
):
    """Resolve a signal and optionally record verified fill and transaction details."""
    with get_db() as conn:
        conn.execute("""
            UPDATE signals SET outcome=?, outcome_price=?,
                outcome_return_pct=?, resolved_at=datetime('now'),
                entry_filled=COALESCE(?, entry_filled),
                fill_price=COALESCE(?, fill_price),
                fees=COALESCE(?, fees),
                slippage=COALESCE(?, slippage),
                outcome_method=COALESCE(?, outcome_method)
            WHERE id=?
        """, (
            outcome, outcome_price, outcome_return_pct, entry_filled, fill_price,
            fees, slippage, outcome_method, signal_id,
        ))


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
        results = [dict(r) for r in rows]
        for row in results:
            for key in ("evidence_json", "risk_gate_json"):
                if row.get(key):
                    try:
                        row[key] = json.loads(row[key])
                    except (TypeError, json.JSONDecodeError):
                        row[key] = None
        return results


def record_signal_observation(
    signal_id, observed_price, outcome=None, outcome_return_pct=None,
    outcome_method="mark_to_market",
):
    """Persist a timestamped mark-to-market observation without calling it a fill."""
    observed_at = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO signal_observations
                (signal_id, observed_at, observed_price, outcome, outcome_return_pct, outcome_method)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (signal_id, observed_at, observed_price, outcome, outcome_return_pct, outcome_method),
        )


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
    """Persist scan results and an immutable signal snapshot for each opportunity."""
    if not isinstance(data, dict):
        raise ValueError("Scan data must be a dictionary")
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO scan_history (scan_type, data)
            VALUES (?, ?)
        """, (scan_type, json.dumps(data, default=str)))
        scan_id = cursor.lastrowid

        container = data
        if not isinstance(container.get("opportunities"), list):
            container = data.get("scan_result") or {}
        opportunities = container.get("opportunities", [])
        generated_at = (
            container.get("generated_at")
            or data.get("timestamp")
            or datetime.utcnow().isoformat()
        )
        for opportunity in opportunities:
            ticker = str(opportunity.get("ticker") or "").upper().strip()
            if not ticker:
                continue
            signal_key = f"{scan_type}:{generated_at}:{ticker}"
            evidence = opportunity.get("evidence") or {
                key: opportunity.get(key)
                for key in (
                    "price", "change_pct", "volume_ratio", "rsi", "macd_histogram",
                    "atr", "support", "resistance", "reasons", "risk_flags",
                    "source", "source_notes", "timestamp",
                )
                if key in opportunity
            }
            risk_gate = opportunity.get("risk_gate")
            values = (
                ticker,
                opportunity.get("action", "WATCH"),
                opportunity.get("horizon", container.get("horizon")),
                opportunity.get("score"),
                opportunity.get("entry_low"),
                opportunity.get("entry_high"),
                opportunity.get("target_price"),
                opportunity.get("stop_loss"),
                opportunity.get("thesis"),
                opportunity.get("price"),
                "opportunity_scan",
                scan_id,
                signal_key,
                json.dumps(evidence, default=str),
                json.dumps(risk_gate, default=str) if risk_gate is not None else None,
                opportunity.get("inference", opportunity.get("thesis")),
                opportunity.get("action"),
                opportunity.get("ml_probability"),
                "platt" if opportunity.get("ml_probability") is not None else None,
                (container.get("regime_settings") or {}).get("regime"),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO signals (
                    ticker, action, horizon, confidence, entry_low, entry_high,
                    target_price, stop_loss, thesis, price_at_signal, source,
                    scan_id, signal_key, evidence_json, risk_gate_json, inference,
                    recommendation, model_probability, model_calibration, regime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            signal = conn.execute(
                "SELECT id FROM signals WHERE signal_key=?", (signal_key,)
            ).fetchone()
            if signal:
                opportunity["signal_id"] = signal["id"]

        conn.execute(
            "UPDATE scan_history SET data=? WHERE id=?",
            (json.dumps(data, default=str), scan_id),
        )
        return scan_id


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
