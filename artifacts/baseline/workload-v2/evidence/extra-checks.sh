#!/bin/sh
set -eu
cd /Users/ravik/src_git/FLOW
export COMPOSE_PROJECT_NAME=chaosloop-load-baseline
export API_PORT=18080 PROMETHEUS_PORT=18090 GRAFANA_PORT=18000 LOG_COLLECTOR_PORT=34224 LOCUST_UI_PORT=18089
export SEED_VERSION=pulsepay-v1 LOAD_IMAGE=pulsepay-load:qualified-20261010T142752Z LOAD_IMAGE_PREBUILT=true
dc() { docker compose -f compose.yaml -f compose.load.yaml "$@"; }
test "$COMPOSE_PROJECT_NAME" = chaosloop-load-baseline
dc stop api outbox-relay event-worker verifier >/dev/null
dc exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --single-transaction' < artifacts/load-runs/qualification-seed.dump
dc exec -T redis redis-cli FLUSHALL >/dev/null
dc --profile observability up -d --wait api outbox-relay event-worker verifier >/dev/null
PROFILE=burst DURATION=60 WARMUP=30 USERS=30 sh scripts/load-run.sh > artifacts/load-runs/current-bounded-burst.log 2>&1
PROFILE=step_ramp DURATION=30 WARMUP=5 USERS=40 RATE=20 sh scripts/load-run.sh > artifacts/load-runs/current-step-ramp.log 2>&1
PROFILE=soak DURATION=30 WARMUP=5 USERS=20 RATE=10 sh scripts/load-run.sh > artifacts/load-runs/current-short-soak.log 2>&1
PROFILE=journeys DURATION=30 WARMUP=5 USERS=5 RATE=5 sh scripts/load-run.sh > artifacts/load-runs/current-journeys.log 2>&1
PROFILE=nominal DURATION=30 WARMUP=5 USERS=10 RATE=20 WORKERS=2 sh scripts/load-run.sh > artifacts/load-runs/current-multiworker.log 2>&1
