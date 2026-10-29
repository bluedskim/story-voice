"""TTS sentence-ending helpers: input-text ellipsis and abrupt-ending detection.

Qwen3-TTS voice clones (notably the Harry reference) sometimes end a chunk while the
last syllable is still loud and drop to silence within ~10ms. Post-processing only
appends silence, so the fix has to happen at synthesis time:

* ``tts_input_text`` appends `` …`` to the text fed to the model only. Story text,
  manifests and ASR verification keep using the original chunk text.
* ``analyze_tail`` measures how fast the last voiced frame decays (10ms RMS envelope);
  ``synthesize_chunk_to_wav`` regenerates abrupt takes a bounded number of times.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ELLIPSIS = "\u2026"
FRAME_SEC = 0.010
_TRAILING_ELLIPSIS_FORMS = (ELLIPSIS, "...", "\u22ef")


def tts_input_text(text: str, enabled: bool | None = None) -> str:
    """Text to feed the TTS model for one chunk (display/ASR keep ``text``)."""
    if enabled is None:
        from audio_quality_config import tts_trailing_ellipsis_enabled

        enabled = tts_trailing_ellipsis_enabled()
    stripped = text.rstrip()
    if not enabled or not stripped:
        return text
    if stripped.endswith(_TRAILING_ELLIPSIS_FORMS):
        return stripped
    return f"{stripped} {ELLIPSIS}"


@dataclass(frozen=True)
class TailAnalysis:
    abrupt: bool
    decay_ms: float  # last frame above hi_db -> last frame above lo_db
    ends_loud: bool  # file ends with last frame above eof_db
    last_frame_db: float  # rel. peak

    @property
    def score(self) -> float:
        """Higher = more natural ending (used to pick the best take)."""
        s = min(self.decay_ms, 300.0)
        if self.ends_loud:
            s -= 1000.0
        if self.abrupt:
            s -= 500.0
        return s


def frame_db_rel_peak(audio, sr: int, frame_sec: float = FRAME_SEC) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float64).reshape(-1)
    fr = max(1, int(round(sr * frame_sec)))
    n = len(x) // fr
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt((x[: n * fr].reshape(n, fr) ** 2).mean(axis=1))
    db = 20.0 * np.log10(rms + 1e-9)
    return db - db.max()


def analyze_tail(
    audio,
    sr: int,
    hi_db: float | None = None,
    lo_db: float | None = None,
    max_decay_ms: float | None = None,
    eof_db: float | None = None,
) -> TailAnalysis:
    from audio_quality_config import (
        tail_abrupt_eof_db,
        tail_abrupt_hi_db,
        tail_abrupt_lo_db,
        tail_abrupt_max_decay_ms,
    )

    hi_db = tail_abrupt_hi_db() if hi_db is None else hi_db
    lo_db = tail_abrupt_lo_db() if lo_db is None else lo_db
    max_decay_ms = tail_abrupt_max_decay_ms() if max_decay_ms is None else max_decay_ms
    eof_db = tail_abrupt_eof_db() if eof_db is None else eof_db

    rel = frame_db_rel_peak(audio, sr)
    if len(rel) < 3:
        return TailAnalysis(abrupt=False, decay_ms=0.0, ends_loud=False, last_frame_db=0.0)
    above_lo = np.nonzero(rel > lo_db)[0]
    end = int(above_lo[-1])
    above_hi = np.nonzero(rel[: end + 1] > hi_db)[0]
    last_hi = int(above_hi[-1]) if len(above_hi) else end
    decay_ms = (end - last_hi) * FRAME_SEC * 1000.0
    last_db = float(rel[-1])
    ends_loud = last_db > eof_db
    abrupt = ends_loud or decay_ms <= max_decay_ms + 1e-6
    return TailAnalysis(abrupt=abrupt, decay_ms=decay_ms, ends_loud=ends_loud, last_frame_db=last_db)
