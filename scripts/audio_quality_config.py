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
# Peak limit after loudness match (~-1 dBFS) before fade-out
DIALOGUE_PEAK_LIMITER = "alimiter=limit=0.89:level=false"

DEFAULT_DIALOGUE_EQ_PRESET = "airy"

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

# Final story loudnorm (after concat + dialogue EQ)
DEFAULT_FINAL_LOUDNORM_I = -16.0
DEFAULT_FINAL_LOUDNORM = True

# ASR verification (opt-in)
DEFAULT_ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
DEFAULT_CER_THRESHOLD = 0.18
DEFAULT_MAX_ASR_RETRIES = 2
MASS_RETRY_FAIL_FRACTION = 0.5
DEFAULT_ASR_VERIFY = False


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
    """Custom ffmpeg chain, named preset, or default ``airy`` when dialogue style is on."""
    custom = os.environ.get("STORY_VOICE_DIALOGUE_EQ", "").strip()
    if custom:
        return custom
    preset = os.environ.get("STORY_VOICE_DIALOGUE_EQ_PRESET", "").strip().lower()
    if preset in {"off", "none", "0"}:
        return None
    if not preset:
        preset = DEFAULT_DIALOGUE_EQ_PRESET
    return DIALOGUE_EQ_PRESETS.get(preset)


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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return default


def final_loudnorm_enabled() -> bool:
    return _bool_env("STORY_VOICE_LOUDNORM", DEFAULT_FINAL_LOUDNORM)


def final_loudnorm_integrated() -> float:
    return _float_env("STORY_VOICE_LOUDNORM_I", DEFAULT_FINAL_LOUDNORM_I)


def asr_verify_enabled() -> bool:
    return _bool_env("STORY_VOICE_ASR_VERIFY", DEFAULT_ASR_VERIFY)


def resolve_asr_verify(request_flag: bool | None) -> bool:
    """ASR verify for one generation run.

    Precedence: an explicit per-request flag (admin UI JSON ``asrVerify``) wins;
    when the flag is omitted (CLI, launchd, empty POST body), use ``STORY_VOICE_ASR_VERIFY``.
    """
    if request_flag is not None:
        return request_flag
    return asr_verify_enabled()


def parse_asr_verify_body(body: dict | None) -> bool | None:
    """Extract optional ``asrVerify`` from a generation POST body; ``None`` if absent."""
    if body is None:
        return None
    if "asrVerify" not in body:
        return None
    val = body["asrVerify"]
    if isinstance(val, bool):
        return val
    raise ValueError("asrVerify must be a boolean")


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
