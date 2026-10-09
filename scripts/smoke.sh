#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose run --rm --no-deps tests python tests/e2e/smoke.py
