#!/bin/sh
# Disruptive acceptance test of this disposable lab only; no Docker socket in containers.
set -eu
cd "$(dirname "$0")/.."
operation="recovery-$(date +%s)"
mkdir -p artifacts/baseline
probe() {
  docker compose run --rm --no-deps -v "$PWD/tests:/app/tests:ro" -v "$PWD/artifacts/baseline:/evidence:ro" tests python tests/e2e/recovery.py "$1" --key "$operation" > "artifacts/baseline/recovery-$1.json"
}
# Restore only the named services on any failed gate.
trap 'docker compose start postgres redis event-worker api outbox-relay >/dev/null' EXIT
docker compose stop redis
probe redis-outage
docker compose start redis
probe redis-recovery
docker compose stop event-worker
probe pending-setup
docker compose start event-worker
probe pending-recovery
docker compose stop postgres
probe db-outage
set +e
docker compose run --rm --no-deps verifier python -m verifier.main --once > artifacts/baseline/database-outage-verification.json
result=$?
set -e
[ "$result" -eq 2 ] || { echo 'Verifier did not exit UNKNOWN=2' >&2; exit 1; }
docker compose start postgres
probe db-recovery
probe snapshot
docker compose restart api outbox-relay event-worker redis prometheus grafana loki tempo
probe persistence
docker compose run --rm --no-deps verifier python -m verifier.main --once > artifacts/baseline/recovery-verification.json
echo 'Recovery gates PASS; no automatic client traffic is configured'
