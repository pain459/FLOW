#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
mkdir -p artifacts/phase4/sessions
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps decision-export
