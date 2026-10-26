#!/usr/bin/env python3
"""Clone a voice with Qwen3-TTS (MLX) and narrate a whole story.

Validated on Mac mini (mlx-audio 0.6.0). Supports the original CLI::

  .venv/bin/python scripts/clone_story.py --ref-audio ref.wav --ref-text ref.txt \\
      --story story.txt --out out/story.wav

Catalog shortcut (YAML frontmatter in ``content/stories/``)::

  python scripts/clone_story.py content/stories/ui-joeun-hyeongje.txt
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

ChunkProgress = Callable[[int, int], None]

DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
DEFAULT_REF_WAV = ROOT / "data" / "voice" / "reference.wav"
DEFAULT_REF_TEXT = ROOT / "data" / "voice" / "reference.txt"
DEFAULT_AUDIO_DIR = ROOT / "data" / "audio"
DEFAULT_MAX_CHARS = 120
DEFAULT_PAUSE = 0.35
DEFAULT_SENTENCE_PAUSE = 0.35
DEFAULT_PARAGRAPH_PAUSE = 0.75


def split_sentences(text: str, max_chars: int) -> list[tuple[str, str]]:
    """Split story into TTS chunks (~max_chars) and label pauses after each chunk."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_segmentation import split_story_into_chunks

    return [(c.text, c.pause_after) for c in split_story_into_chunks(text, max_chars)]


def load_ref_text(ref_text: str | Path) -> str:
    ref = os.fspath(ref_text)
    if os.path.isfile(ref):
        return Path(ref).read_text(encoding="utf-8").strip()
    return str(ref_text).strip()


def read_story_text(story_path: Path, catalog_mode: bool = True) -> str:
    """Load story body for TTS; always strips YAML front matter when present."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_catalog import story_body_from_path

    return story_body_from_path(story_path)


def post_process_chunk_wav(
    chunk_path: Path,
    role: str,
    sr: int,
    dialogue_style: bool,
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from audio_post import (
        apply_chunk_lead_fade_in,
        apply_chunk_tail_pad,
        apply_dialogue_style,
        apply_narration_loudnorm_if_enabled,
    )
    from audio_quality_config import dialogue_post_should_run

    if role == "dialogue" and dialogue_style and dialogue_post_should_run():
        styled = chunk_path.with_name(chunk_path.stem + "_styled.wav")
        apply_dialogue_style(chunk_path, styled, sr)
        styled.replace(chunk_path)
    else:
        # Dialogue style chain already afade=t=in; narration/dialogue need chunk-start de-click.
        apply_chunk_lead_fade_in(chunk_path, sr)
        if role == "narration":
            apply_narration_loudnorm_if_enabled(chunk_path, sr)
    apply_chunk_tail_pad(chunk_path, sr)


def synthesize_chunk_to_wav(
    model,
    chunk: tuple[str, str, str],
    voice_ref,
    lang: str,
    temperature: float | None,
    out_path: Path,
    dialogue_style: bool,
) -> int:
    import numpy as np
    from mlx_audio import audio_io as sf

    text, _pause_kind, role = chunk
    kw: dict = dict(
        text=text,
        ref_audio=voice_ref.audio_array(),
        ref_text=voice_ref.text,
        lang_code=lang,
    )
    if temperature is not None:
        kw["temperature"] = temperature
    try:
        results = list(model.generate(**kw))
    except TypeError:
        kw.pop("lang_code", None)
        results = list(model.generate(**kw))
    audio = np.concatenate([np.array(r.audio, dtype=np.float32).reshape(-1) for r in results])
    sr = int(getattr(results[0], "sample_rate", getattr(model, "sample_rate", 24000)))
    sf.write(str(out_path), audio, sr)
    post_process_chunk_wav(out_path, role, sr, dialogue_style)
    return sr


def generate_chunks_to_wav(
    model,
    chunks: list[tuple[str, str, str]],
    voice_ref,
    lang: str,
    tmpdir: str,
    sentence_pause: float,
    paragraph_pause: float,
    temperature: float | None,
    dialogue_style: bool = True,
    on_chunk: ChunkProgress | None = None,
) -> tuple[list[str], int, float]:
    sr = getattr(model, "sample_rate", 24000)
    files: list[str] = []
    t_tts = time.time()

    for i, chunk in enumerate(chunks):
        t1 = time.time()
        f = os.path.join(tmpdir, f"chunk_{i:04d}.wav")
        sr = synthesize_chunk_to_wav(
            model,
            chunk,
            voice_ref,
            lang,
            temperature,
            Path(f),
            dialogue_style,
        )
        files.append(f)
        text, _pause, role = chunk
        print(
            f"[{i + 1}/{len(chunks)}] TTS {time.time() - t1:.1f}s [{role}] :: {text[:40]}",
            file=sys.stderr,
        )
        if on_chunk:
            on_chunk(i + 1, len(chunks))

    sil_sentence = os.path.join(tmpdir, "silence_sentence.wav")
    sil_paragraph = os.path.join(tmpdir, "silence_paragraph.wav")
    for path, duration in (
        (sil_sentence, sentence_pause),
        (sil_paragraph, paragraph_pause),
    ):
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
                path,
            ],
            check=True,
        )

    lst = os.path.join(tmpdir, "list.txt")
    write_chunk_concat_list(lst, files, chunks, sil_sentence, sil_paragraph)

    return files, sr, time.time() - t_tts


def write_chunk_concat_list(
    list_path: str | Path,
    chunk_files: list[str | Path],
    chunks: list[tuple[str, str, str]],
    silence_sentence: str | Path,
    silence_paragraph: str | Path,
) -> None:
    """ffmpeg concat demuxer list: optional pause wav between chunk files."""
    with open(list_path, "w", encoding="utf-8") as fh:
        for i, f in enumerate(chunk_files):
            if i:
                _, pause_kind, _role = chunks[i - 1]
                sil = silence_paragraph if pause_kind == "paragraph" else silence_sentence
                fh.write(f"file '{os.fspath(sil)}'\n")
            fh.write(f"file '{os.fspath(f)}'\n")


def story_chunks_for_tts(story_text: str, max_chars: int) -> list[tuple[str, str, str]]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_segmentation import split_story_into_chunks

    return [(c.text, c.pause_after, c.role) for c in split_story_into_chunks(story_text, max_chars)]


def ffmpeg_concat_wav(list_path: str, sr: int, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-ar",
            str(sr),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            os.fspath(out_wav),
        ],
        check=True,
    )


def ffmpeg_concat_to_out(list_path: str, sr: int, out_path: Path) -> None:
    """Concat chunks then final loudnorm + encode (tests / legacy callers)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from audio_post import apply_final_loudnorm_if_enabled, encode_story_from_wav

    tmp = Path(list_path).parent / "_concat_story.wav"
    ffmpeg_concat_wav(list_path, sr, tmp)
    apply_final_loudnorm_if_enabled(tmp)
    encode_story_from_wav(tmp, out_path, sr)


