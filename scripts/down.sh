#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Retain the watchdog until an active experiment has restored and released.
if [ -n "$(docker compose --profile chaos ps --status running -q docker-gate)" ]; then
  sh chaos/scripts/stop.sh
fi
docker compose -f compose.yaml -f compose.phase4.yaml --profile observability --profile verify --profile chaos --profile intelligence down
