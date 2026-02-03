#!/bin/bash
set -euo pipefail

HEARTBEAT_PATH="${HEARTBEAT_PATH:-/run/controlpod/heartbeat}"
MAX_AGE_SECONDS="${MAX_AGE_SECONDS:-600}"

if [[ ! -f "$HEARTBEAT_PATH" ]]; then
  logger -t controlpod-health "heartbeat missing; restarting controlpod.service"
  systemctl restart controlpod.service
  exit 0
fi

ts="$(cut -d'|' -f1 "$HEARTBEAT_PATH" | xargs)"
if ! hb_epoch="$(date -d "$ts" +%s 2>/dev/null)"; then
  logger -t controlpod-health "heartbeat parse failed ($ts); restarting controlpod.service"
  systemctl restart controlpod.service
  exit 0
fi

now="$(date +%s)"
age=$((now - hb_epoch))
if (( age > MAX_AGE_SECONDS )); then
  logger -t controlpod-health "heartbeat stale (${age}s > ${MAX_AGE_SECONDS}s); restarting controlpod.service"
  systemctl restart controlpod.service
fi
