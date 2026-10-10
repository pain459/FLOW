#!/bin/sh
# Sourced by operator wrappers; only Docker and ordinary POSIX shell tools needed.
set -eu
cd "$(dirname "$0")/.."
load_compose() { docker compose -f compose.yaml -f compose.load.yaml "$@"; }
load_metadata() {
  ids=$(docker compose ps -a -q api postgres redis outbox-relay event-worker verifier prometheus grafana)
  {
    if [ -n "$ids" ]; then
      docker inspect --format '{"service":{{json (index .Config.Labels "com.docker.compose.service")}},"running":{{.State.Running}},"health":{{if index .State "Health"}}{{json (index (index .State "Health") "Status")}}{{else}}null{{end}},"image_id":{{json .Image}},"image_tag":{{json .Config.Image}},"cpu_limit":{{.HostConfig.NanoCpus}},"memory_limit_bytes":{{.HostConfig.Memory}},"config":[{{$separator := ""}}{{range .Config.Env}}{{$key := index (split . "=") 0}}{{if or (eq $key "DB_POOL_SIZE") (eq $key "DB_TIMEOUT_SECONDS") (eq $key "REQUEST_TIMEOUT_SECONDS") (eq $key "CACHE_TTL_SECONDS") (eq $key "PULSEPAY_CURRENCY") (eq $key "WORKER_POLL_SECONDS") (eq $key "RECLAIM_IDLE_MS") (eq $key "VERIFIER_INTERVAL_SECONDS") (eq $key "SEED_VERSION") (eq $key "SEED_ACCOUNT_COUNT") (eq $key "SEED_BALANCE_MINOR")}}{{$separator}}{{json .}}{{$separator = ","}}{{end}}{{end}}]}' $ids
    fi
    docker image inspect "${LOAD_IMAGE:-pulsepay-load:v1}" --format '{"service":"load-controller","image_id":{{json .Id}},"image_tag":{{json .Id}}}'
    docker info --format '{"docker_cpus":{{.NCPU}},"docker_memory_bytes":{{.MemTotal}},"docker_version":{{json .ServerVersion}},"architecture":{{json .Architecture}},"os":{{json .OSType}}}'
  } | load_compose run --rm --no-deps -T load-controller python -m load_generator.controller.cli metadata
}
