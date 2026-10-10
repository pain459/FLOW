#!/bin/sh
. "$(dirname "$0")/common.sh"
# This stops faults, with no workload-control or application teardown command.
chaos_cli abort
