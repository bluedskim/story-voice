"""TTS / dialogue style defaults (env overrides)."""

from __future__ import annotations

import os

DEFAULT_MAX_CHARS = 120
DEFAULT_SENTENCE_PAUSE = 0.35
DEFAULT_PARAGRAPH_PAUSE = 0.75

# Dialogue post-process (pitch + gain + short fades on chunk boundaries)
DEFAULT_DIALOGUE_PITCH_ST = 1.5
DEFAULT_DIALOGUE_GAIN_DB = 2.0
DEFAULT_DIALOGUE_FADE_SEC = 0.012

# Optional EBU loudnorm on narration chunks only (keeps dialogue relatively louder)
DEFAULT_NARRATION_LOUDNORM_I = -23.0


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def dialogue_pitch_semitones() -> float:
    return _float_env("STORY_VOICE_DIALOGUE_PITCH_ST", DEFAULT_DIALOGUE_PITCH_ST)


def dialogue_gain_db() -> float:
    return _float_env("STORY_VOICE_DIALOGUE_GAIN_DB", DEFAULT_DIALOGUE_GAIN_DB)


def dialogue_fade_sec() -> float:
    return _float_env("STORY_VOICE_DIALOGUE_FADE_SEC", DEFAULT_DIALOGUE_FADE_SEC)


def narration_loudnorm_enabled() -> bool:
    raw = os.environ.get("STORY_VOICE_NARRATION_LOUDNORM", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def narration_loudnorm_integrated() -> float:
    return _float_env("STORY_VOICE_NARRATION_LOUDNORM_I", DEFAULT_NARRATION_LOUDNORM_I)


def dialogue_style_enabled() -> bool:
    raw = os.environ.get("STORY_VOICE_DIALOGUE_STYLE", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return True
