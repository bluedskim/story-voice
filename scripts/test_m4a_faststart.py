"""Story m4a output must be faststart (moov before mdat)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_post import encode_story_from_wav  # noqa: E402
from m4a_faststart import is_faststart, remux_faststart, top_level_atoms  # noqa: E402


def _tone_wav(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ar", "24000", "-ac", "1", str(path)],
        check=True,
    )


def test_encode_story_is_faststart() -> None:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "s.wav"
        out = Path(d) / "s.m4a"
        _tone_wav(wav)
        encode_story_from_wav(wav, out, 24000)
        assert is_faststart(out), top_level_atoms(out)


def test_remux_moves_moov_front_losslessly() -> None:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "s.wav"
        out = Path(d) / "s.m4a"
        _tone_wav(wav)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(out)],
            check=True,
        )
        assert not is_faststart(out)
        before = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(out), "-map", "0:a", "-c", "copy", "-f", "data", "-"],
            capture_output=True, check=True,
        ).stdout
        remux_faststart(out)
        assert is_faststart(out)
        after = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(out), "-map", "0:a", "-c", "copy", "-f", "data", "-"],
            capture_output=True, check=True,
        ).stdout
        assert before == after


if __name__ == "__main__":
    test_encode_story_is_faststart()
    test_remux_moves_moov_front_losslessly()
    print("ok")
