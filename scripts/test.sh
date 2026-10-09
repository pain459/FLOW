#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p artifacts/tests
set +e
docker compose run --rm tests "$@" > artifacts/tests/latest.txt 2>&1
result=$?
set -e
cat artifacts/tests/latest.txt
if [ "$result" -ne 0 ]; then
  docker compose --profile observability --profile activity ps --format json > artifacts/tests/service-state.json
  docker compose logs --no-color --tail 200 api outbox-relay event-worker > artifacts/tests/services.txt 2>&1
  docker compose run --rm --no-deps verifier python -m verifier.main --once > artifacts/tests/lab-verification.json || true
  echo 'Failure diagnostics retained in artifacts/tests; lab snapshot is separate from isolated test fixtures' >&2
fi
exit "$result"
