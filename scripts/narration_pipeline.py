"""End-to-end narration: TTS chunks, optional ASR verify, post-process."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from audio_post import ffmpeg_concat_wav, ffmpeg_loudnorm_m4a, ffmpeg_trim_chunk, run_ffmpeg
from audio_quality_config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_CER_THRESHOLD,
    DEFAULT_MAX_ASR_RETRIES,
    DEFAULT_PARAGRAPH_PAUSE,
    DEFAULT_SENTENCE_PAUSE,
    asr_verify_enabled,
)
from asr_verify import (
    ChunkVerifyResult,
    MlxQwenAsr,
    VerifyStats,
    release_mlx_memory,
    score_chunk,
    should_retry,
)
from story_chunking import StoryChunk, split_story_into_chunks

ChunkProgress = Callable[[int, int], None]


@dataclass
class NarrationConfig:
    sentence_pause: float = DEFAULT_SENTENCE_PAUSE
    paragraph_pause: float = DEFAULT_PARAGRAPH_PAUSE
    verify_asr: bool = True
    cer_threshold: float = DEFAULT_CER_THRESHOLD
    max_asr_retries: int = DEFAULT_MAX_ASR_RETRIES
    asr_model: str = DEFAULT_ASR_MODEL
    temperature: float | None = None


@dataclass
class StoryTiming:
    tts_seconds: float = 0.0
    asr_seconds: float = 0.0
    retry_count: int = 0
    verify_stats: VerifyStats = field(default_factory=VerifyStats)


def _generate_tts_audio(
    model,
    text: str,
    ref_audio: str | Path,
    ref_text: str,
    lang: str,
    temperature: float | None,
) -> tuple[object, int]:
    import numpy as np

    ref_audio_str = os.fspath(ref_audio)
    kw: dict = dict(text=text, ref_audio=ref_audio_str, ref_text=ref_text, lang_code=lang)
    if temperature is not None:
        kw["temperature"] = temperature
    try:
        results = list(model.generate(**kw))
    except TypeError:
        kw.pop("lang_code", None)
        results = list(model.generate(**kw))
    audio = np.concatenate([np.array(r.audio, dtype=np.float32).reshape(-1) for r in results])
    sr = int(getattr(results[0], "sample_rate", getattr(model, "sample_rate", 24000)))
    return audio, sr


def _write_chunk_wav(audio, sr: int, path: Path) -> None:
    from mlx_audio import audio_io as sf

    sf.write(str(path), audio, sr)


def _make_silence_wav(path: Path, duration: float, sr: int) -> None:
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sr}:cl=mono",
            "-t",
            str(duration),
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )


class TtsSession:
    """Loads/unloads TTS to free RAM for ASR on 16GB Mac mini."""

    def __init__(
        self,
        model_loader: Callable[[], object],
        model_unloader: Callable[[], None] | None = None,
    ) -> None:
        self._loader = model_loader
        self._unloader = model_unloader
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = self._loader()
        return self._model

    def release(self) -> None:
        if self._unloader:
            self._unloader()
        self._model = None
        release_mlx_memory()


def _synthesize_chunk(
    tts_session: TtsSession,
    chunk: StoryChunk,
    ref_audio: Path,
    ref_text: str,
    cfg: NarrationConfig,
    raw_path: Path,
    trimmed_path: Path,
) -> int:
    audio, sr = _generate_tts_audio(
        tts_session.model,
        chunk.text,
        ref_audio,
        ref_text,
        "Korean",
        cfg.temperature,
    )
    _write_chunk_wav(audio, sr, raw_path)
    run_ffmpeg(ffmpeg_trim_chunk(raw_path, trimmed_path))
    release_mlx_memory()
    return sr


def _run_asr_verification(
    chunks: list[StoryChunk],
    chunk_paths: list[Path],
    tts_session: TtsSession,
    ref_audio: Path,
    ref_text: str,
    cfg: NarrationConfig,
    tmpdir: Path,
) -> tuple[list[Path], VerifyStats, float, int]:
    """Unload TTS, load ASR, score chunks, retry failures with TTS/ASR alternation."""
    stats = VerifyStats()
    tts_session.release()
    asr = MlxQwenAsr(cfg.asr_model)

    best_paths = list(chunk_paths)
    best_cer = [1.0] * len(chunks)
    attempt_counts = [1] * len(chunks)

    t_asr = time.time()
    for i, chunk in enumerate(chunks):
        cer, hyp = score_chunk(asr, best_paths[i], chunk.text)
        best_cer[i] = cer
        stats.chunk_results.append(ChunkVerifyResult(index=i, cer=cer, attempts=1, hypothesis=hyp))
        print(f"  ASR chunk {i + 1}/{len(chunks)} CER={cer:.3f}", file=sys.stderr)

    retry_round = 0
    while retry_round < cfg.max_asr_retries:
        indices = [
            i
            for i, cer in enumerate(best_cer)
            if should_retry(cer, cfg.cer_threshold, attempt_counts[i], 1 + cfg.max_asr_retries)
        ]
        if not indices:
            break
        retry_round += 1
        print(f"ASR retry round {retry_round}: chunks {indices}", file=sys.stderr)

        asr.unload()
        tts_session.model  # load TTS
        for i in indices:
            chunk = chunks[i]
            raw = tmpdir / f"chunk_{i:04d}_retry{retry_round}_raw.wav"
            trimmed = tmpdir / f"chunk_{i:04d}_retry{retry_round}.wav"
            _synthesize_chunk(tts_session, chunk, ref_audio, ref_text, cfg, raw, trimmed)
            stats.retry_generations += 1

        tts_session.release()
        asr.load()
        for i in indices:
            cer, hyp = score_chunk(asr, tmpdir / f"chunk_{i:04d}_retry{retry_round}.wav", chunks[i].text)
            attempt_counts[i] += 1
            if cer <= best_cer[i]:
                best_cer[i] = cer
                best_paths[i] = tmpdir / f"chunk_{i:04d}_retry{retry_round}.wav"
            for row in stats.chunk_results:
                if row.index == i:
                    row.cer = best_cer[i]
                    row.attempts = attempt_counts[i]
                    row.hypothesis = hyp
            print(f"  ASR chunk {i + 1} after retry CER={cer:.3f} (best={best_cer[i]:.3f})", file=sys.stderr)

    asr.unload()
    stats.asr_seconds = time.time() - t_asr
    return best_paths, stats, stats.asr_seconds, stats.retry_generations


def _concat_and_encode(
    chunks: list[StoryChunk],
    chunk_wavs: list[Path],
    sr: int,
    cfg: NarrationConfig,
    tmpdir: Path,
    out_path: Path,
) -> None:
    list_path = tmpdir / "list.txt"
    with list_path.open("w", encoding="utf-8") as fh:
        for i, wav in enumerate(chunk_wavs):
            chunk = chunks[i]
            if chunk.pause_before_sec > 0:
                sil = tmpdir / f"before_{i:04d}.wav"
                _make_silence_wav(sil, chunk.pause_before_sec, sr)
                fh.write(f"file '{sil}'\n")
            fh.write(f"file '{wav}'\n")
            if i < len(chunk_wavs) - 1:
                pause = chunks[i].pause_after_sec(cfg.sentence_pause, cfg.paragraph_pause)
                sil = tmpdir / f"after_{i:04d}.wav"
                _make_silence_wav(sil, pause, sr)
                fh.write(f"file '{sil}'\n")

    raw_story = tmpdir / "story_concat.wav"
    run_ffmpeg(ffmpeg_concat_wav(list_path, raw_story, sr))
    suffix = out_path.suffix.lower()
    if suffix in {".m4a", ".mp4"}:
        run_ffmpeg(ffmpeg_loudnorm_m4a(raw_story, out_path))
    elif suffix == ".mp3":
        import subprocess

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(raw_story),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(out_path),
            ],
            check=True,
        )
    else:
        shutil.copy2(raw_story, out_path)


def narrate_story(
    story_text: str,
    out_path: Path,
    ref_audio: Path,
    ref_text: str,
    tts_session: TtsSession,
    config: NarrationConfig | None = None,
    on_progress: ChunkProgress | None = None,
) -> StoryTiming:
    cfg = config or NarrationConfig(verify_asr=asr_verify_enabled())
    chunks = split_story_into_chunks(story_text)
    if not chunks:
        raise ValueError("Story text is empty")
    print(f"{len(chunks)} chunks (sentence-based)", file=sys.stderr)

    timing = StoryTiming()
    out_parent = out_path.parent if out_path.parent.exists() else Path.cwd() / "out"
    tmpdir = Path(tempfile.mkdtemp(prefix="story_chunks_", dir=str(out_parent)))
    try:
        chunk_wavs: list[Path] = []
        sr = 24000
        t_tts = time.time()

        for i, chunk in enumerate(chunks):
            raw = tmpdir / f"chunk_{i:04d}_raw.wav"
            trimmed = tmpdir / f"chunk_{i:04d}.wav"
            t1 = time.time()
            sr = _synthesize_chunk(tts_session, chunk, ref_audio, ref_text, cfg, raw, trimmed)
            chunk_wavs.append(trimmed)
            print(
                f"[{i + 1}/{len(chunks)}] TTS {time.time() - t1:.1f}s :: {chunk.text[:40]}",
                file=sys.stderr,
            )
            if on_progress:
                on_progress(i + 1, len(chunks))

        timing.tts_seconds = time.time() - t_tts

        if cfg.verify_asr:
            chunk_wavs, vstats, asr_sec, retries = _run_asr_verification(
                chunks, chunk_wavs, tts_session, ref_audio, ref_text, cfg, tmpdir
            )
            timing.verify_stats = vstats
            timing.asr_seconds = asr_sec
            timing.retry_count = retries

        _concat_and_encode(chunks, chunk_wavs, sr, cfg, tmpdir, out_path)
        print(
            f"timing: TTS {timing.tts_seconds:.1f}s  ASR {timing.asr_seconds:.1f}s  "
            f"retries {timing.retry_count}  -> {out_path}",
            file=sys.stderr,
        )
        return timing
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
