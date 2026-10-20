#!/usr/bin/env python3
"""Clone a voice with Qwen3-TTS (MLX) and narrate a whole story."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

ChunkProgress = Callable[[int, int], None]

DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
DEFAULT_REF_WAV = ROOT / "data" / "voice" / "reference.wav"
DEFAULT_REF_TEXT = ROOT / "data" / "voice" / "reference.txt"
DEFAULT_AUDIO_DIR = ROOT / "data" / "audio"

# Re-export for scripts/tests
from audio_quality_config import (  # noqa: E402
    DEFAULT_CER_THRESHOLD,
    DEFAULT_MAX_ASR_RETRIES,
    DEFAULT_PARAGRAPH_PAUSE,
    DEFAULT_SENTENCE_PAUSE,
    asr_verify_enabled,
)
from narration_pipeline import NarrationConfig, TtsSession, narrate_story  # noqa: E402
from story_chunking import split_sentences, split_story_into_chunks  # noqa: E402

DEFAULT_MAX_CHARS = 120  # legacy CLI flag maps to comma-split threshold


def load_ref_text(ref_text: str | Path) -> str:
    ref = os.fspath(ref_text)
    if os.path.isfile(ref):
        return Path(ref).read_text(encoding="utf-8").strip()
    return str(ref_text).strip()


def read_story_text(story_path: Path, catalog_mode: bool) -> str:
    raw = story_path.read_text(encoding="utf-8")
    if not catalog_mode:
        return raw
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_catalog import load_story

    return load_story(story_path).body


def ffmpeg_concat_to_out(list_path: str, sr: int, out_path: Path) -> None:
    """Legacy helper for tests importing clone_story."""
    from audio_post import ffmpeg_concat_wav, ffmpeg_loudnorm_m4a, run_ffmpeg
    from pathlib import Path as P

    wav = P(list_path).parent / "_legacy_concat.wav"
    run_ffmpeg(ffmpeg_concat_wav(P(list_path), wav, sr))
    if out_path.suffix.lower() in {".m4a", ".mp4"}:
        run_ffmpeg(ffmpeg_loudnorm_m4a(wav, out_path))
    else:
        import shutil

        shutil.copy2(wav, out_path)


class StoryGenerator:
    """Keep the TTS model loaded across multiple stories (released during ASR)."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        ref_audio: Path = DEFAULT_REF_WAV,
        ref_text: str | None = None,
        ref_text_path: Path | None = None,
        sentence_pause: float = DEFAULT_SENTENCE_PAUSE,
        paragraph_pause: float = DEFAULT_PARAGRAPH_PAUSE,
        temperature: float | None = None,
        verify_asr: bool | None = None,
        cer_threshold: float | None = None,
        max_asr_retries: int | None = None,
        keep_chunks: bool = False,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        from mlx_audio.tts.utils import load_model

        del keep_chunks  # handled inside pipeline tempdir
        self.model_id = model_id
        self.ref_audio = ref_audio
        if ref_text is None:
            ref_text_path = ref_text_path or DEFAULT_REF_TEXT
            ref_text = load_ref_text(ref_text_path)
        self.ref_text = ref_text
        self._model = None
        self._config = NarrationConfig(
            sentence_pause=sentence_pause,
            paragraph_pause=paragraph_pause,
            temperature=temperature,
            verify_asr=verify_asr if verify_asr is not None else asr_verify_enabled(),
            cer_threshold=cer_threshold if cer_threshold is not None else DEFAULT_CER_THRESHOLD,
            max_asr_retries=max_asr_retries if max_asr_retries is not None else DEFAULT_MAX_ASR_RETRIES,
        )
        if max_chars != DEFAULT_MAX_CHARS:
            from audio_quality_config import LONG_SENTENCE_COMMA_SPLIT_CHARS

            import audio_quality_config as aqc

            aqc.LONG_SENTENCE_COMMA_SPLIT_CHARS = max_chars
        t0 = time.time()
        print(f"Loading model {model_id}…", file=sys.stderr)
        self._model = load_model(model_id)
        print(f"model loaded in {time.time() - t0:.1f}s", file=sys.stderr)

    def _load_model(self):
        if self._model is None:
            from mlx_audio.tts.utils import load_model

            self._model = load_model(self.model_id)
        return self._model

    def _unload_model(self) -> None:
        self._model = None
        from asr_verify import release_mlx_memory

        release_mlx_memory()

    def generate_story(
        self,
        story_text: str,
        output_path: Path,
        on_progress: ChunkProgress | None = None,
    ) -> None:
        session = TtsSession(self._load_model, self._unload_model)
        narrate_story(
            story_text,
            output_path,
            self.ref_audio,
            self.ref_text,
            session,
            config=self._config,
            on_progress=on_progress,
        )
        try:
            import mlx.core as mx

            print(f"peak mem {mx.get_peak_memory() / 1e9:.2f} GB", file=sys.stderr)
        except Exception:
            pass


