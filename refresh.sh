#!/usr/bin/env bash
# Pull ESPN data and rebuild docs/index.html
set -euo pipefail
cd "$(dirname "$0")"

uv run --env-file .env metrics.py
uv run dashboard.py
