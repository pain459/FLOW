#!/bin/sh
# Thin local Docker entrypoints; native Chaos Toolkit owns the experiments.
set -eu
cd "$(dirname "$0")/../.."
chaos_compose() {
  if [ "${CHAOS_PROXY_ROUTING:-false}" = true ]; then
    docker compose -f compose.yaml -f compose.chaos.yaml -f compose.toxiproxy.yaml --profile chaos "$@"
  else
    docker compose -f compose.yaml -f compose.chaos.yaml --profile chaos "$@"
  fi
}
chaos_ready() {
  if [ "${CHAOS_IMAGE_PREBUILT:-false}" != true ]; then
    chaos_compose build chaos-runner
  fi
  chaos_compose --profile chaos up -d --wait docker-gate chaos-watchdog
}
chaos_cli() {
  chaos_compose run --rm --no-deps -T \
    -e ALLOW_DATABASE_CHAOS="${ALLOW_DATABASE_CHAOS:-false}" \
    -e CHAOS_IMAGE_ID="$(docker image inspect pulsepay-chaos:v1 --format '{{.Id}}')" \
    chaos-runner "$@"
}
chaos_export() {
  mkdir -p artifacts/chaos
  chaos_cli export "${1:-latest}" > artifacts/chaos/latest-bundle.tar
  tar -xf artifacts/chaos/latest-bundle.tar -C artifacts/chaos
}
