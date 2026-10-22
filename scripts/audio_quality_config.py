"""TTS / dialogue style defaults (env overrides)."""

from __future__ import annotations

import os

DEFAULT_MAX_CHARS = 120
DEFAULT_SENTENCE_PAUSE = 0.35
DEFAULT_PARAGRAPH_PAUSE = 0.75

# Dialogue post-process (EQ by default; pitch/gain optional, default off)
DEFAULT_DIALOGUE_PITCH_ST = 0.0
DEFAULT_DIALOGUE_GAIN_DB = 0.0
DEFAULT_DIALOGUE_FADE_SEC = 0.012

DIALOGUE_EQ_PRESETS: dict[str, str] = {
    "bright": (
        "highpass=f=90,equalizer=f=250:t=q:w=1.0:g=-2.5,"
        "equalizer=f=3000:t=q:w=1.2:g=3.5,treble=g=2:f=8000"
    ),
    "warm": (
        "bass=g=2.5:f=180,equalizer=f=500:t=q:w=1.0:g=-1.5,"
        "equalizer=f=2500:t=q:w=1.0:g=2"
    ),
    "airy": (
        "highpass=f=110,equalizer=f=300:t=q:w=1.0:g=-3,"
        "equalizer=f=5000:t=q:w=1.0:g=3,treble=g=3:f=10000"
    ),
}

# Optional EBU loudnorm on narration chunks only
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


def dialogue_eq_filter() -> str | None:
    """Custom ffmpeg audio filter chain, or named preset, or None (EQ off)."""
    custom = os.environ.get("STORY_VOICE_DIALOGUE_EQ", "").strip()
    if custom:
        return custom
    preset = os.environ.get("STORY_VOICE_DIALOGUE_EQ_PRESET", "").strip().lower()
    if preset:
        chain = DIALOGUE_EQ_PRESETS.get(preset)
        if chain:
            return chain
    return None


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


def dialogue_post_should_run() -> bool:
    if not dialogue_style_enabled():
        return False
    if dialogue_eq_filter():
        return True
    if abs(dialogue_pitch_semitones()) > 1e-9:
        return True
    if abs(dialogue_gain_db()) > 1e-9:
        return True
    return False
