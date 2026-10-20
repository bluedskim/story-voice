#!/usr/bin/env python3
"""One-shot ASR for voice upload (separate process; exits and releases MLX RAM)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from voice_asr import DEFAULT_ASR_MODEL, extract_transcript


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: voice_asr_worker.py <wav>", file=sys.stderr)
        return 2
    wav = Path(sys.argv[1])
    if not wav.is_file():
        print("missing wav", file=sys.stderr)
        return 2
    model_id = os.environ.get("STORY_VOICE_ASR_MODEL", DEFAULT_ASR_MODEL)
    from mlx_audio.stt import load

    model = load(model_id)
    result = model.generate(str(wav), language="Korean")
    text = extract_transcript(result)
    print(json.dumps({"text": text}, ensure_ascii=False))
    del model
    try:
        import mlx.core as mx

        mx.clear_cache()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
