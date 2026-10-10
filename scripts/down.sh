#!/bin/sh
set -eu
# Retain the watchdog until an active experiment has restored and released.
if [ -n "$(docker compose --profile chaos ps --status running -q docker-gate)" ]; then
  sh chaos/scripts/stop.sh
fi
docker compose --profile observability --profile verify --profile chaos down
