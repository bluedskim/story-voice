#!/usr/bin/env python3
"""Clone parent voice and narrate one story (chunked TTS + ffmpeg concat)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Defaults from Mac mini validation
DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
DEFAULT_REF_WAV = ROOT / "data" / "voice" / "reference.wav"
DEFAULT_REF_TEXT = ROOT / "data" / "voice" / "reference.txt"
DEFAULT_AUDIO_DIR = ROOT / "data" / "audio"
DEFAULT_SENTENCE_PAUSE = 0.35
DEFAULT_PARAGRAPH_PAUSE = 0.75

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!…])\s+")


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs and text.strip():
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return paragraphs


def split_sentences(paragraph: str) -> list[str]:
    parts = SENTENCE_SPLIT_RE.split(paragraph.strip())
    return [p.strip() for p in parts if p.strip()]


def iter_chunks(text: str) -> list[tuple[str, str]]:
    """Return (chunk_text, pause_kind) where pause_kind is 'sentence' or 'paragraph'."""
    chunks: list[tuple[str, str]] = []
    paragraphs = split_paragraphs(text)
    for pi, paragraph in enumerate(paragraphs):
        sentences = split_sentences(paragraph)
        for si, sentence in enumerate(sentences):
            chunks.append((sentence, "paragraph" if si == len(sentences) - 1 else "sentence"))
        if pi < len(paragraphs) - 1 and sentences:
            # Mark last sentence of paragraph for longer pause (already 'paragraph')
            pass
    return chunks


def silence_wav(path: Path, duration_sec: float, sample_rate: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            str(duration_sec),
            "-acodec",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def generate_chunk_wav(
    model,
    text: str,
    ref_audio: Path,
    ref_text: str,
    out_path: Path,
    lang_code: str,
) -> int:
    import numpy as np
    from mlx_audio.audio_io import write as audio_write

    results = list(
        model.generate(
            text=text,
            ref_audio=str(ref_audio),
            ref_text=ref_text,
            lang_code=lang_code,
            verbose=False,
        )
    )
    if not results:
        raise RuntimeError(f"No audio generated for chunk: {text[:40]}…")
    audio = results[0].audio
    sample_rate = results[0].sample_rate
    audio_write(str(out_path), np.array(audio), sample_rate, format="wav")
    return sample_rate


def concat_wavs_ffmpeg(chunk_paths: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as list_file:
        for p in chunk_paths:
            # ffmpeg concat demuxer requires escaped paths
            escaped = str(p.resolve()).replace("'", r"'\''")
            list_file.write(f"file '{escaped}'\n")
        list_path = Path(list_file.name)

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    list_path.unlink(missing_ok=True)


class StoryGenerator:
    """Keep the TTS model loaded across multiple stories."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        ref_audio: Path = DEFAULT_REF_WAV,
        ref_text_path: Path = DEFAULT_REF_TEXT,
        lang_code: str = "Korean",
        sentence_pause: float = DEFAULT_SENTENCE_PAUSE,
        paragraph_pause: float = DEFAULT_PARAGRAPH_PAUSE,
        work_dir: Path | None = None,
    ) -> None:
        from mlx_audio.tts.utils import load_model

        self.model_id = model_id
        self.ref_audio = ref_audio
        self.ref_text = ref_text_path.read_text(encoding="utf-8").strip()
        self.lang_code = lang_code
        self.sentence_pause = sentence_pause
        self.paragraph_pause = paragraph_pause
        self.work_dir = work_dir or (ROOT / "out" / "chunks")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        print(f"Loading model {model_id}…", file=sys.stderr)
        self.model = load_model(model_id)
        self._sample_rate: int | None = None

    def generate_story(self, story_text: str, output_m4a: Path) -> None:
        chunks = iter_chunks(story_text)
        if not chunks:
            raise ValueError("Story text is empty")

        piece_paths: list[Path] = []
        story_work = self.work_dir / output_m4a.stem
        story_work.mkdir(parents=True, exist_ok=True)

        for index, (text, pause_kind) in enumerate(chunks):
            wav_path = story_work / f"{index:04d}.wav"
            print(f"  [{index + 1}/{len(chunks)}] {text[:50]}…", file=sys.stderr)
            sample_rate = generate_chunk_wav(
                self.model,
                text,
                self.ref_audio,
                self.ref_text,
                wav_path,
                self.lang_code,
            )
            self._sample_rate = sample_rate
            piece_paths.append(wav_path)

            is_last = index == len(chunks) - 1
            if not is_last:
                pause = self.paragraph_pause if pause_kind == "paragraph" else self.sentence_pause
                silence_path = story_work / f"{index:04d}_pause.wav"
                silence_wav(silence_path, pause, sample_rate)
                piece_paths.append(silence_path)

        print("Concatenating with ffmpeg…", file=sys.stderr)
        concat_wavs_ffmpeg(piece_paths, output_m4a)
        print(f"Wrote {output_m4a}", file=sys.stderr)


def generate_from_story_file(
    story_path: Path,
    output_m4a: Path | None = None,
    generator: StoryGenerator | None = None,
    **generator_kwargs,
) -> Path:
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_catalog import load_story

    story = load_story(story_path)
    out = output_m4a or (DEFAULT_AUDIO_DIR / f"{story.id}.m4a")
    owns_generator = generator is None
    if owns_generator:
        generator = StoryGenerator(**generator_kwargs)
    generator.generate_story(story.body, out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate cloned-voice audio for one story.")
    parser.add_argument("story", type=Path, help="Path to story .txt (with YAML frontmatter)")
    parser.add_argument("--output", type=Path, help="Output .m4a path (default: data/audio/<id>.m4a)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ref-audio", type=Path, default=DEFAULT_REF_WAV)
    parser.add_argument("--ref-text", type=Path, default=DEFAULT_REF_TEXT)
    parser.add_argument("--lang", default="Korean", dest="lang_code")
    parser.add_argument(
        "--sentence-pause",
        type=float,
        default=DEFAULT_SENTENCE_PAUSE,
        help="Seconds of silence between sentences (default: 0.35)",
    )
    parser.add_argument(
        "--paragraph-pause",
        type=float,
        default=DEFAULT_PARAGRAPH_PAUSE,
        help="Seconds of silence after each paragraph (default: 0.75)",
    )
    args = parser.parse_args()

    if not args.ref_audio.is_file():
        sys.exit(f"Reference audio not found: {args.ref_audio}")
    if not args.ref_text.is_file():
        sys.exit(f"Reference transcript not found: {args.ref_text}")

    generate_from_story_file(
        args.story,
        output_m4a=args.output,
        model_id=args.model,
        ref_audio=args.ref_audio,
        ref_text_path=args.ref_text,
        lang_code=args.lang_code,
        sentence_pause=args.sentence_pause,
        paragraph_pause=args.paragraph_pause,
    )


if __name__ == "__main__":
    main()
