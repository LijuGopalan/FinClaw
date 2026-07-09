#!/usr/bin/env python3
"""
watchdog.py — FinClaw Self-Healing Monitor
==========================================
Runs as a background daemon alongside the FinClaw stack.

Every 60 seconds it:
  1. Checks all three services are alive (server, scheduler, telegram_bot)
  2. Reads the last 200 lines of server.log and start.log for error patterns
  3. Checks /api/health and /api/schwab/status endpoints
  4. Applies known auto-fixes (code patches, config tweaks)
  5. Restarts crashed/unhealthy services
  6. Sends a Telegram alert describing exactly what was fixed

Known auto-fixable errors
--------------------------
  ● Process crash          — restart the process
  ● Port already in use    — kill stale, restart
  ● http_options kwarg     — already patched in llm.py; just restart
  ● Schwab token missing   — alert user (cannot auto-fix, needs browser)
  ● "model idle timeout"   — log is noisy; bump max_tokens guard if recurs
  ● Repeated LLM failures  — raise _REQUEST_TIMEOUT in llm.py automatically

Run:
    ./venv/bin/python watchdog.py &
    # or add to start.sh
"""

import os
import re
import sys
import time
import signal
import logging
import subprocess
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque
from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.resolve()
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
LOG_FILES   = [BASE_DIR / "server.log", BASE_DIR / "start.log", BASE_DIR / "server.error.log"]
SKILLS_DIR  = BASE_DIR / "skills"

# ── Config ───────────────────────────────────────────────────────────────────
CHECK_INTERVAL   = 300        # seconds between health checks
LOG_TAIL_LINES   = 200        # lines to scan per check
API_BASE         = "http://localhost:5055/api"
MAX_RESTART_COOLDOWN = 300    # seconds between restarts of same process

# ── Services to monitor ───────────────────────────────────────────────────────
SERVICES = {
    "server":       {"script": "server.py",      "log": "server.log"},
    "scheduler":    {"script": "scheduler.py",   "log": "start.log"},
    "telegram_bot": {"script": "telegram_bot.py","log": "start.log"},
}

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "watchdog.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("finclaw.watchdog")


# ═════════════════════════════════════════════════════════════════════════════
# Telegram helper
# ═════════════════════════════════════════════════════════════════════════════

