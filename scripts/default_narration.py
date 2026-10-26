"""Shared default narrator voice and catalog-wide default story audio."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from user_storage import ROOT, REF_TXT_NAME, REF_WAV_NAME

SYSTEM_USER_ID = 0


def default_voice_dir() -> Path:
    raw = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "voice" / "default"


def default_audio_dir() -> Path:
    raw = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "audio" / "default"


DEFAULT_VOICE_DIR = default_voice_dir()
DEFAULT_AUDIO_DIR = default_audio_dir()
DEFAULT_SOURCE_WAV = DEFAULT_VOICE_DIR / "default-narration-source.wav"
DEFAULT_REF_WAV = DEFAULT_VOICE_DIR / REF_WAV_NAME
DEFAULT_REF_TXT = DEFAULT_VOICE_DIR / REF_TXT_NAME
RECORD_SCRIPT = ROOT / "content" / "record_script.txt"


def default_story_audio(story_id: str) -> Path:
    return default_audio_dir() / f"{story_id}.m4a"


def has_default_reference() -> bool:
    voice_dir = default_voice_dir()
    return (voice_dir / REF_WAV_NAME).is_file() and (voice_dir / REF_TXT_NAME).is_file()


def ensure_default_reference() -> tuple[Path, Path]:
    """
    Ensure system reference wav/txt exist under data/voice/default/.
    Uses default-narration-source.wav or reference.wav; never deletes existing files.
    """
    voice_dir = default_voice_dir()
    ref_wav = voice_dir / REF_WAV_NAME
    ref_txt = voice_dir / REF_TXT_NAME
    source_wav = voice_dir / "default-narration-source.wav"
    voice_dir.mkdir(parents=True, exist_ok=True)
    if not ref_wav.is_file():
        if source_wav.is_file():
            shutil.copy2(source_wav, ref_wav)
        elif DEFAULT_SOURCE_WAV.is_file():
            shutil.copy2(DEFAULT_SOURCE_WAV, ref_wav)
        else:
            raise RuntimeError(
                "기본 낭독 목소리 파일이 없어요. data/voice/default/ 에 "
                "default-narration-source.wav 또는 reference.wav 를 넣어 주세요."
            )
    if not ref_txt.is_file():
        script = RECORD_SCRIPT.read_text(encoding="utf-8").strip() if RECORD_SCRIPT.is_file() else ""
        if not script:
            raise RuntimeError("기본 낭독용 reference.txt 가 없고 record_script.txt 도 비어 있어요.")
        ref_txt.write_text(script + "\n", encoding="utf-8")
    return ref_wav, ref_txt


def resolve_story_audio_path(user_id: int, story_id: str) -> Path | None:
    """Playback path: personal audio first, else shared default."""
    from user_storage import user_story_audio

    personal = user_story_audio(user_id, story_id)
    if personal.is_file():
        return personal
    default = default_story_audio(story_id)
    if default.is_file():
        return default
    return None


def story_audio_meta(user_id: int, story_id: str) -> dict:
    from user_storage import has_user_reference, user_story_audio

    personal = user_story_audio(user_id, story_id).is_file()
    default = default_story_audio(story_id).is_file()
    has_audio = personal or default
    meta = {
        "hasAudio": has_audio,
        "hasPersonalAudio": personal,
        "hasDefaultAudio": default,
        "canGeneratePersonal": has_user_reference(user_id),
    }
    if has_audio:
        meta["audioUrl"] = f"/audio/{story_id}.m4a"
        meta["audioSource"] = "personal" if personal else "default"
    return meta
