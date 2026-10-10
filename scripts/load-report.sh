#!/bin/sh
. "$(dirname "$0")/load-common.sh"
load_compose run --rm --no-deps load-controller python -m load_generator.controller.cli report
