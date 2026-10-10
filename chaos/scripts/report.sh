#!/bin/sh
. "$(dirname "$0")/common.sh"
chaos_cli report "${1:-latest}"
chaos_export "${1:-latest}"
