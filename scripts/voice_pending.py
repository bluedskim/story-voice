"""Pending voice uploads (prepare → confirm) with expiry."""

from __future__ import annotations

import json
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from user_storage import user_voice_pending_dir
from voice_service import VoiceSaveError

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
    user_id: int


def _pending_root(user_id: int, token: str) -> Path:
    return user_voice_pending_dir(user_id) / token


def cleanup_expired(user_id: int | None = None, now: float | None = None) -> None:
    now = now or time.time()

    def _clean_dir(pending_dir: Path) -> None:
        if not pending_dir.is_dir():
            return
        for child in pending_dir.iterdir():
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

    if user_id is not None:
        _clean_dir(user_voice_pending_dir(user_id))
        return
    from user_storage import users_dir

    base = users_dir()
    if not base.is_dir():
        return
    for user_dir in base.iterdir():
        if user_dir.is_dir():
            _clean_dir(user_dir / "voice" / "pending")


def create_pending(
    user_id: int,
    wav_path: Path,
    duration_sec: float,
    asr_transcript: str,
    expected_script: str,
    script_cer: float,
) -> PendingVoice:
    cleanup_expired(user_id)
    pending_dir = user_voice_pending_dir(user_id)
    pending_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    root = _pending_root(user_id, token)
    root.mkdir(parents=True, exist_ok=False)
    dest_wav = root / "reference.wav"
    shutil.copy2(wav_path, dest_wav)
    meta = {
        "createdAt": time.time(),
        "durationSec": duration_sec,
        "asrTranscript": asr_transcript,
        "expectedScript": expected_script,
        "scriptCer": script_cer,
        "userId": user_id,
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
        user_id=user_id,
    )


def load_pending(user_id: int, token: str) -> PendingVoice:
    cleanup_expired(user_id)
    if not token or "/" in token or ".." in token:
        raise VoiceSaveError("잘못된 확인 코드예요. 다시 녹음부터 해 주세요.", "invalid_token")
    root = _pending_root(user_id, token)
    meta_path = root / "meta.json"
    wav_path = root / "reference.wav"
    if not meta_path.is_file() or not wav_path.is_file():
        raise VoiceSaveError("확인 시간이 지났거나 없는 요청이에요. 다시 녹음해 주세요.", "expired_token")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        created = float(data["createdAt"])
        stored_uid = int(data.get("userId", user_id))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise VoiceSaveError("확인 시간이 지났어요. 다시 녹음해 주세요.", "expired_token")
    if stored_uid != user_id:
        raise VoiceSaveError("잘못된 확인 코드예요. 다시 녹음부터 해 주세요.", "invalid_token")
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
        user_id=user_id,
    )


def delete_pending(user_id: int, token: str) -> None:
    shutil.rmtree(_pending_root(user_id, token), ignore_errors=True)