def _telegram(msg: str):
    """Send a watchdog notification to Telegram."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"🔧 <b>FinClaw Watchdog</b>\n\n{msg}",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        logger.warning("Watchdog Telegram send failed: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
# Process management
# ═════════════════════════════════════════════════════════════════════════════

_last_restart: dict[str, float] = {}   # service → epoch time of last restart
_restart_count: dict[str, int]  = defaultdict(int)


def _is_running(script_name: str) -> bool:
    """Return True if a python process with script_name is running."""
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-if", f"{script_name}"],
            capture_output=True, text=True,
        )
        return bool(result.stdout.strip())
    except Exception as e:
        logger.error("Error in _is_running for %s: %s", script_name, e)
        return False


def _kill(script_name: str):
    """Kill all processes matching script_name."""
    try:
        subprocess.run(["/usr/bin/pkill", "-if", f"{script_name}"], capture_output=True)
        time.sleep(1)
        subprocess.run(["/usr/bin/pkill", "-9", "-if", f"{script_name}"], capture_output=True)
    except Exception as e:
        logger.error("Error in _kill for %s: %s", script_name, e)


def _start(service_key: str) -> bool:
    """Start a service in the background. Returns True if launched."""
    svc    = SERVICES[service_key]
    script = BASE_DIR / svc["script"]
    log    = BASE_DIR / svc["log"]

    now = time.time()
    if now - _last_restart.get(service_key, 0) < MAX_RESTART_COOLDOWN:
        remaining = int(MAX_RESTART_COOLDOWN - (now - _last_restart.get(service_key, 0)))
        logger.info("Skipping restart of %s — cooldown %ds remaining", service_key, remaining)
        return False

    logger.info("Starting %s...", service_key)
    try:
        with open(log, "a") as lf:
            subprocess.Popen(
                [str(VENV_PYTHON), str(script)],
                cwd=str(BASE_DIR),
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )
        _last_restart[service_key] = now
        _restart_count[service_key] += 1
        time.sleep(3)  # Give it a moment to initialise
        return True
    except Exception as e:
        logger.error("Failed to start %s: %s", service_key, e)
        return False


def _restart(service_key: str, reason: str) -> bool:
    """Kill + restart a service. Returns True if restarted."""
    svc = SERVICES[service_key]
    logger.warning("Restarting %s — reason: %s", service_key, reason)
    _kill(svc["script"])
    time.sleep(1)
    started = _start(service_key)
    if started:
        logger.info("✅ %s restarted", service_key)
    return started


# ═════════════════════════════════════════════════════════════════════════════
# Error pattern registry
# ═════════════════════════════════════════════════════════════════════════════

# Each entry: (regex_pattern, severity, label, auto_fix_func_name_or_None)
# Patterns are matched against recent log lines.
ERROR_PATTERNS = [
    # LLM errors
    (r"unexpected keyword argument 'http_options'",
     "critical", "http_options kwarg error in google-genai",  "fix_http_options"),
    (r"model did not produce a response before the model idle timeout",
     "error",    "Gemini idle timeout on brief/scan",          "fix_llm_timeout"),
    (r"LLM temporarily unavailable",
     "warning",  "Transient LLM failure (will retry)",         None),
    # Schwab errors
    (r"Schwab.*token.*failed|stale token|token file load failed",
     "error",    "Schwab token stale or invalid",              "alert_schwab_reauth"),
    (r"Schwab.*HTTP 401|Schwab.*HTTP 403",
     "critical", "Schwab auth rejected (token expired)",       "alert_schwab_reauth"),
    # Server errors
    (r"Address already in use",
     "critical", "Port 5055 already in use",                   "fix_port_conflict"),
    (r"flask.*error|werkzeug.*error",
     "error",    "Flask/Werkzeug server error",                 "restart_server"),
    # Scheduler errors
    (r"scheduler.*failed|cron.*failed",
     "error",    "Scheduler cron job failed",                   None),
    # Database errors
    (r"sqlite3|database.*error|no such table",
     "warning",  "Database issue",                              None),
    # Import errors (missing packages)
    (r"ModuleNotFoundError|ImportError",
     "critical", "Missing Python module",                       None),
]


# ═════════════════════════════════════════════════════════════════════════════
# Auto-fix functions
# ═════════════════════════════════════════════════════════════════════════════

def fix_http_options() -> str:
    """Ensure http_options is inside GenerateContentConfig in llm.py."""
    llm_path = SKILLS_DIR / "llm.py"
    text = llm_path.read_text()

    # Check if already fixed (http_options inside config block)
    if "http_options=types.HttpOptions" in text:
        # Verify it's NOT a top-level kwarg to generate_content()
        # Simple heuristic: it should appear before the closing ')' of config
        if "config=types.GenerateContentConfig(" in text and \
           "http_options=types.HttpOptions" in text:
            # Check the indentation context — if already fixed, nothing to do
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if "http_options=types.HttpOptions" in line:
                    # Look backwards for generate_content( without intervening config(
                    context = "\n".join(lines[max(0,i-15):i+1])
                    if "GenerateContentConfig(" in context:
                        return "http_options already correctly placed — no change needed"

    # Apply patch: move http_options inside GenerateContentConfig
    old = (
        "                config=types.GenerateContentConfig(\n"
        "                    system_instruction=sys_prompt,\n"
        "                    max_output_tokens=max_tokens,\n"
        "                    temperature=0.15,\n"
        "                ),\n"
        "                # Hard HTTP timeout — prevents indefinite hang on slow/idle model\n"
        "                # Retried up to _MAX_RETRIES times with exponential backoff\n"
        "                http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT * 1000),"
    )
    new = (
        "                config=types.GenerateContentConfig(\n"
        "                    system_instruction=sys_prompt,\n"
        "                    max_output_tokens=max_tokens,\n"
        "                    temperature=0.15,\n"
        "                    http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT * 1000),\n"
        "                ),"
    )
    if old in text:
        llm_path.write_text(text.replace(old, new))
        return "✅ Patched http_options inside GenerateContentConfig in llm.py"
    return "http_options pattern not found — manual inspection needed"


def fix_llm_timeout() -> str:
    """Raise _REQUEST_TIMEOUT in llm.py if too low, and max_tokens if too high."""
    llm_path = SKILLS_DIR / "llm.py"
    text = llm_path.read_text()

    # Read current timeout
    m = re.search(r"_REQUEST_TIMEOUT\s*=\s*(\d+)", text)
    current = int(m.group(1)) if m else 90

    changed = []
    if current < 150:
        text = re.sub(
            r"_REQUEST_TIMEOUT\s*=\s*\d+",
            "_REQUEST_TIMEOUT = 150",
            text,
        )
        changed.append(f"_REQUEST_TIMEOUT {current}s → 150s")

    if changed:
        llm_path.write_text(text)

    # Also fix scheduler max_tokens if too high
    sched_path = BASE_DIR / "scheduler.py"
    sched_text = sched_path.read_text()
    m2 = re.search(r"response = ask\(prompt, max_tokens=(\d+)\)", sched_text)
    if m2:
        current_tok = int(m2.group(1))
        if current_tok > 2000:
            sched_text = sched_text.replace(
                f"max_tokens={current_tok}",
                "max_tokens=1500",
            )
            sched_path.write_text(sched_text)
            changed.append(f"scheduler max_tokens {current_tok} → 1500")

    if changed:
        return "✅ LLM timeout fixes applied: " + ", ".join(changed)
    return "LLM timeout settings already at safe values — triggering restart"


def fix_port_conflict() -> str:
    """Kill whatever is holding port 5055, then restart server."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", ":5055"],
            capture_output=True, text=True,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
                logger.info("Killed PID %s holding port 5055", pid)
            except Exception:
                pass
    except Exception as e:
        logger.warning("port conflict kill failed: %s", e)
    time.sleep(1)
    return "✅ Port 5055 cleared"


