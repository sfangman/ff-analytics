#!/usr/bin/env bash
# Pull ESPN data and rebuild output/site/index.html
set -euo pipefail
cd "$(dirname "$0")"

uv run --env-file .env metrics.py
uv run dashboard.py
