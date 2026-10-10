#!/bin/sh
. "$(dirname "$0")/load-common.sh"
load_compose build load-controller
load_metadata
load_compose run --rm --no-deps load-controller python -m load_generator.controller.cli preflight --profile "${PROFILE:-nominal}"
