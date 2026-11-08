#!/bin/sh
# Run the toolkit's offline tests (no Canvas, no network).
cd "$(dirname "$0")/.." && exec uv run --quiet --python 3.12 \
  --with pytest --with requests --with beautifulsoup4 --with pyyaml \
  pytest -q tests "$@"
