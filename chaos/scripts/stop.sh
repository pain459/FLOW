#!/bin/sh
# Remove daemon authority only after active restoration and reporting finish.
. "$(dirname "$0")/common.sh"
chaos_cli abort
chaos_compose run --rm --no-deps -T --entrypoint python chaos-runner -c '
import time
from chaos.docker_client import Docker
deadline=time.monotonic()+90
while Docker().lease():
    if time.monotonic()>=deadline:
        raise SystemExit("Lease remains active; run chaos-restore and retain tools for recovery")
    time.sleep(0.5)
print("No active authorization lease; stopping watchdog and Docker gate")
'
chaos_compose stop chaos-watchdog docker-gate
