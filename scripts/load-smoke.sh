#!/bin/sh
set -eu
PROFILE=smoke sh "$(dirname "$0")/load-run.sh"
