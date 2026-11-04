"""Shared default narrator voice and catalog-wide default story audio."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from user_storage import ROOT, REF_TXT_NAME, REF_WAV_NAME

SYSTEM_USER_ID = 0

DEFAULT_VOICE_IDS = frozenset({"harry", "dana", "anna"})


@dataclass(frozen=True)
class LocalOnlyVoicePaths:
    """Packaged reference under default voice root, plus a gitignored local wav path."""

    subdir: str
    local_wav: Path

    def packaged_wav(self, voice_root: Path) -> Path:
        return voice_root / self.subdir / REF_WAV_NAME

    def expected_locations_hint(self, voice_root: Path) -> str:
        parts = [str(self.packaged_wav(voice_root)), str(self.local_wav)]
        return " or ".join(parts)


LOCAL_ONLY_VOICES: dict[str, LocalOnlyVoicePaths] = {
    "harry": LocalOnlyVoicePaths(
        subdir="harry",
        local_wav=ROOT / "data" / "voice" / "harry" / "harry_script_reference.wav",
    ),
    "anna": LocalOnlyVoicePaths(
        subdir="anna",
        local_wav=ROOT / "data" / "voice" / "anna" / REF_WAV_NAME,
    ),
}

log = logging.getLogger("story_voice.default_narration")


class DefaultReferenceUnavailable(Exception):
    """Default narrator reference is missing (no silent fallback to another voice)."""

    def __init__(self, voice: str, *, story_id: str | None = None, detail: str = "") -> None:
        self.voice = voice
        self.story_id = story_id
        self.detail = detail
        msg = f"default voice reference unavailable: {voice}"
        if story_id:
            msg += f" (story {story_id})"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


def default_voice_root() -> Path:
    raw = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "voice" / "default"


def default_audio_dir() -> Path:
    raw = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "audio" / "default"


DEFAULT_VOICE_DIR = default_voice_root()
DEFAULT_AUDIO_DIR = default_audio_dir()
DEFAULT_SOURCE_WAV = DEFAULT_VOICE_DIR / "default-narration-source.wav"
DEFAULT_REF_WAV = DEFAULT_VOICE_DIR / REF_WAV_NAME
DEFAULT_REF_TXT = DEFAULT_VOICE_DIR / REF_TXT_NAME
RECORD_SCRIPT = ROOT / "content" / "record_script.txt"


def normalize_default_voice_id(raw: str) -> str:
    voice = raw.strip().lower()
    if voice not in DEFAULT_VOICE_IDS:
        raise ValueError(f"unsupported default voice: {raw!r}")
    return voice


def story_default_voice(story_id: str) -> str:
    from story_catalog import STORIES_DIR, load_story

    path = STORIES_DIR / f"{story_id}.txt"
    if not path.is_file():
        raise KeyError(story_id)
    return load_story(path).default_voice


def voice_reference_dir(voice_id: str) -> Path:
    """Directory used for packaged reference files (Dana: legacy default root)."""
    voice = normalize_default_voice_id(voice_id)
    if voice == "dana":
        return default_voice_root()
    paths = LOCAL_ONLY_VOICES.get(voice)
    if paths:
        return default_voice_root() / paths.subdir
    raise ValueError(f"unsupported default voice: {voice_id!r}")


def resolve_local_only_reference_wav(voice_id: str) -> Path | None:
    voice = normalize_default_voice_id(voice_id)
    paths = LOCAL_ONLY_VOICES.get(voice)
    if not paths:
        return None
    voice_root = default_voice_root()
    packaged = paths.packaged_wav(voice_root)
    if packaged.is_file():
        return packaged
    if paths.local_wav.is_file():
        return paths.local_wav
    return None


def local_only_reference_available(voice_id: str) -> bool:
    return resolve_local_only_reference_wav(voice_id) is not None


def resolve_harry_reference_wav() -> Path | None:
    return resolve_local_only_reference_wav("harry")


def harry_reference_available() -> bool:
    return local_only_reference_available("harry")


def resolve_local_only_reference_txt(voice_id: str, wav: Path) -> Path:
    voice = normalize_default_voice_id(voice_id)
    candidates = [
        wav.with_suffix(".txt"),
        wav.parent / REF_TXT_NAME,
    ]
    for path in candidates:
        if path.is_file():
            return path
    if RECORD_SCRIPT.is_file() and RECORD_SCRIPT.read_text(encoding="utf-8").strip():
        return RECORD_SCRIPT
    raise DefaultReferenceUnavailable(
        voice,
        detail=f"{voice} reference transcript missing (add .txt beside the wav or content/record_script.txt)",
    )


def resolve_harry_reference_txt(wav: Path) -> Path:
    return resolve_local_only_reference_txt("harry", wav)


def local_only_reference_detail(voice_id: str) -> str:
    voice = normalize_default_voice_id(voice_id)
    paths = LOCAL_ONLY_VOICES[voice]
    return f"expected {paths.expected_locations_hint(default_voice_root())}"


def can_generate_default_narration(story_id: str) -> bool:
    voice = story_default_voice(story_id)
    if voice in LOCAL_ONLY_VOICES:
        return local_only_reference_available(voice)
    return True


def default_story_audio(story_id: str) -> Path:
    return default_audio_dir() / f"{story_id}.m4a"


def has_default_reference(voice_id: str | None = None) -> bool:
    voice = normalize_default_voice_id(voice_id or "dana")
    if voice in LOCAL_ONLY_VOICES:
        return local_only_reference_available(voice)
    voice_dir = voice_reference_dir(voice)
    if (voice_dir / REF_WAV_NAME).is_file() and (voice_dir / REF_TXT_NAME).is_file():
        return True
    return (voice_dir / "default-narration-source.wav").is_file() or (voice_dir / REF_WAV_NAME).is_file()


def ensure_default_reference(voice_id: str | None = None) -> tuple[Path, Path]:
    """
    Ensure system reference wav/txt exist for a catalog default voice (harry | dana | anna).
    Dana uses legacy data/voice/default/ (default-narration-source.wav → reference.wav).
    Local-only voices use packaged reference.wav under default/<voice>/ or a gitignored local wav.
    """
    voice = normalize_default_voice_id(voice_id or "dana")
    if voice in LOCAL_ONLY_VOICES:
        wav = resolve_local_only_reference_wav(voice)
        if wav is None:
            raise DefaultReferenceUnavailable(voice, detail=local_only_reference_detail(voice))
        return wav, resolve_local_only_reference_txt(voice, wav)

    voice_dir = voice_reference_dir(voice)
    ref_wav = voice_dir / REF_WAV_NAME
    ref_txt = voice_dir / REF_TXT_NAME
    source_wav = voice_dir / "default-narration-source.wav"
    voice_dir.mkdir(parents=True, exist_ok=True)
    if not ref_wav.is_file():
        if source_wav.is_file():
            shutil.copy2(source_wav, ref_wav)
        else:
            raise DefaultReferenceUnavailable(
                "dana",
                detail=f"{voice_dir}/ 에 default-narration-source.wav 또는 reference.wav 가 필요해요.",
            )
    if not ref_txt.is_file():
        script = RECORD_SCRIPT.read_text(encoding="utf-8").strip() if RECORD_SCRIPT.is_file() else ""
        if not script:
            raise RuntimeError("기본 낭독용 reference.txt 가 없고 record_script.txt 도 비어 있어요.")
        ref_txt.write_text(script + "\n", encoding="utf-8")
    return ref_wav, ref_txt


def ensure_default_reference_for_story(story_id: str) -> tuple[Path, Path]:
    voice = story_default_voice(story_id)
    if voice in LOCAL_ONLY_VOICES and not local_only_reference_available(voice):
        raise DefaultReferenceUnavailable(voice, story_id=story_id)
    return ensure_default_reference(voice)


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
