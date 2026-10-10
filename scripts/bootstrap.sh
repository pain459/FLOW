#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  umask 077
  docker run --rm --memory 128m --cpus 0.5 --pids-limit 32 --network none --user "$(id -u):$(id -g)" -v "$PWD:/workspace" python:3.12.10-slim-bookworm python -c '
from pathlib import Path
import secrets
p=Path("/workspace/.env")
text=Path("/workspace/.env.example").read_text()
for line in text.splitlines():
    if "replace_with_generated_secret" in line:
        text=text.replace(line, line.split("=")[0]+"="+secrets.token_hex(24))
with p.open("x") as f: f.write(text)
p.chmod(0o600)
print("Generated local .env; secrets not printed")'
fi
docker compose build
docker compose up -d postgres redis
docker compose run --rm migrate
