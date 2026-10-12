#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
docker compose -f compose.yaml -f compose.phase4.yaml exec -T incident-controller python -m decision_engine.cli ask "$@"
