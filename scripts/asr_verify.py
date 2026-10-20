"""ASR verification with mlx-audio Qwen3-ASR (lazy load, unload for memory)."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from audio_quality_config import DEFAULT_ASR_MODEL
from cer import character_error_rate


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


def release_mlx_memory() -> None:
    try:
        import mlx.core as mx

        mx.clear_cache()
    except Exception:
        pass


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
        if isinstance(result, list):
            result = result[0]
        return (getattr(result, "text", None) or str(result)).strip()


class FakeAsrTranscriber:
    """Test double: perfect transcription."""

    def transcribe(self, wav_path: Path) -> str:
        return ""


def score_chunk(asr: AsrTranscriber, wav_path: Path, reference: str) -> tuple[float, str]:
    hyp = asr.transcribe(wav_path)
    return character_error_rate(reference, hyp), hyp


def should_retry(
    cer: float,
    threshold: float,
    attempts_so_far: int,
    max_total_attempts: int,
) -> bool:
    """``max_total_attempts`` includes the first generation (e.g. 1 + extra retries)."""
    return cer > threshold and attempts_so_far < max_total_attempts
