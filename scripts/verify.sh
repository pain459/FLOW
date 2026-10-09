#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose run --rm --no-deps verifier python -m verifier.main --once
