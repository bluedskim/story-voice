"""Pending voice uploads (prepare → confirm) with expiry."""

from __future__ import annotations

import json
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from voice_service import VOICE_DIR, VoiceSaveError

PENDING_DIR = VOICE_DIR / "pending"
PENDING_TTL_SEC = 30 * 60  # 30 minutes


@dataclass
class PendingVoice:
    token: str
    wav_path: Path
    meta_path: Path
    created_at: float
    duration_sec: float
    asr_transcript: str
    expected_script: str
    script_cer: float


def _pending_root(token: str) -> Path:
    return PENDING_DIR / token


def cleanup_expired(now: float | None = None) -> None:
    if not PENDING_DIR.is_dir():
        return
    now = now or time.time()
    for child in PENDING_DIR.iterdir():
        if not child.is_dir():
            continue
        meta = child / "meta.json"
        if not meta.is_file():
            shutil.rmtree(child, ignore_errors=True)
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            created = float(data.get("createdAt", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            created = 0
        if now - created > PENDING_TTL_SEC:
            shutil.rmtree(child, ignore_errors=True)


def create_pending(
    wav_path: Path,
    duration_sec: float,
    asr_transcript: str,
    expected_script: str,
    script_cer: float,
) -> PendingVoice:
    cleanup_expired()
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    root = _pending_root(token)
    root.mkdir(parents=True, exist_ok=False)
    dest_wav = root / "reference.wav"
    shutil.copy2(wav_path, dest_wav)
    meta = {
        "createdAt": time.time(),
        "durationSec": duration_sec,
        "asrTranscript": asr_transcript,
        "expectedScript": expected_script,
        "scriptCer": script_cer,
    }
    meta_path = root / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
    return PendingVoice(
        token=token,
        wav_path=dest_wav,
        meta_path=meta_path,
        created_at=meta["createdAt"],
        duration_sec=duration_sec,
        asr_transcript=asr_transcript,
        expected_script=expected_script,
        script_cer=script_cer,
    )


def load_pending(token: str) -> PendingVoice:
    cleanup_expired()
    if not token or "/" in token or ".." in token:
        raise VoiceSaveError("잘못된 확인 코드예요. 다시 녹음부터 해 주세요.", "invalid_token")
    root = _pending_root(token)
    meta_path = root / "meta.json"
    wav_path = root / "reference.wav"
    if not meta_path.is_file() or not wav_path.is_file():
        raise VoiceSaveError("확인 시간이 지났거나 없는 요청이에요. 다시 녹음해 주세요.", "expired_token")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        created = float(data["createdAt"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise VoiceSaveError("확인 시간이 지났어요. 다시 녹음해 주세요.", "expired_token")
    if time.time() - created > PENDING_TTL_SEC:
        shutil.rmtree(root, ignore_errors=True)
        raise VoiceSaveError("확인 시간이 지났어요. 다시 녹음해 주세요.", "expired_token")
    return PendingVoice(
        token=token,
        wav_path=wav_path,
        meta_path=meta_path,
        created_at=created,
        duration_sec=float(data.get("durationSec", 0)),
        asr_transcript=str(data.get("asrTranscript", "")),
        expected_script=str(data.get("expectedScript", "")),
        script_cer=float(data.get("scriptCer", 0)),
    )


def delete_pending(token: str) -> None:
    shutil.rmtree(_pending_root(token), ignore_errors=True)
