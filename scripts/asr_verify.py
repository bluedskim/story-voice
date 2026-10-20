"""ASR verification with mlx-audio Qwen3-ASR (lazy load, unload for memory)."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from audio_quality_config import DEFAULT_ASR_MODEL, MASS_RETRY_FAIL_FRACTION
from cer import character_error_rate, normalize_korean_for_cer

log = logging.getLogger("story_voice.asr")


class AsrTranscriber(Protocol):
    def transcribe(self, wav_path: Path) -> str: ...


@dataclass
class ChunkVerifyResult:
    index: int
    cer: float
    attempts: int
    hypothesis: str


@dataclass
class VerifyStats:
    asr_seconds: float = 0.0
    retry_generations: int = 0
    chunk_results: list[ChunkVerifyResult] = field(default_factory=list)
    mass_retry_skipped: bool = False


def asr_debug_enabled() -> bool:
    raw = os.environ.get("STORY_VOICE_ASR_DEBUG", "").strip().lower()
    return raw in {"1", "true", "yes", "on", "debug"}


def release_mlx_memory() -> None:
    try:
        import mlx.core as mx

        mx.clear_cache()
    except Exception:
        pass


def extract_transcript(result: Any) -> str:
    """Decode mlx-audio STT output; never use ``str(result)`` (repr blows up CER)."""
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


class MlxQwenAsr:
    def __init__(self, model_id: str = DEFAULT_ASR_MODEL) -> None:
        self.model_id = model_id
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        from mlx_audio.stt import load

        print(f"Loading ASR {self.model_id}…", file=sys.stderr)
        t0 = time.time()
        self._model = load(self.model_id)
        print(f"ASR loaded in {time.time() - t0:.1f}s", file=sys.stderr)

    def unload(self) -> None:
        self._model = None
        release_mlx_memory()

    def transcribe(self, wav_path: Path) -> str:
        self.load()
        result = self._model.generate(str(wav_path), language="Korean")
        return extract_transcript(result)


class FakeAsrTranscriber:
    """Test double: perfect transcription."""

    def transcribe(self, wav_path: Path) -> str:
        return ""


def score_chunk(asr: AsrTranscriber, wav_path: Path, reference: str) -> tuple[float, str]:
    hyp = asr.transcribe(wav_path)
    cer = character_error_rate(reference, hyp)
    if asr_debug_enabled() or log.isEnabledFor(logging.DEBUG):
        ref_n = normalize_korean_for_cer(reference)
        hyp_n = normalize_korean_for_cer(hyp)
        log.debug("CER wav=%s cer=%.4f ref_norm=%r hyp_norm=%r", wav_path.name, cer, ref_n, hyp_n)
        if asr_debug_enabled():
            print(
                f"    ASR debug ref_norm={ref_n!r} hyp_norm={hyp_n!r} raw_hyp={hyp!r}",
                file=sys.stderr,
            )
    return cer, hyp


def should_retry(
    cer: float,
    threshold: float,
    attempts_so_far: int,
    max_total_attempts: int,
) -> bool:
    """``max_total_attempts`` includes the first generation (e.g. 1 + extra retries)."""
    return cer > threshold and attempts_so_far < max_total_attempts


def should_skip_mass_retry(
    fail_count: int,
    total_chunks: int,
    fraction: float = MASS_RETRY_FAIL_FRACTION,
) -> bool:
    if total_chunks <= 0:
        return False
    return fail_count > total_chunks * fraction
