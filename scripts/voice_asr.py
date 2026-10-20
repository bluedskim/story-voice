"""Voice-upload ASR (subprocess on Mac; fake for CI)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"


class VoiceAsrError(Exception):
    pass


def _asr_backend() -> str:
    return os.environ.get("STORY_VOICE_VOICE_ASR", os.environ.get("STORY_VOICE_ASR", "mlx")).lower()


def transcribe_reference_wav(wav_path: Path, timeout_sec: float = 120.0) -> str:
    """Transcribe 24 kHz mono reference audio. Never loads MLX in the caller process."""
    backend = _asr_backend()
    if backend in {"fake", "stub", "test"}:
        return _fake_transcribe(wav_path)
    return _transcribe_subprocess(wav_path, timeout_sec)


def _fake_transcribe(wav_path: Path) -> str:
    """Deterministic stub: env override, sidecar, or record script prefix."""
    override = os.environ.get("STORY_VOICE_FAKE_ASR_TEXT")
    if override is not None:
        return override.strip()
    sidecar = Path(f"{wav_path}.asr.txt")
    if sidecar.is_file():
        return sidecar.read_text(encoding="utf-8").strip()
    from voice_service import default_record_script

    script = default_record_script()
    if script:
        return script[:80]
    return "테스트 받아쓰기 문장입니다."


def _transcribe_subprocess(wav_path: Path, timeout_sec: float) -> str:
    worker = ROOT / "scripts" / "voice_asr_worker.py"
    env = os.environ.copy()
    env.setdefault("STORY_VOICE_ASR_MODEL", DEFAULT_ASR_MODEL)
    try:
        proc = subprocess.run(
            [sys.executable, str(worker), str(wav_path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        raise VoiceAsrError("받아쓰기에 시간이 너무 오래 걸렸어요. 다시 시도해 주세요.")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise VoiceAsrError(err or "받아쓰기에 실패했어요.")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise VoiceAsrError("받아쓰기 결과를 읽지 못했어요.")
    text = (payload.get("text") or "").strip()
    if not text:
        raise VoiceAsrError("받아쓰기가 비어 있어요. 더 또렷하게 녹음해 주세요.")
    return text


def extract_transcript(result) -> str:
    """Decode mlx-audio STT output (shared with narration ASR)."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, list):
        if not result:
            return ""
        return extract_transcript(result[0])
    text = getattr(result, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    segments = getattr(result, "segments", None)
    if segments:
        parts: list[str] = []
        for seg in segments:
            if isinstance(seg, dict):
                piece = seg.get("text", "")
            else:
                piece = getattr(seg, "text", "")
            if piece:
                parts.append(str(piece).strip())
        if parts:
            return " ".join(parts)
    return ""
