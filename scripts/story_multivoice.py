"""Multivoice story rendering (PoC): per-chunk voice references."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

VoiceRefResolver = Callable[["StoryChunkLike"], object]


class StoryChunkLike:
    text: str
    pause_after: str
    role: str
    speaker_key: str | None


def load_voice_reference(wav: Path, txt: Path | None = None) -> object:
    sys.path.insert(0, str(ROOT / "scripts"))
    from clone_story import load_ref_text
    from story_narration import VoiceReference

    if not wav.is_file():
        raise FileNotFoundError(f"Reference wav not found: {wav}")
    text_path = txt
    if text_path is None:
        candidates = [wav.with_suffix(".txt"), wav.parent / "reference.txt"]
        for c in candidates:
            if c.is_file():
                text_path = c
                break
    if text_path is None or not text_path.is_file():
        raise FileNotFoundError(f"Reference transcript not found for {wav}")
    return VoiceReference(path=wav, text=load_ref_text(text_path))


def parse_ref_arg(raw: str) -> tuple[Path, Path | None]:
    """Parse CLI ref: path/to.wav or path/to.wav,path/to.txt"""
    if "," in raw:
        wav_s, txt_s = raw.split(",", 1)
        return Path(wav_s.strip()), Path(txt_s.strip())
    wav = Path(raw.strip())
    return wav, None


def build_voice_resolver(
    narrator_ref: object,
    default_character_ref: object,
    speaker_map: dict[str, object],
) -> VoiceRefResolver:
    def resolve(chunk: StoryChunkLike) -> object:
        key = chunk.speaker_key
        if key is None:
            return narrator_ref
        return speaker_map.get(key, default_character_ref)

    return resolve


def cache_voice_references(*refs: object) -> dict[int, object]:
    """Eager-load wav arrays once per distinct VoiceReference."""
    seen: dict[int, object] = {}
    for ref in refs:
        rid = id(ref)
        if rid not in seen:
            ref.audio_array()  # type: ignore[attr-defined]
            seen[rid] = ref
    return seen


ChunkTuple = tuple[str, str, str, str | None]


def story_chunks_for_multivoice(story_text: str, max_chars: int) -> list[ChunkTuple]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_segmentation import split_story_into_chunks

    return [
        (c.text, c.pause_after, c.role, c.speaker_key)
        for c in split_story_into_chunks(story_text, max_chars)
    ]


def narrate_story_multivoice(
    story_text: str,
    out_path: Path,
    resolve_voice: VoiceRefResolver,
    model,
    *,
    max_chars: int = 120,
    sentence_pause: float = 0.35,
    paragraph_pause: float = 0.75,
    temperature: float | None = None,
    dialogue_style: bool = True,
    narration_config=None,
    tts_session=None,
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from audio_post import apply_final_loudnorm_if_enabled, encode_story_from_wav
    from clone_story import (
        ffmpeg_concat_wav,
        generate_chunks_to_wav_multivoice,
        write_chunk_concat_list,
    )
    from story_narration import default_narration_config, run_asr_verification
    from story_segmentation import StoryChunk, split_story_into_chunks

    cfg = narration_config or default_narration_config()
    raw_chunks = split_story_into_chunks(story_text, max_chars)
    if not raw_chunks:
        raise ValueError("Story text is empty")
    chunks: list[tuple[str, str, str]] = [
        (c.text, c.pause_after, c.role) for c in raw_chunks
    ]
    chunk_objs: list[StoryChunk] = raw_chunks

    print(f"{len(chunks)} chunks (multivoice)", file=sys.stderr)

    tmpdir = tempfile.mkdtemp(
        prefix="poc_multivoice_",
        dir=str(out_path.parent if out_path.parent.exists() else ROOT / "out"),
    )
    t_total = time.time()
    try:
        active_model = tts_session.model if tts_session else model

        def _ref_for_index(i: int) -> object:
            return resolve_voice(chunk_objs[i])

        def _voice_label(i: int) -> str:
            key = chunk_objs[i].speaker_key
            if key is None:
                return "narrator"
            return f"character:{key}"

        _files, sr, t_tts = generate_chunks_to_wav_multivoice(
            active_model,
            chunks,
            _ref_for_index,
            "Korean",
            tmpdir,
            sentence_pause,
            paragraph_pause,
            temperature,
            dialogue_style=dialogue_style,
            voice_label_for_index=_voice_label,
        )
        chunk_paths = [Path(p) for p in _files]
        t_asr = 0.0
        retries = 0

        if cfg.verify_asr:
            if tts_session is None:
                raise RuntimeError("ASR verify requires TtsSession for TTS/ASR memory handoff")
            from clone_story import synthesize_chunk_to_wav

            def _resynth(m, chunk_tuple, path: Path) -> None:
                idx = next(i for i, ct in enumerate(chunks) if ct == chunk_tuple)
                synthesize_chunk_to_wav(
                    m,
                    chunk_tuple,
                    _ref_for_index(idx),
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
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


def story_markup_body_from_id(story_id: str) -> str:
    """Story body with @speaker lines intact (for PoC rendering)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_catalog import STORIES_DIR, FRONTMATTER_RE

    path = STORIES_DIR / f"{story_id}.txt"
    if not path.is_file():
        raise KeyError(story_id)
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if match:
        return raw[match.end() :].strip()
    return raw.strip()
