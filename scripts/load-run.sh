#!/bin/sh
. "$(dirname "$0")/load-common.sh"
profile=${PROFILE:-smoke}
if [ "${LOAD_IMAGE_PREBUILT:-false}" = true ]; then
  docker image inspect "${LOAD_IMAGE:-pulsepay-load:v1}" >/dev/null
else
  load_compose build load-controller
fi
set -- --profile "$profile"
if [ "${LOAD_UI:-false}" = true ]; then set -- "$@" --web; fi
if [ -n "${DURATION:-}" ]; then set -- "$@" --duration "$DURATION"; fi
if [ -n "${WARMUP:-}" ]; then set -- "$@" --warmup "$WARMUP"; fi
if [ -n "${USERS:-}" ]; then set -- "$@" --users "$USERS"; fi
if [ -n "${RATE:-}" ]; then set -- "$@" --rate "$RATE"; fi
if [ -n "${WORKERS:-}" ]; then set -- "$@" --workers "$WORKERS"; fi
if [ "${ALLOW_LONG_RUN:-false}" = true ]; then set -- "$@" --allow-long-run; fi
load_compose run --rm --no-deps load-controller python -m load_generator.controller.cli validate "$@"
guard_name="${COMPOSE_PROJECT_NAME:-chaosloop}-load-guard"
# Reserve the operator workflow before starting traffic; the controller also holds flock.
load_compose run --rm -d --name "$guard_name" --no-deps load-guard >/dev/null
resource_name="${COMPOSE_PROJECT_NAME:-chaosloop}-load-resources"
cleanup() {
  docker rm -f "$resource_name" >/dev/null 2>&1 || true
  docker rm -f "$guard_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM
load_metadata
ids=$(docker compose ps -q api postgres redis outbox-relay event-worker verifier)
mkdir -p artifacts/load-runs
docker stats --format '{{json .}}' $ids | load_compose run --rm --name "$resource_name" --no-deps -T load-resources > "artifacts/load-runs/resource-stream-$(date -u +%Y%m%dT%H%M%SZ).log" 2>&1 &
set +e
if [ "${LOAD_UI:-false}" = true ]; then
  echo "Locust UI: http://127.0.0.1:${LOCUST_UI_PORT:-8089}; manual session, profile-limited duration/users."
  load_compose run --rm --service-ports --use-aliases --no-deps -v "$PWD/.git:/revision:ro" load-controller python -m load_generator.controller.cli run "$@"
else
  load_compose run --rm --use-aliases --no-deps -v "$PWD/.git:/revision:ro" load-controller python -m load_generator.controller.cli run "$@"
fi
result=$?
set -e
mkdir -p artifacts/load-runs
load_compose run --rm --no-deps -T load-controller python -m load_generator.controller.cli export > artifacts/load-runs/latest-bundle.tar
tar -xf artifacts/load-runs/latest-bundle.tar -C artifacts/load-runs
exit "$result"
