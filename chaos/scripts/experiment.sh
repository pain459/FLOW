#!/bin/sh
. "$(dirname "$0")/common.sh"
command=${1:-list}
scenario=${2:-}
case "$command" in
  list|validate)
    chaos_cli "$command" ${scenario:+"$scenario"}
    ;;
  preflight|run)
    test -n "$scenario" || { echo 'A committed scenario name is required.' >&2; exit 1; }
    chaos_ready
    set +e
    chaos_cli "$command" "$scenario"
    result=$?
    set -e
    if [ "$command" = run ]; then chaos_export || exit 1; fi
    exit "$result"
    ;;
  *) echo 'Use list, validate, preflight or run.' >&2; exit 1 ;;
esac
