#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ "${CONFIRM_RESET:-}" = chaosloop ] || { echo 'REFUSED: require CONFIRM_RESET=chaosloop; deletes only this lab volumes' >&2; exit 1; }
project=$(docker compose -f compose.yaml -f compose.phase4.yaml config --format json | docker run --rm --memory 128m --cpus 0.5 --pids-limit 32 --network none -i python:3.12.10-slim-bookworm python -c 'import sys,json; print(json.load(sys.stdin)["name"])')
[ "$project" = chaosloop ] || { echo 'REFUSED: Compose project must be chaosloop' >&2; exit 1; }
echo 'DESTRUCTIVE: removing chaosloop containers and named lab volumes only'
docker compose -f compose.yaml -f compose.phase4.yaml --profile observability --profile verify --profile chaos --profile intelligence --profile tests --profile tools down --volumes --remove-orphans
