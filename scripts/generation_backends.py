"""Pluggable story audio generators (MLX on Mac, fake for CI/Linux)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from member_generation import MemberGenerationPlan

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
        ref_wav: Path | None = None,
        ref_txt: Path | None = None,
    ) -> None:
        pass

    def generate_member_story(
        self,
        plan: "MemberGenerationPlan",
        story_text_stripped: str,
        output_path: Path,
        on_progress: ProgressCallback,
        *,
        verify_asr: bool = False,
    ) -> None:
        """Default: single reference from plan's primary slot."""
        wav, txt = next(iter(plan.slot_refs.values()))
        text = plan.markup_body if plan.multivoice else story_text_stripped
        self.generate_story(
            plan.story_id,
            text,
            output_path,
            on_progress,
            verify_asr=verify_asr,
            ref_wav=wav,
            ref_txt=txt,
        )


class FakeGenerationBackend(GenerationBackend):
    """Fast stub: simulates chunk progress and writes a tiny valid m4a."""

    def __init__(self, chunk_delay: float | None = None) -> None:
        if chunk_delay is None:
            chunk_delay = float(os.environ.get("STORY_VOICE_FAKE_CHUNK_DELAY", "0.02"))
        self.chunk_delay = chunk_delay
        self.last_verify_asr: bool | None = None
        self.last_ref_wav: Path | None = None
        self.last_multivoice: bool = False
        self.last_chunk_slot_ids: list[int] = []
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
        ref_wav: Path | None = None,
        ref_txt: Path | None = None,
    ) -> None:
        self.last_verify_asr = verify_asr
        self.last_ref_wav = ref_wav
        from audio_quality_config import DEFAULT_MAX_CHARS
        from story_segmentation import split_story_into_chunks

        chunks = split_story_into_chunks(story_text, DEFAULT_MAX_CHARS)
        total = max(len(chunks), 1)
        for i in range(total):
            on_progress(i + 1, total, story_id)
            time.sleep(self.chunk_delay)
        shutil.copy2(FIXTURE_M4A, output_path)

    def generate_member_story(
        self,
        plan,
        story_text_stripped: str,
        output_path: Path,
        on_progress: ProgressCallback,
        *,
        verify_asr: bool = False,
    ) -> None:
        from audio_quality_config import DEFAULT_MAX_CHARS
        from role_assignments import resolved_slot_for_role
        from story_segmentation import split_story_into_chunks

        self.last_verify_asr = verify_asr
        self.last_multivoice = plan.multivoice
        self.last_chunk_slot_ids = []
        text = plan.markup_body if plan.multivoice else story_text_stripped
        chunks = split_story_into_chunks(text, DEFAULT_MAX_CHARS)
        if plan.multivoice:
            for c in chunks:
                sid = resolved_slot_for_role(
                    0,
                    plan.story_id,
                    c.speaker_key,
                    plan.assignments,
                )
                self.last_chunk_slot_ids.append(sid)
            self.last_ref_wav = plan.slot_refs.get(self.last_chunk_slot_ids[0], (None, None))[0]
        else:
            wav, _ = next(iter(plan.slot_refs.values()))
            self.last_ref_wav = wav
            self.last_chunk_slot_ids = [next(iter(plan.slot_refs.keys()))] * len(chunks)

        total = max(len(chunks), 1)
        for i in range(total):
            on_progress(i + 1, total, plan.story_id)
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
        ref_wav: Path | None = None,
        ref_txt: Path | None = None,
    ) -> None:
        from clone_story import DEFAULT_REF_TEXT, DEFAULT_REF_WAV, load_ref_text, split_sentences, DEFAULT_MAX_CHARS

        wav = ref_wav or DEFAULT_REF_WAV
        txt_path = ref_txt or DEFAULT_REF_TEXT
        total = len(split_sentences(story_text, DEFAULT_MAX_CHARS)) or 1

        def on_chunk(current: int, _total: int) -> None:
            on_progress(current, total, story_id)

        generator = self._get_generator()
        generator.ref_audio = wav
        generator.ref_text = load_ref_text(txt_path)
        generator.narration_config.verify_asr = verify_asr
        generator.generate_story(story_text, output_path, on_progress=on_chunk)

    def generate_member_story(
        self,
        plan,
        story_text_stripped: str,
        output_path: Path,
        on_progress: ProgressCallback,
        *,
        verify_asr: bool = False,
    ) -> None:
        from role_assignments import resolved_slot_for_role
        from story_multivoice import load_voice_reference, narrate_story_multivoice
        from story_segmentation import split_story_into_chunks
        from clone_story import DEFAULT_MAX_CHARS

        if not plan.multivoice:
            wav, txt = next(iter(plan.slot_refs.values()))
            return self.generate_story(
                plan.story_id,
                story_text_stripped,
                output_path,
                on_progress,
                verify_asr=verify_asr,
                ref_wav=wav,
                ref_txt=txt,
            )

        ref_cache: dict[int, object] = {}

        def resolve_voice(chunk) -> object:
            sid = resolved_slot_for_role(
                0,
                plan.story_id,
                chunk.speaker_key,
                plan.assignments,
            )
            if sid not in ref_cache:
                wav, txt = plan.slot_refs[sid]
                ref = load_voice_reference(wav, txt)
                ref.audio_array()
                ref_cache[sid] = ref
            return ref_cache[sid]

        generator = self._get_generator()
        generator.narration_config.verify_asr = verify_asr
        session = None
        if verify_asr:
            session = generator._TtsSession(generator._load_model, generator._unload_model)

        total = len(split_story_into_chunks(plan.markup_body, DEFAULT_MAX_CHARS)) or 1

        def on_chunk(current: int, _total: int) -> None:
            on_progress(current, total, plan.story_id)

        active_model = generator.model
        narrate_story_multivoice(
            plan.markup_body,
            output_path,
            resolve_voice,
            active_model,
            max_chars=generator.max_chars,
            sentence_pause=generator.sentence_pause,
            paragraph_pause=generator.paragraph_pause,
            temperature=generator.temperature,
            dialogue_style=generator.dialogue_style,
            narration_config=generator.narration_config,
            tts_session=session,
        )
        on_progress(total, total, plan.story_id)


def get_backend() -> GenerationBackend:
    kind = os.environ.get("STORY_VOICE_GENERATOR", "mlx").lower()
    if kind in {"fake", "stub", "test"}:
        return FakeGenerationBackend()
    return MLXGenerationBackend()
