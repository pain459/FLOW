#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps --entrypoint python incident-controller -m decision_engine.cli replay "$@"