def generate_from_story_file(
    story_path: Path,
    output_path: Path | None = None,
    generator: StoryGenerator | None = None,
    **generator_kwargs,
) -> Path:
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_catalog import load_story

    story = load_story(story_path)
    out = output_path or (DEFAULT_AUDIO_DIR / f"{story.id}.m4a")
    owns = generator is None
    if owns:
        generator = StoryGenerator(**generator_kwargs)
    generator.generate_story(story.body, out)
    return out


def main() -> None:
    from audio_quality_config import DEFAULT_CER_THRESHOLD

    ap = argparse.ArgumentParser(description="Clone voice and narrate a story with Qwen3-TTS (MLX).")
    ap.add_argument("catalog_story", nargs="?", type=Path)
    ap.add_argument("--ref-audio", type=Path, default=None)
    ap.add_argument("--ref-text", default=None)
    ap.add_argument("--story", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--lang", default="Korean")
    ap.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="Long-sentence comma split threshold (legacy name)",
    )
    ap.add_argument("--pause", type=float, default=None)
    ap.add_argument("--sentence-pause", type=float, default=None)
    ap.add_argument("--paragraph-pause", type=float, default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--no-asr-verify", action="store_true")
    ap.add_argument("--cer-threshold", type=float, default=DEFAULT_CER_THRESHOLD)
    ap.add_argument("--max-asr-retries", type=int, default=DEFAULT_MAX_ASR_RETRIES)
    a = ap.parse_args()

    sentence_pause = a.sentence_pause if a.sentence_pause is not None else DEFAULT_SENTENCE_PAUSE
    paragraph_pause = a.paragraph_pause if a.paragraph_pause is not None else DEFAULT_PARAGRAPH_PAUSE
    if a.pause is not None:
        sentence_pause = paragraph_pause = a.pause

    legacy = a.story is not None and a.ref_audio is not None
    catalog = a.catalog_story is not None and not legacy

    if legacy:
        story_path = a.story
        story_text = read_story_text(story_path, catalog_mode=False)
        ref_audio = a.ref_audio
        ref_text = load_ref_text(a.ref_text)
        out = a.out or a.output
    elif catalog:
        story_path = a.catalog_story
        story_text = read_story_text(story_path, catalog_mode=True)
        ref_audio = a.ref_audio or DEFAULT_REF_WAV
        ref_text = load_ref_text(a.ref_text or DEFAULT_REF_TEXT)
        from story_catalog import load_story

        out = a.out or a.output or (DEFAULT_AUDIO_DIR / f"{load_story(story_path).id}.m4a")
    else:
        sys.exit("Provide catalog story path or --ref-audio + --ref-text + --story + --out")

    gen = StoryGenerator(
        model_id=a.model,
        ref_audio=ref_audio,
        ref_text=ref_text,
        max_chars=a.max_chars,
        sentence_pause=sentence_pause,
        paragraph_pause=paragraph_pause,
        temperature=a.temperature,
        verify_asr=not a.no_asr_verify,
        cer_threshold=a.cer_threshold,
        max_asr_retries=a.max_asr_retries,
    )
    gen.generate_story(story_text, out)


if __name__ == "__main__":
    main()
