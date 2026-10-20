"""Character error rate for Korean ASR verification."""

from __future__ import annotations

import re

def normalize_korean_for_cer(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    # Keep Hangul / letters / digits; drop punctuation and quotes for CER.
    text = re.sub(r"[^\w]", "", text, flags=re.UNICODE)
    return text.casefold()


def levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize_korean_for_cer(reference)
    hyp = normalize_korean_for_cer(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein_distance(ref, hyp) / len(ref)
