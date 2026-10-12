#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose -f compose.yaml -f compose.phase4.yaml --profile observability --profile chaos --profile intelligence ps
docker compose run --rm --no-deps tests python -c 'import urllib.request; print(urllib.request.urlopen("http://api:8080/health/dependencies",timeout=10).read().decode())'
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps --entrypoint python incident-controller -m decision_engine.cli health
