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

SENTENCE_END_RE = r"(?<=[.!?。！？…\"\"'''])\s+"


def split_sentences(text: str, max_chars: int) -> list[tuple[str, str]]:
    """Split story into TTS chunks (~max_chars) and label pauses after each chunk.

    Returns list of (chunk_text, pause_kind) where pause_kind is ``sentence`` or
    ``paragraph`` (end of a paragraph). The last chunk's pause_kind is ignored.
    """
    text = re.sub(r"[ \t]+", " ", text.strip())
    parts: list[tuple[str, str]] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    for para in paragraphs:
        sents = re.split(SENTENCE_END_RE, para)
        buf = ""
        para_chunks: list[str] = []
        for s in sents:
            s = s.strip()
            if not s:
                continue
            if buf and len(buf) + 1 + len(s) > max_chars:
                para_chunks.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            para_chunks.append(buf)
        for ci, chunk in enumerate(para_chunks):
            pause_kind = "paragraph" if ci == len(para_chunks) - 1 else "sentence"
            parts.append((chunk, pause_kind))
    return parts


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


def generate_chunks_to_wav(
    model,
    chunks: list[tuple[str, str]],
    ref_audio: str | Path,
    ref_text: str,
    lang: str,
    tmpdir: str,
    sentence_pause: float,
    paragraph_pause: float,
    temperature: float | None,
    on_chunk: ChunkProgress | None = None,
) -> tuple[list[str], int]:
    import mlx.core as mx
    import numpy as np
    from mlx_audio import audio_io as sf

    ref_audio_str = os.fspath(ref_audio)
    sr = getattr(model, "sample_rate", 24000)
    files: list[str] = []

    for i, (chunk, pause_kind) in enumerate(chunks):
        t1 = time.time()
        kw: dict = dict(text=chunk, ref_audio=ref_audio_str, ref_text=ref_text, lang_code=lang)
        if temperature is not None:
            kw["temperature"] = temperature
        try:
            results = list(model.generate(**kw))
        except TypeError:
            kw.pop("lang_code", None)
            results = list(model.generate(**kw))
        audio = np.concatenate(
            [np.array(r.audio, dtype=np.float32).reshape(-1) for r in results]
        )
        f = os.path.join(tmpdir, f"chunk_{i:04d}.wav")
        sf.write(f, audio, sr)
        files.append(f)
        print(
            f"[{i + 1}/{len(chunks)}] {len(audio) / sr:.1f}s audio in {time.time() - t1:.1f}s :: {chunk[:40]}",
            file=sys.stderr,
        )
        if on_chunk:
            on_chunk(i + 1, len(chunks))
        mx.clear_cache()

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
    with open(lst, "w", encoding="utf-8") as fh:
        for i, f in enumerate(files):
            if i:
                _, pause_kind = chunks[i - 1]
                sil = sil_paragraph if pause_kind == "paragraph" else sil_sentence
                fh.write(f"file '{sil}'\n")
            fh.write(f"file '{f}'\n")

    return files, sr


def ffmpeg_concat_to_out(list_path: str, sr: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_path.suffix.lower()
    cmd = [
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
    ]
    if suffix in {".m4a", ".mp4"}:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    elif suffix == ".mp3":
        cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
    cmd.append(os.fspath(out_path))
    subprocess.run(cmd, check=True)


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
    keep_chunks: bool = False,
    on_progress: ChunkProgress | None = None,
) -> None:
    chunks = split_sentences(story_text, max_chars)
    if not chunks:
        raise ValueError("Story text is empty")
    print(f"{len(chunks)} chunks", file=sys.stderr)

    tmpdir = tempfile.mkdtemp(
        prefix="story_chunks_", dir=str(out_path.parent if out_path.parent.exists() else ROOT / "out")
    )
    t_gen = time.time()
    try:
        _, sr = generate_chunks_to_wav(
            model,
            chunks,
            ref_audio,
            ref_text,
            "Korean",
            tmpdir,
            sentence_pause,
            paragraph_pause,
            temperature,
            on_chunk=on_progress,
        )
        lst = os.path.join(tmpdir, "list.txt")
        ffmpeg_concat_to_out(lst, sr, out_path)
        print(
            f"done: {out_path}  gen {time.time() - t_gen:.1f}s",
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
        keep_chunks: bool = False,
    ) -> None:
        from mlx_audio.tts.utils import load_model

        self.ref_audio = ref_audio
        if ref_text is None:
            ref_text_path = ref_text_path or DEFAULT_REF_TEXT
            ref_text = load_ref_text(ref_text_path)
        self.ref_text = ref_text
        self.max_chars = max_chars
        self.sentence_pause = sentence_pause
        self.paragraph_pause = paragraph_pause
        self.temperature = temperature
        self.keep_chunks = keep_chunks
        t0 = time.time()
        print(f"Loading model {model_id}…", file=sys.stderr)
        self.model = load_model(model_id)
        print(f"model loaded in {time.time() - t0:.1f}s", file=sys.stderr)

    def generate_story(
        self,
        story_text: str,
        output_path: Path,
        on_progress: ChunkProgress | None = None,
    ) -> None:
        import mlx.core as mx

        narrate_story(
            story_text,
            output_path,
            self.ref_audio,
            self.ref_text,
            self.model,
            max_chars=self.max_chars,
            sentence_pause=self.sentence_pause,
            paragraph_pause=self.paragraph_pause,
            temperature=self.temperature,
            keep_chunks=self.keep_chunks,
            on_progress=on_progress,
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

    gen = StoryGenerator(
        model_id=a.model,
        ref_audio=ref_audio,
        ref_text=ref_text,
        max_chars=a.max_chars,
        sentence_pause=sentence_pause,
        paragraph_pause=paragraph_pause,
        temperature=a.temperature,
        keep_chunks=a.keep_chunks,
    )
    gen.generate_story(story_text, out)


if __name__ == "__main__":
    main()
