"""Pluggable story audio generators (MLX on Mac, fake for CI/Linux)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "data" / "audio"
FIXTURE_M4A = AUDIO_DIR / ".fixture.m4a"

ProgressCallback = Callable[[int, int, str], None]


class GenerationBackend(ABC):
    @abstractmethod
    def generate_story(
        self,
        story_id: str,
        story_text: str,
        output_path: Path,
        on_progress: ProgressCallback,
        *,
        verify_asr: bool = False,
    ) -> None:
        pass


class FakeGenerationBackend(GenerationBackend):
    """Fast stub: simulates chunk progress and writes a tiny valid m4a."""

    def __init__(self, chunk_delay: float | None = None) -> None:
        if chunk_delay is None:
            chunk_delay = float(os.environ.get("STORY_VOICE_FAKE_CHUNK_DELAY", "0.02"))
        self.chunk_delay = chunk_delay
        self.last_verify_asr: bool | None = None
        self._ensure_fixture()

    def _ensure_fixture(self) -> None:
        if FIXTURE_M4A.is_file():
            return
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                str(FIXTURE_M4A),
            ],
            check=True,
        )

    def generate_story(
        self,
        story_id: str,
        story_text: str,
        output_path: Path,
        on_progress: ProgressCallback,
        *,
        verify_asr: bool = False,
    ) -> None:
        self.last_verify_asr = verify_asr
        from audio_quality_config import DEFAULT_MAX_CHARS
        from story_segmentation import split_story_into_chunks

        chunks = split_story_into_chunks(story_text, DEFAULT_MAX_CHARS)
        total = max(len(chunks), 1)
        for i in range(total):
            on_progress(i + 1, total, story_id)
            time.sleep(self.chunk_delay)
        shutil.copy2(FIXTURE_M4A, output_path)


class MLXGenerationBackend(GenerationBackend):
    """Validated mlx-audio path; model loaded once per worker lifetime."""

    def __init__(self) -> None:
        self._generator = None

    def _get_generator(self):
        if self._generator is None:
            from clone_story import DEFAULT_REF_TEXT, DEFAULT_REF_WAV, StoryGenerator, load_ref_text

            self._generator = StoryGenerator(ref_audio=DEFAULT_REF_WAV, ref_text_path=DEFAULT_REF_TEXT)
        from clone_story import DEFAULT_REF_TEXT, DEFAULT_REF_WAV, load_ref_text

        self._generator.ref_audio = DEFAULT_REF_WAV
        self._generator.ref_text = load_ref_text(DEFAULT_REF_TEXT)
        return self._generator

    def generate_story(
        self,
        story_id: str,
        story_text: str,
        output_path: Path,
        on_progress: ProgressCallback,
        *,
        verify_asr: bool = False,
    ) -> None:
        from clone_story import split_sentences, DEFAULT_MAX_CHARS

        total = len(split_sentences(story_text, DEFAULT_MAX_CHARS)) or 1

        def on_chunk(current: int, _total: int) -> None:
            on_progress(current, total, story_id)

        generator = self._get_generator()
        generator.narration_config.verify_asr = verify_asr
        generator.generate_story(story_text, output_path, on_progress=on_chunk)


def get_backend() -> GenerationBackend:
    kind = os.environ.get("STORY_VOICE_GENERATOR", "mlx").lower()
    if kind in {"fake", "stub", "test"}:
        return FakeGenerationBackend()
    return MLXGenerationBackend()
