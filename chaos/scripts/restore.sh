#!/bin/sh
. "$(dirname "$0")/common.sh"
test "${1:-verify}" = verify || { echo 'Use restore.sh verify.' >&2; exit 1; }
chaos_cli restore
