#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p artifacts/baseline
docker compose run --rm --no-deps seed > artifacts/baseline/seed.json
docker compose run --rm --no-deps verifier python -m verifier.main --once > artifacts/baseline/verification-before.json
docker compose run --rm --no-deps --name chaosloop-baseline-observer tests python tests/e2e/baseline.py --seconds 1800 > artifacts/baseline/steady-state.json
docker compose run --rm --no-deps verifier python -m verifier.main --once > artifacts/baseline/verification.json
docker compose run --rm --no-deps tests python -c 'import urllib.request; print(urllib.request.urlopen("http://api:8080/health/dependencies").read().decode())' > artifacts/baseline/health.json
