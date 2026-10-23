"""TTS session, reference caching, ASR verify retries, final loudnorm."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from asr_verify import (
    ChunkVerifyResult,
    MlxQwenAsr,
    VerifyStats,
    release_mlx_memory,
    score_chunk,
    should_retry,
    should_skip_mass_retry,
)
from audio_quality_config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_CER_THRESHOLD,
    DEFAULT_MAX_ASR_RETRIES,
    asr_verify_enabled,
)


@dataclass
class VoiceReference:
    """Load reference waveform once per story (avoids per-chunk reload)."""

    path: Path
    text: str
    _wave: object | None = field(default=None, repr=False)

    def audio_array(self) -> object:
        if self._wave is None:
            from mlx_audio.utils import load_audio

            self._wave = load_audio(str(self.path), sample_rate=24000)
        return self._wave


@dataclass
class NarrationConfig:
    verify_asr: bool = False
    cer_threshold: float = DEFAULT_CER_THRESHOLD
    max_asr_retries: int = DEFAULT_MAX_ASR_RETRIES
    asr_model: str = DEFAULT_ASR_MODEL


class TtsSession:
    """Load/unload TTS around ASR for 16GB-class machines."""

    def __init__(
        self,
        model_loader: Callable[[], object],
        model_unloader: Callable[[], None] | None = None,
    ) -> None:
        self._loader = model_loader
        self._unloader = model_unloader
        self._model: object | None = None

    @property
    def model(self) -> object:
        if self._model is None:
            t0 = time.time()
            self._model = self._loader()
            print(f"TTS model ready in {time.time() - t0:.1f}s", file=sys.stderr)
        return self._model

    def release(self) -> None:
        if self._unloader:
            self._unloader()
        self._model = None
        release_mlx_memory()


def default_narration_config(verify_asr: bool | None = None) -> NarrationConfig:
    return NarrationConfig(
        verify_asr=verify_asr if verify_asr is not None else asr_verify_enabled(),
    )


ChunkTuple = tuple[str, str, str]  # text, pause_kind, role
SynthesizeFn = Callable[[object, ChunkTuple, Path], int]


def run_asr_verification(
    chunks: list[ChunkTuple],
    chunk_paths: list[Path],
    tts_session: TtsSession,
    cfg: NarrationConfig,
    synthesize: SynthesizeFn,
) -> tuple[list[Path], VerifyStats]:
    stats = VerifyStats()
    tts_session.release()
    asr = MlxQwenAsr(cfg.asr_model)

    best_paths = list(chunk_paths)
    best_cer = [1.0] * len(chunks)
    attempt_counts = [1] * len(chunks)

    t_asr = time.time()
    for i, chunk in enumerate(chunks):
        text = chunk[0]
        cer, hyp = score_chunk(asr, best_paths[i], text)
        best_cer[i] = cer
        stats.chunk_results.append(ChunkVerifyResult(index=i, cer=cer, attempts=1, hypothesis=hyp))
        print(f"  ASR chunk {i + 1}/{len(chunks)} CER={cer:.3f}", file=sys.stderr)

    fail_count = sum(1 for cer in best_cer if cer > cfg.cer_threshold)
    if should_skip_mass_retry(fail_count, len(chunks)):
        stats.mass_retry_skipped = True
        print(
            f"WARN: {fail_count}/{len(chunks)} chunks above CER {cfg.cer_threshold} — "
            "skipping retries (likely systematic ASR/CER issue)",
            file=sys.stderr,
        )
        asr.unload()
        stats.asr_seconds = time.time() - t_asr
        return best_paths, stats

    max_attempts = 1 + cfg.max_asr_retries
    retry_round = 0
    while retry_round < cfg.max_asr_retries:
        indices = [
            i
            for i, cer in enumerate(best_cer)
            if should_retry(cer, cfg.cer_threshold, attempt_counts[i], max_attempts)
        ]
        if not indices:
            break
        retry_round += 1
        print(f"ASR retry round {retry_round}: chunks {indices}", file=sys.stderr)

        asr.unload()
        _ = tts_session.model
        for i in indices:
            out = best_paths[i].with_name(f"chunk_{i:04d}_retry{retry_round}.wav")
            synthesize(tts_session.model, chunks[i], out)
            stats.retry_generations += 1

        tts_session.release()
        asr.load()
        for i in indices:
            retry_path = best_paths[i].with_name(f"chunk_{i:04d}_retry{retry_round}.wav")
            cer, hyp = score_chunk(asr, retry_path, chunks[i][0])
            attempt_counts[i] += 1
            if cer <= best_cer[i]:
                best_cer[i] = cer
                best_paths[i] = retry_path
            for row in stats.chunk_results:
                if row.index == i:
                    row.cer = best_cer[i]
                    row.attempts = attempt_counts[i]
                    row.hypothesis = hyp
            print(
                f"  ASR chunk {i + 1} after retry CER={cer:.3f} (best={best_cer[i]:.3f})",
                file=sys.stderr,
            )

    asr.unload()
    stats.asr_seconds = time.time() - t_asr
    return best_paths, stats
