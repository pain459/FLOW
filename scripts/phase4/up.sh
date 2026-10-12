#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
docker run --rm --network none --memory 128m --cpus .5 -v "$PWD:/workspace" python:3.12.10-slim-bookworm python /workspace/scripts/phase4/prepare.py
docker compose build api
docker compose -f compose.yaml -f compose.phase4.yaml build incident-controller laya-service decision-roles
docker compose -f compose.yaml -f compose.phase4.yaml up -d postgres redis
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps decision-roles
docker compose -f compose.yaml -f compose.phase4.yaml run --rm --no-deps decision-migrate
docker compose -f compose.yaml -f compose.phase4.yaml --profile observability --profile chaos --profile intelligence up -d
# Weights are deliberately provisioned by intelligence-setup, never downloaded by up.
