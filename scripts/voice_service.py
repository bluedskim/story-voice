"""Save parent voice reference (ffmpeg convert, backup, validation)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cer import character_error_rate
from user_storage import (
    user_ref_txt,
    user_ref_wav,
    user_voice_dir,
    user_voice_history_dir,
    user_voice_pending_dir,
    has_user_reference,
)

ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPT = ROOT / "content" / "record_script.txt"

# Legacy module-level aliases (tests / CLI that pass user_id via save_reference)
VOICE_DIR = ROOT / "data" / "voice"
REF_WAV = VOICE_DIR / "reference.wav"
REF_TXT = VOICE_DIR / "reference.txt"

MIN_DURATION_SEC = 5.0
MAX_DURATION_SEC = 40.0
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB raw upload

MIN_CHARS_PER_SEC = 2.0
MAX_CHARS_PER_SEC = 11.0

WARN_EDIT_CER_THRESHOLD = 0.35


class VoiceSaveError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def default_record_script() -> str:
    if RECORD_SCRIPT.is_file():
        return RECORD_SCRIPT.read_text(encoding="utf-8").strip()
    return ""


def expected_script_for_match(user_id: int) -> str:
    ref_txt = user_ref_txt(user_id)
    if ref_txt.is_file():
        text = ref_txt.read_text(encoding="utf-8").strip()
        if text:
            return text
    return default_record_script()


def probe_duration_sec(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError):
        raise VoiceSaveError(
            "오디오 길이를 확인할 수 없어요. 다른 파일로 다시 시도해 주세요.",
            "invalid_audio",
        )


def convert_to_reference_wav(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        raise VoiceSaveError(
            "오디오 파일을 읽을 수 없어요. 녹음 파일이나 m4a·wav 형식을 올려 주세요.",
            "invalid_audio",
        )


def validate_duration_sec(duration: float) -> None:
    if duration < MIN_DURATION_SEC:
        raise VoiceSaveError(
            f"녹음이 너무 짧아요 ({duration:.1f}s). {MIN_DURATION_SEC:.0f}초 이상이 필요해요.",
            "too_short",
        )
    if duration > MAX_DURATION_SEC:
        raise VoiceSaveError(
            f"녹음이 너무 길아요 ({duration:.1f}s). {MAX_DURATION_SEC:.0f}초 이하로 해 주세요.",
            "too_long",
        )


def validate_text_fits_duration(transcript: str, duration_sec: float) -> None:
    text = transcript.strip()
    if not text:
        raise VoiceSaveError("받아쓰기를 입력해 주세요.", "empty_transcript")
    char_count = len(text)
    min_chars = MIN_CHARS_PER_SEC * duration_sec
    max_chars = MAX_CHARS_PER_SEC * duration_sec
    if char_count > max_chars:
        raise VoiceSaveError(
            f"받아쓰기가 녹음 길이({duration_sec:.1f}초)에 비해 너무 깁니다 "
            f"({char_count}자). 녹음과 같은 내용만 적어 주세요. "
            f"이 길이에서는 보통 {int(max_chars)}자 이하가 맞아요.",
            "text_too_long_for_audio",
        )
    if char_count < min_chars:
        raise VoiceSaveError(
            f"받아쓰기가 녹음 길이({duration_sec:.1f}초)에 비해 너무 짧습니다 "
            f"({char_count}자). 녹음한 말을 빠짐없이 적어 주세요.",
            "text_too_short_for_audio",
        )


def backup_current_reference(user_id: int) -> Path | None:
    ref_wav = user_ref_wav(user_id)
    ref_txt = user_ref_txt(user_id)
    if not ref_wav.is_file() and not ref_txt.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = user_voice_history_dir(user_id) / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    if ref_wav.is_file():
        shutil.copy2(ref_wav, backup_dir / "reference.wav")
    if ref_txt.is_file():
        shutil.copy2(ref_txt, backup_dir / "reference.txt")
    meta = {"backedUpAt": stamp, "source": "reference"}
    (backup_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
    return backup_dir


def commit_reference_wav(user_id: int, wav_path: Path, transcript: str, duration_sec: float) -> dict:
    validate_text_fits_duration(transcript, duration_sec)
    backup_dir = backup_current_reference(user_id)
    voice_dir = user_voice_dir(user_id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wav_path, user_ref_wav(user_id))
    user_ref_txt(user_id).write_text(transcript.strip() + "\n", encoding="utf-8")
    return {
        "ok": True,
        "durationSec": round(duration_sec, 2),
        "backupDir": str(backup_dir) if backup_dir else None,
    }


def prepare_voice_upload(user_id: int, upload_path: Path, upload_size: int) -> dict:
    if upload_size > MAX_UPLOAD_BYTES:
        raise VoiceSaveError(
            f"파일이 너무 커요 (최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).",
            "too_large",
        )
    pending_parent = user_voice_pending_dir(user_id)
    pending_parent.mkdir(parents=True, exist_ok=True)
    staging_wav = pending_parent / "_prepare_staging.wav"
    convert_to_reference_wav(upload_path, staging_wav)
    try:
        duration = probe_duration_sec(staging_wav)
        validate_duration_sec(duration)

        from voice_asr import VoiceAsrError, transcribe_reference_wav
        from voice_pending import create_pending

        try:
            asr_text = transcribe_reference_wav(staging_wav)
        except VoiceAsrError as exc:
            raise VoiceSaveError(str(exc), "asr_failed")

        expected = expected_script_for_match(user_id)
        script_cer = character_error_rate(expected, asr_text) if expected else 0.0
        pending = create_pending(user_id, staging_wav, duration, asr_text, expected, script_cer)
    finally:
        staging_wav.unlink(missing_ok=True)

    match_pct = round(max(0.0, 1.0 - script_cer) * 100)
    return {
        "pendingToken": pending.token,
        "transcript": asr_text,
        "durationSec": round(duration, 2),
        "scriptCer": round(script_cer, 4),
        "scriptMatchPercent": match_pct,
        "expectedScriptPreview": expected[:120] + ("…" if len(expected) > 120 else ""),
        "limits": {
            "minCharsPerSec": MIN_CHARS_PER_SEC,
            "maxCharsPerSec": MAX_CHARS_PER_SEC,
            "maxCharsForDuration": int(MAX_CHARS_PER_SEC * duration),
        },
    }


def confirm_voice_upload(user_id: int, token: str, transcript: str) -> dict:
    from voice_pending import delete_pending, load_pending

    pending = load_pending(user_id, token)
    transcript = transcript.strip()
    edit_cer = character_error_rate(pending.asr_transcript, transcript) if pending.asr_transcript else 0.0
    validate_text_fits_duration(transcript, pending.duration_sec)

    pending_parent = user_voice_pending_dir(user_id)
    with tempfile.TemporaryDirectory(prefix="voice_commit_", dir=pending_parent) as tmp:
        staged = Path(tmp) / "reference.wav"
        shutil.copy2(pending.wav_path, staged)
        result = commit_reference_wav(user_id, staged, transcript, pending.duration_sec)

    delete_pending(user_id, token)
    if edit_cer > WARN_EDIT_CER_THRESHOLD:
        result["editWarning"] = (
            "받아쓰기가 자동 인식 결과와 많이 달라요. 녹음과 글이 같다면 저장해도 괜찮아요."
        )
        result["editCer"] = round(edit_cer, 4)
    return result


def save_reference(user_id: int, upload_path: Path, transcript: str, upload_size: int) -> dict:
    """Legacy one-step save (tests / CLI). Prefer prepare + confirm in the web UI."""
    transcript = transcript.strip()
    if upload_size > MAX_UPLOAD_BYTES:
        raise VoiceSaveError(
            f"파일이 너무 커요 (최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).",
            "too_large",
        )

    pending_parent = user_voice_pending_dir(user_id)
    pending_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voice_upload_", dir=pending_parent) as tmp:
        tmp_wav = Path(tmp) / "converted.wav"
        convert_to_reference_wav(upload_path, tmp_wav)
        duration = probe_duration_sec(tmp_wav)
        validate_duration_sec(duration)
        validate_text_fits_duration(transcript, duration)

        backup_dir = backup_current_reference(user_id)
        voice_dir = user_voice_dir(user_id)
        voice_dir.mkdir(parents=True, exist_ok=True)
        tmp_ref = Path(tmp) / "reference.wav"
        shutil.move(str(tmp_wav), str(tmp_ref))
        os.replace(tmp_ref, user_ref_wav(user_id))
        user_ref_txt(user_id).write_text(transcript + "\n", encoding="utf-8")

    return {
        "ok": True,
        "durationSec": round(duration, 2),
        "backupDir": str(backup_dir) if backup_dir else None,
    }


def has_reference(user_id: int) -> bool:
    return has_user_reference(user_id)
