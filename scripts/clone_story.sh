#!/usr/bin/env bash
# Validated usage:
#   scripts/clone_story.sh <ref.wav> <ref_transcript(.txt or string)> <story.txt> [out.wav]
# Catalog shortcut (defaults under data/voice/ and data/audio/):
#   scripts/clone_story.sh content/stories/ui-joeun-hyeongje.txt
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/python ]]; then
  echo "Create venv first: uv venv --python 3.12 && uv pip install -r requirements-mlx.txt" >&2
  exit 1
fi

if [[ $# -ge 3 ]]; then
  REF="$1"
  REFTXT="$2"
  STORY="$3"
  OUT="${4:-out/story_$(date +%Y%m%d_%H%M%S).wav}"
  shift $(( $# >= 4 ? 4 : 3 ))
  exec .venv/bin/python scripts/clone_story.py --ref-audio "$REF" --ref-text "$REFTXT" --story "$STORY" --out "$OUT" "$@"
fi

if [[ $# -eq 1 ]]; then
  exec .venv/bin/python scripts/clone_story.py "$1" "${@:2}"
fi

echo "Usage:" >&2
echo "  $0 <ref.wav> <ref.txt> <story.txt> [out.wav]" >&2
echo "  $0 content/stories/<id>.txt" >&2
exit 1