def restart_server() -> str:
    _restart("server", "Flask error detected in logs")
    return "✅ Server restarted"


def alert_schwab_reauth() -> str:
    """Cannot auto-fix — need user browser login. Just alert."""
    return (
        "⚠️ Schwab token expired or rejected.\n"
        "Run: <code>python skills/schwab_client.py</code>\n"
        "and complete the browser login. Data will fall back to yfinance until then."
    )


# Map fix function names → callables
FIX_REGISTRY = {
    "fix_http_options":    fix_http_options,
    "fix_llm_timeout":     fix_llm_timeout,
    "fix_port_conflict":   fix_port_conflict,
    "restart_server":      restart_server,
    "alert_schwab_reauth": alert_schwab_reauth,
}

# Which services to restart after each fix
FIX_RESTART_MAP = {
    "fix_http_options":    ["server", "scheduler", "telegram_bot"],
    "fix_llm_timeout":     ["scheduler"],
    "fix_port_conflict":   ["server"],
    "restart_server":      [],  # already restarted inside fix
    "alert_schwab_reauth": [],  # no restart needed
}


# ═════════════════════════════════════════════════════════════════════════════
# Log scanner
# ═════════════════════════════════════════════════════════════════════════════

_seen_errors: deque = deque(maxlen=500)   # prevents re-alerting on same error


def _tail_logs(n_lines: int = LOG_TAIL_LINES) -> list[str]:
    """Return the last n_lines from all monitored log files."""
    lines = []
    for path in LOG_FILES:
        try:
            if not path.exists():
                continue
            with open(path, "rb") as f:
                # Efficient tail without loading whole file
                f.seek(0, 2)
                size = f.tell()
                chunk = min(size, n_lines * 120)   # ~120 bytes/line estimate
                f.seek(max(0, size - chunk))
                raw = f.read().decode("utf-8", errors="replace")
                lines.extend(raw.splitlines()[-n_lines:])
        except Exception as e:
            logger.debug("Could not tail %s: %s", path, e)
    return lines


