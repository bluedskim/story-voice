"""Defaults for chunking, ASR verification, and post-processing."""

from __future__ import annotations

import os

# Pauses (seconds)
DEFAULT_SENTENCE_PAUSE = 0.35
DEFAULT_PARAGRAPH_PAUSE = 0.75
DIALOGUE_PAUSE_EXTRA = 0.12  # added before and after quoted dialogue chunks

# Sentence chunking
LONG_SENTENCE_COMMA_SPLIT_CHARS = 90
MIN_SENTENCE_MERGE_CHARS = 12

# ASR verification (Qwen3-ASR-0.6B-8bit)
DEFAULT_ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
DEFAULT_CER_THRESHOLD = 0.18  # ~1 wrong char per 5–6; retries only above this
DEFAULT_MAX_ASR_RETRIES = 2
DEFAULT_ASR_VERIFY = True

# Post-processing
LOUDNORM_I_LUFS = -16.0
TRIM_SILENCE_THRESHOLD_DB = -40


def asr_verify_enabled() -> bool:
    raw = os.environ.get("STORY_VOICE_ASR_VERIFY", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return DEFAULT_ASR_VERIFY
