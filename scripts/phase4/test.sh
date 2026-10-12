#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
docker compose -f compose.yaml -f compose.phase4.yaml build decision-tests
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps --entrypoint python decision-roles -m decision_engine.setup_test_db
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps --entrypoint python decision-roles -m decision_engine.migrate_test
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps decision-tests
