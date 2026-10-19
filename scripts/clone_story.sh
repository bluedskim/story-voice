#!/usr/bin/env bash
# Generate one story with the parent's cloned voice (Mac mini + MLX).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Create a venv first: uv venv --python 3.12 && source .venv/bin/activate" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

STORY="${1:-content/stories/ui-joeun-hyeongje.txt}"
shift || true

exec python scripts/clone_story.py "$STORY" "$@"