def scan_logs() -> list[dict]:
    """Scan recent logs and return list of detected issues."""
    lines  = _tail_logs()
    recent = "\n".join(lines[-LOG_TAIL_LINES:])
    issues = []

    for pattern, severity, label, fix_fn in ERROR_PATTERNS:
        matches = re.findall(pattern, recent, re.IGNORECASE)
        if matches:
            key = f"{pattern}:{matches[0]}"
            if key not in _seen_errors:
                _seen_errors.append(key)
                issues.append({
                    "pattern":  pattern,
                    "severity": severity,
                    "label":    label,
                    "fix_fn":   fix_fn,
                    "sample":   matches[0][:120],
                })
    return issues


# ═════════════════════════════════════════════════════════════════════════════
# API health check
# ═════════════════════════════════════════════════════════════════════════════

def check_api_health() -> dict:
    """Query the FinClaw API health endpoint."""
    try:
        r = requests.get(f"{API_BASE}/health", timeout=60)
        if r.status_code == 200:
            return r.json()
        return {"status": "unhealthy", "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e), "status": "unreachable"}


def check_schwab_status() -> dict:
    try:
        r = requests.get(f"{API_BASE}/schwab/status", timeout=10)
        return r.json()
    except Exception:
        return {}


def check_openclaw_crons() -> list[dict]:
    """
    Run `openclaw cron list` and return jobs with status=error.
    Returns list of {id, name, status, diagnostic} dicts.
    """
    try:
        result = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        import json as _json
        jobs = _json.loads(result.stdout)
        if isinstance(jobs, dict):
            jobs = jobs.get("items", jobs.get("crons", []))
        return [j for j in (jobs or []) if j.get("state", {}).get("lastRunStatus") == "error"]
    except Exception as e:
        logger.debug("openclaw cron list failed: %s", e)
        return []


_cron_fix_cooldown: dict[str, float] = {}   # cron_id → last fix epoch

def fix_openclaw_cron(job: dict) -> str:
    """
    Switch a failing OpenClaw cron job to gemini-3-flash-preview and reset it.
    """
    job_id   = job.get("id", "")
    job_name = job.get("name", job_id)

    now = time.time()
    if now - _cron_fix_cooldown.get(job_id, 0) < 600:   # 10-min cooldown per job
        return f"Cron '{job_name}' fix on cooldown — skipping"

    _cron_fix_cooldown[job_id] = now

    try:
        result = subprocess.run(
            ["openclaw", "cron", "edit", job_id, "--model", "google/gemini-3-flash-preview"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return f"✅ Switched cron '{job_name}' to gemini-3-flash-preview"
        else:
            return f"cron edit failed: {result.stderr[:100]}"
    except Exception as e:
        return f"cron fix exception: {e}"


# ═════════════════════════════════════════════════════════════════════════════
# Main watchdog loop
# ═════════════════════════════════════════════════════════════════════════════

def watchdog_cycle():
    """One full health + log scan cycle. Returns summary dict."""
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actions  = []
    alerts   = []

    # ── 1. Process liveness ─────────────────────────────────────────────────
    for svc_key, svc in SERVICES.items():
        if not _is_running(svc["script"]):
            reason = f"{svc['script']} not running"
            logger.warning(reason)
            restarted = _restart(svc_key, reason)
            if restarted:
                actions.append(f"▶️ Restarted <b>{svc_key}</b> (was crashed)")
            else:
                actions.append(f"⏳ <b>{svc_key}</b> restart on cooldown — will retry")

    # ── 1b. Duplicate process detection ─────────────────────────────────────
    for svc_key, svc in SERVICES.items():
        try:
            result = subprocess.run(
                ["/usr/bin/pgrep", "-if", f"{svc['script']}"],
                capture_output=True, text=True,
            )
            pids = [p for p in result.stdout.strip().splitlines() if p]
            if len(pids) > 1:
                logger.warning("Multiple instances of %s detected: %s", svc_key, pids)
                _kill(svc["script"])
                actions.append(f"🧹 Killed duplicate <b>{svc_key}</b> instances")
                _last_restart[svc_key] = 0
        except Exception as e:
            logger.error("Error checking duplicates for %s: %s", svc_key, e)

    # ── 2. API health ────────────────────────────────────────────────────────
    health = check_api_health()
    if health.get("status") != "healthy":
        err = health.get("error", "unknown")
        logger.warning("API health check failed: %s", err)
        if not _is_running("server.py"):
            pass  # already handled above
        else:
            # Server is running but not responding — restart
            restarted = _restart("server", f"API health failed: {err}")
            if restarted:
                actions.append(f"▶️ Restarted <b>server</b> (health check failed: {err[:60]})")

    # ── 3. Log scan ──────────────────────────────────────────────────────────
    issues = scan_logs()
    for issue in issues:
        label  = issue["label"]
        fix_fn = issue["fix_fn"]
        logger.warning("Detected: [%s] %s", issue["severity"], label)

        fix_result = ""
        services_to_restart = []

        if fix_fn and fix_fn in FIX_REGISTRY:
            try:
                fix_result = FIX_REGISTRY[fix_fn]()
                logger.info("Fix applied — %s: %s", fix_fn, fix_result)
                services_to_restart = FIX_RESTART_MAP.get(fix_fn, [])
            except Exception as e:
                fix_result = f"Fix failed: {e}"
                logger.error("Fix %s raised exception: %s", fix_fn, e)
        else:
            fix_result = "No auto-fix — monitoring"

        # Restart affected services
        for svc_key in services_to_restart:
            restarted = _restart(svc_key, f"post-fix restart after {fix_fn}")
            if restarted:
                actions.append(f"▶️ Restarted <b>{svc_key}</b> after fix")

        actions.append(
            f"🔍 Detected: <b>{label}</b>\n"
            f"   Fix: {fix_result}"
        )

    # ── 4. Schwab token check ─────────────────────────────────────────────────
    schwab = check_schwab_status()
    if schwab and not schwab.get("authenticated") and schwab.get("api_key_set"):
        msg = "⚠️ Schwab token missing or expired. Run <code>python skills/schwab_client.py</code> to re-authenticate."
        key = "schwab_not_auth"
        if key not in _seen_errors:
            _seen_errors.append(key)
            alerts.append(msg)
            logger.warning("Schwab not authenticated")

    # ── 5. OpenClaw cron job health ───────────────────────────────────────────
    failed_crons = check_openclaw_crons()
    for job in failed_crons:
        job_id   = job.get("id", "")
        job_name = job.get("name", job_id)
        diag     = (job.get("state") or {}).get("lastDiagnosticSummary", "")[:120]
        key      = f"cron_error:{job_id}"
        if key not in _seen_errors:
            _seen_errors.append(key)
            logger.warning("OpenClaw cron '%s' failed: %s", job_name, diag)
            fix_result = fix_openclaw_cron(job)
            actions.append(
                f"🕐 OpenClaw cron <b>{job_name}</b> failed\n"
                f"   Reason: {diag[:80]}\n"
                f"   Fix: {fix_result}"
            )

    return {
        "timestamp": now_str,
        "actions":   actions,
        "alerts":    alerts,
        "health":    health,
        "issues":    issues,
    }


def run_watchdog():
    """Main daemon loop."""
    logger.info("🐾 FinClaw Watchdog started — checking every %ds", CHECK_INTERVAL)
    _telegram(
        f"🐾 <b>Watchdog started</b>\n"
        f"Monitoring: server, scheduler, telegram_bot\n"
        f"Check interval: {CHECK_INTERVAL}s\n"
        f"Auto-fixes: process crashes, port conflicts, LLM errors"
    )

    while True:
        try:
            result = watchdog_cycle()

            # Send Telegram if anything happened
            if result["actions"] or result["alerts"]:
                parts = ["<b>Actions taken:</b>"] + result["actions"] if result["actions"] else []
                if result["alerts"]:
                    parts += ["<b>Alerts:</b>"] + result["alerts"]

                _telegram("\n".join(parts))

        except Exception as e:
            logger.error("Watchdog cycle exception: %s", e, exc_info=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run_watchdog()
