#!/bin/bash
# rotate_logs.sh — Truncate all FinClaw log files
# Runs every 6 hours via launchd to prevent log bloat.
# ====================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILES=(
  "server.log"
  "server.error.log"
  "finclaw_launchd.log"
  "finclaw_launchd_error.log"
  "start.log"
  "startup.log"
  "gateway.log"
)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Log rotation starting..."

for f in "${LOG_FILES[@]}"; do
  filepath="$DIR/$f"
  if [ -f "$filepath" ]; then
    size=$(du -h "$filepath" | cut -f1)
    : > "$filepath"
    echo "  ✓ Truncated $f ($size)"
  fi
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Log rotation complete."
