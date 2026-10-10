#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose --profile observability ps
docker compose run --rm --no-deps tests python -c 'import urllib.request; print(urllib.request.urlopen("http://api:8080/health/dependencies",timeout=10).read().decode())'