def narrate_story(
    story_text: str,
    out_path: Path,
    ref_audio: Path,
    ref_text: str,
    model,
    max_chars: int = DEFAULT_MAX_CHARS,
    sentence_pause: float = DEFAULT_SENTENCE_PAUSE,
    paragraph_pause: float = DEFAULT_PARAGRAPH_PAUSE,
    temperature: float | None = None,
    dialogue_style: bool = True,
    keep_chunks: bool = False,
    on_progress: ChunkProgress | None = None,
    narration_config=None,
    tts_session=None,
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from audio_post import apply_final_loudnorm_if_enabled, encode_story_from_wav
    from story_narration import VoiceReference, default_narration_config, run_asr_verification

    cfg = narration_config or default_narration_config()
    chunks = story_chunks_for_tts(story_text, max_chars)
    if not chunks:
        raise ValueError("Story text is empty")
    print(f"{len(chunks)} chunks", file=sys.stderr)

    voice_ref = VoiceReference(path=ref_audio, text=ref_text)
    tmpdir = tempfile.mkdtemp(
        prefix="story_chunks_", dir=str(out_path.parent if out_path.parent.exists() else ROOT / "out")
    )
    t_total = time.time()
    try:
        active_model = tts_session.model if tts_session else model
        _files, sr, t_tts = generate_chunks_to_wav(
            active_model,
            chunks,
            voice_ref,
            "Korean",
            tmpdir,
            sentence_pause,
            paragraph_pause,
            temperature,
            dialogue_style=dialogue_style,
            on_chunk=on_progress,
        )
        chunk_paths = [Path(p) for p in _files]
        t_asr = 0.0
        retries = 0

        if cfg.verify_asr:
            if tts_session is None:
                raise RuntimeError("ASR verify requires TtsSession for TTS/ASR memory handoff")

            def _resynth(m, chunk_tuple, path: Path) -> None:
                synthesize_chunk_to_wav(
                    m,
                    chunk_tuple,
                    voice_ref,
                    "Korean",
                    temperature,
                    path,
                    dialogue_style,
                )

            chunk_paths, vstats = run_asr_verification(
                chunks,
                chunk_paths,
                tts_session,
                cfg,
                _resynth,
            )
            t_asr = vstats.asr_seconds
            retries = vstats.retry_generations

        sil_sentence = os.path.join(tmpdir, "silence_sentence.wav")
        sil_paragraph = os.path.join(tmpdir, "silence_paragraph.wav")
        lst = os.path.join(tmpdir, "list.txt")
        write_chunk_concat_list(
            lst,
            [str(p) for p in chunk_paths],
            chunks,
            sil_sentence,
            sil_paragraph,
        )
        story_wav = Path(tmpdir) / "story_concat.wav"
        ffmpeg_concat_wav(lst, sr, story_wav)
        t_ln = time.time()
        apply_final_loudnorm_if_enabled(story_wav)
        t_ln = time.time() - t_ln
        encode_story_from_wav(story_wav, out_path, sr)
        print(
            f"done: {out_path}  TTS {t_tts:.1f}s  ASR {t_asr:.1f}s  "
            f"retries {retries}  loudnorm {t_ln:.1f}s  total {time.time() - t_total:.1f}s",
            file=sys.stderr,
        )
    finally:
        if not keep_chunks:
            shutil.rmtree(tmpdir, ignore_errors=True)


class StoryGenerator:
    """Keep the TTS model loaded across multiple stories."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        ref_audio: Path = DEFAULT_REF_WAV,
        ref_text: str | None = None,
        ref_text_path: Path | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
        sentence_pause: float = DEFAULT_SENTENCE_PAUSE,
        paragraph_pause: float = DEFAULT_PARAGRAPH_PAUSE,
        temperature: float | None = None,
        dialogue_style: bool | None = None,
        keep_chunks: bool = False,
        verify_asr: bool | None = None,
        cer_threshold: float | None = None,
        max_asr_retries: int | None = None,
    ) -> None:
        from mlx_audio.tts.utils import load_model

        sys.path.insert(0, str(ROOT / "scripts"))
        from audio_quality_config import dialogue_style_enabled

        self.ref_audio = ref_audio
        if ref_text is None:
            ref_text_path = ref_text_path or DEFAULT_REF_TEXT
            ref_text = load_ref_text(ref_text_path)
        self.ref_text = ref_text
        self.max_chars = max_chars
        self.sentence_pause = sentence_pause
        self.paragraph_pause = paragraph_pause
        self.temperature = temperature
        self.dialogue_style = dialogue_style if dialogue_style is not None else dialogue_style_enabled()
        self.keep_chunks = keep_chunks
        self.model_id = model_id
        self._model = None
        sys.path.insert(0, str(ROOT / "scripts"))
        from audio_quality_config import (
            DEFAULT_CER_THRESHOLD,
            DEFAULT_MAX_ASR_RETRIES,
            asr_verify_enabled,
        )
        from story_narration import NarrationConfig, TtsSession

        self.narration_config = NarrationConfig(
            verify_asr=verify_asr if verify_asr is not None else asr_verify_enabled(),
            cer_threshold=cer_threshold if cer_threshold is not None else DEFAULT_CER_THRESHOLD,
            max_asr_retries=max_asr_retries if max_asr_retries is not None else DEFAULT_MAX_ASR_RETRIES,
        )
        self._TtsSession = TtsSession
        t0 = time.time()
        print(f"Loading model {model_id}…", file=sys.stderr)
        self._model = load_model(model_id)
        print(f"model loaded in {time.time() - t0:.1f}s", file=sys.stderr)

    @property
    def model(self):
        return self._model

    def _load_model(self):
        if self._model is None:
            from mlx_audio.tts.utils import load_model

            print(f"Reloading TTS model {self.model_id}…", file=sys.stderr)
            t0 = time.time()
            self._model = load_model(self.model_id)
            print(f"TTS reloaded in {time.time() - t0:.1f}s", file=sys.stderr)
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
        import mlx.core as mx

        session = None
        if self.narration_config.verify_asr:
            session = self._TtsSession(self._load_model, self._unload_model)
        narrate_story(
            story_text,
            output_path,
            self.ref_audio,
            self.ref_text,
            self._model,
            max_chars=self.max_chars,
            sentence_pause=self.sentence_pause,
            paragraph_pause=self.paragraph_pause,
            temperature=self.temperature,
            dialogue_style=self.dialogue_style,
            keep_chunks=self.keep_chunks,
            on_progress=on_progress,
            narration_config=self.narration_config,
            tts_session=session,
        )
        try:
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
    ap = argparse.ArgumentParser(description="Clone voice and narrate a story with Qwen3-TTS (MLX).")
    ap.add_argument(
        "catalog_story",
        nargs="?",
        type=Path,
        help="Catalog story path (content/stories/*.txt with YAML frontmatter)",
    )
    ap.add_argument("--ref-audio", type=Path, default=None)
    ap.add_argument("--ref-text", default=None, help="Transcript string or path to .txt")
    ap.add_argument("--story", type=Path, default=None, help="Plain story text file (validated CLI)")
    ap.add_argument("--out", type=Path, default=None, help="Output .wav / .m4a / .mp3")
    ap.add_argument("--output", type=Path, default=None, help="Alias for --out (catalog shortcut)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--lang", default="Korean")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument(
        "--pause",
        type=float,
        default=None,
        help="Silence (s) between all chunks; sets both sentence and paragraph pause",
    )
    ap.add_argument("--sentence-pause", type=float, default=None)
    ap.add_argument("--paragraph-pause", type=float, default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument(
        "--no-dialogue-style",
        action="store_true",
        help="Disable dialogue-only post-process (pitch/gain/fades)",
    )
    ap.add_argument("--keep-chunks", action="store_true")
    a = ap.parse_args()

    sentence_pause = a.sentence_pause
    paragraph_pause = a.paragraph_pause
    if a.pause is not None:
        sentence_pause = paragraph_pause = a.pause
    if sentence_pause is None:
        sentence_pause = DEFAULT_SENTENCE_PAUSE
    if paragraph_pause is None:
        paragraph_pause = DEFAULT_PARAGRAPH_PAUSE

    legacy = a.story is not None and a.ref_audio is not None
    catalog = a.catalog_story is not None and not legacy

    if legacy:
        story_path = a.story
        if not story_path.is_file():
            sys.exit(f"Story file not found: {story_path}")
        story_text = read_story_text(story_path, catalog_mode=False)
        ref_audio = a.ref_audio
        if a.ref_text is None:
            sys.exit("--ref-text is required with --story and --ref-audio")
        ref_text = load_ref_text(a.ref_text)
        out = a.out or a.output
        if out is None:
            sys.exit("--out is required with --story and --ref-audio")
    elif catalog:
        story_path = a.catalog_story
        if not story_path.is_file():
            sys.exit(f"Story file not found: {story_path}")
        story_text = read_story_text(story_path, catalog_mode=True)
        ref_audio = a.ref_audio or DEFAULT_REF_WAV
        ref_text_path = a.ref_text or DEFAULT_REF_TEXT
        ref_text = load_ref_text(ref_text_path)
        sys.path.insert(0, str(ROOT / "scripts"))
        from story_catalog import load_story

        story_id = load_story(story_path).id
        out = a.out or a.output or (DEFAULT_AUDIO_DIR / f"{story_id}.m4a")
    else:
        sys.exit("Provide catalog story path or --ref-audio + --ref-text + --story + --out")

    if not ref_audio.is_file():
        sys.exit(f"Reference audio not found: {ref_audio}")

    sys.path.insert(0, str(ROOT / "scripts"))
    from audio_quality_config import dialogue_style_enabled

    dialogue_style = dialogue_style_enabled() and not a.no_dialogue_style

    gen = StoryGenerator(
        model_id=a.model,
        ref_audio=ref_audio,
        ref_text=ref_text,
        max_chars=a.max_chars,
        sentence_pause=sentence_pause,
        paragraph_pause=paragraph_pause,
        temperature=a.temperature,
        dialogue_style=dialogue_style,
        keep_chunks=a.keep_chunks,
    )
    gen.generate_story(story_text, out)


if __name__ == "__main__":
    main()
