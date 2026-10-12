#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps decision-evaluator "$@"
