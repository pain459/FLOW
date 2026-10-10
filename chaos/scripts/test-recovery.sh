#!/bin/sh
# Explicit acceptance test: interrupt only our named runner's worker pause.
. "$(dirname "$0")/common.sh"
case "${CHAOS_RECOVERY_MODE:-kill}" in
  kill|abort) pulsepay_mode=${CHAOS_RECOVERY_MODE:-kill} ;;
  *) echo 'CHAOS_RECOVERY_MODE must be kill or abort' >&2; exit 1 ;;
esac
chaos_ready
pulsepay_runner=chaosloop-chaos-recovery-test-$pulsepay_mode
pulsepay_target=$(docker compose ps -q event-worker)
test -n "$pulsepay_target"
test "$(docker inspect "$pulsepay_target" --format '{{index .Config.Labels "com.docker.compose.project"}}')" = chaosloop
test "$(docker inspect "$pulsepay_target" --format '{{index .Config.Labels "io.pulsepay.chaos.role"}}')" = event-worker
test "$(docker inspect "$pulsepay_target" --format '{{.State.Paused}}')" = false
chaos_compose run -d --name "$pulsepay_runner" --no-deps \
  -e CHAOS_IMAGE_ID="$(docker image inspect pulsepay-chaos:v1 --format '{{.Id}}')" \
  chaos-runner run 002-worker-pause >/dev/null
trap 'docker rm -f "$pulsepay_runner" >/dev/null 2>&1 || true' EXIT HUP INT TERM
pulsepay_waited=0
while [ "$(docker inspect "$pulsepay_target" --format '{{.State.Paused}}')" != true ]; do
  test "$(docker inspect "$pulsepay_runner" --format '{{.State.Running}}')" = true || {
    docker logs "$pulsepay_runner" >&2
    exit 1
  }
  test "$pulsepay_waited" -lt 65 || exit 1
  sleep 1
  pulsepay_waited=$((pulsepay_waited + 1))
done
pulsepay_killed_at=$(date +%s)
if [ "$pulsepay_mode" = kill ]; then
  docker kill --signal=KILL "$pulsepay_runner" >/dev/null
else
  chaos_cli abort
fi
pulsepay_waited=0
while [ "$(docker inspect "$pulsepay_target" --format '{{.State.Paused}}')" = true ]; do
  test "$pulsepay_waited" -lt 30 || { chaos_cli restore; exit 1; }
  sleep 1
  pulsepay_waited=$((pulsepay_waited + 1))
done
pulsepay_restored_at=$(date +%s)
printf '{"stage":"interrupted_target_restored","mode":"%s","seconds_after_interruption":%s}\n' "$pulsepay_mode" "$((pulsepay_restored_at - pulsepay_killed_at))"
if [ "$pulsepay_mode" = kill ]; then
  chaos_cli restore
else
  pulsepay_waited=0
  while [ "$(docker inspect "$pulsepay_runner" --format '{{.State.Running}}')" = true ]; do
    test "$pulsepay_waited" -lt 60 || { chaos_cli restore; exit 1; }
    sleep 1
    pulsepay_waited=$((pulsepay_waited + 1))
  done
  docker logs "$pulsepay_runner"
fi
chaos_compose run --rm --no-deps -T --entrypoint python chaos-runner -c '
from chaos import state
import json,sys
identifier=state.read(state.EVIDENCE/"latest.json")["run_id"]
trigger=state.read(state.CONTROL/identifier/"watchdog-triggered.json")
summary=state.read(state.EVIDENCE/identifier/"summary.json")
assert trigger["reason"]==("RUNNER_HEARTBEAT_LOST" if sys.argv[1]=="kill" else "OPERATOR_ABORT"), trigger
assert summary["result"]=="ABORTED" and summary["restoration"]=="RESTORED", summary
assert summary["integrity"]["after"]=="PASS", summary
print(json.dumps({"run_id":identifier,"recovery_test":"PASS","watchdog_trigger":trigger}))
' "$pulsepay_mode"
chaos_export
