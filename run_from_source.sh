#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m clippiti "$@"
