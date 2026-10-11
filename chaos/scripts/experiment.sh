#!/bin/sh
. "$(dirname "$0")/common.sh"
command=${1:-list}
scenario=${2:-}
test "$#" -le 2 || { echo 'Only a reviewed command and scenario are accepted; use DURATION for exposure seconds.' >&2; exit 1; }
set -- "$command" ${scenario:+"$scenario"}
if [ -n "${DURATION:-}" ]; then
  case "$command" in validate|preflight|run) ;; *) echo 'DURATION applies only to validate, preflight or run.' >&2; exit 1 ;; esac
  case "$DURATION" in *[!0-9]*) echo 'DURATION must be integer seconds (3..300).' >&2; exit 1 ;; esac
  set -- "$@" --duration-seconds "$DURATION"
fi
case "$command" in
  list|validate)
    chaos_cli "$@"
    ;;
  preflight|run)
    test -n "$scenario" || { echo 'A committed scenario name is required.' >&2; exit 1; }
    chaos_ready
    set +e
    chaos_cli "$@"
    result=$?
    set -e
    if [ "$command" = run ]; then chaos_export || exit 1; fi
    exit "$result"
    ;;
  *) echo 'Use list, validate, preflight or run.' >&2; exit 1 ;;
esac
