#!/usr/bin/env bash
# Daily AI funnel maintenance: refresh quotes, recompute tiers, fail on stale data.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m fdc.quotes "$@"
uv run python -m fdc.funnel
uv run python -m fdc.funnel --check
