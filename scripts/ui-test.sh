#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p artifacts/dashboard
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose build ui-tests
container="chaosloop-ui-tests-$$"
trap 'docker rm -fv "$container" >/dev/null 2>&1 || true' EXIT HUP INT TERM
set +e
docker compose run --name "$container" --no-deps ui-tests > artifacts/dashboard/browser-tests.txt 2>&1
result=$?
set -e
cat artifacts/dashboard/browser-tests.txt
docker cp "$container:/evidence/." artifacts/dashboard/
exit "$result"
