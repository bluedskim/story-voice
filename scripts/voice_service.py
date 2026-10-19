"""Save parent voice reference (ffmpeg convert, backup, validation)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_DIR = ROOT / "data" / "voice"
HISTORY_DIR = VOICE_DIR / "history"
REF_WAV = VOICE_DIR / "reference.wav"
REF_TXT = VOICE_DIR / "reference.txt"
RECORD_SCRIPT = ROOT / "content" / "record_script.txt"

MIN_DURATION_SEC = 5.0
MAX_DURATION_SEC = 40.0
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB raw upload


class VoiceSaveError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def default_record_script() -> str:
    if RECORD_SCRIPT.is_file():
        return RECORD_SCRIPT.read_text(encoding="utf-8").strip()
    return ""


def probe_duration_sec(path: Path) -> float:
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


def convert_to_reference_wav(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
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
    )


def backup_current_reference() -> Path | None:
    if not REF_WAV.is_file() and not REF_TXT.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = HISTORY_DIR / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    if REF_WAV.is_file():
        shutil.copy2(REF_WAV, backup_dir / "reference.wav")
    if REF_TXT.is_file():
        shutil.copy2(REF_TXT, backup_dir / "reference.txt")
    meta = {"backedUpAt": stamp, "source": "reference"}
    (backup_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
    return backup_dir


def save_reference(upload_path: Path, transcript: str, upload_size: int) -> dict:
    transcript = transcript.strip()
    if not transcript:
        raise VoiceSaveError("받아쓰기를 입력해 주세요.", "empty_transcript")
    if upload_size > MAX_UPLOAD_BYTES:
        raise VoiceSaveError(
            f"파일이 너무 커요 (최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).",
            "too_large",
        )

    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voice_upload_", dir=VOICE_DIR) as tmp:
        tmp_wav = Path(tmp) / "converted.wav"
        convert_to_reference_wav(upload_path, tmp_wav)
        duration = probe_duration_sec(tmp_wav)
        if duration < MIN_DURATION_SEC:
            raise VoiceSaveError(
                f"녹음이 너무 짧아요 ({duration:.1f}s). {MIN_DURATION_SEC:.0f}초 이상이 필요해요.",
                "too_short",
            )
        if duration > MAX_DURATION_SEC:
            raise VoiceSaveError(
                f"녹음이 너무 길어요 ({duration:.1f}s). {MAX_DURATION_SEC:.0f}초 이하로 해 주세요.",
                "too_long",
            )

        backup_dir = backup_current_reference()
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_ref = Path(tmp) / "reference.wav"
        shutil.move(str(tmp_wav), str(tmp_ref))
        os.replace(tmp_ref, REF_WAV)
        REF_TXT.write_text(transcript + "\n", encoding="utf-8")

    return {
        "ok": True,
        "durationSec": round(duration, 2),
        "backupDir": str(backup_dir) if backup_dir else None,
    }


def has_reference() -> bool:
    return REF_WAV.is_file() and REF_TXT.is_file()
