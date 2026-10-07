"""Timestamp formatting and precise phrase localization.

This module is the single source of truth for:
  - turning raw seconds into MM:SS / HH:MM:SS strings
  - normalizing text for robust comparisons (case, punctuation, whitespace)
  - locating an exact phrase inside word-level timing data so we can return
    the timestamp of the *matching words*, not just the timestamp of the
    chunk that happens to contain them.

Keeping this in one module means app/llm.py, app/search.py, app/rag.py, and
the worker all agree on timestamp formatting instead of drifting apart.
"""
import re
import difflib
from typing import Dict, List, Optional, TypedDict


class Word(TypedDict, total=False):
    word: str
    start: float
    end: float


def format_timestamp(seconds: Optional[float]) -> str:
    """Format seconds as MM:SS, or HH:MM:SS once past an hour.

    Examples: 31 -> "00:31", 1421 -> "23:41", 3725 -> "01:02:05".
    """
    if seconds is None:
        return "00:00"
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def timestamp_pair(seconds: Optional[float]) -> Dict:
    """Return both the raw-seconds and formatted representations."""
    return {"seconds": float(seconds or 0.0), "formatted": format_timestamp(seconds)}


_PUNCT_RE = re.compile(r"[^\w\s']", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation (keep apostrophes for contractions),
    and collapse whitespace, so comparisons are robust to casing and
    stray punctuation from captions/Whisper output."""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def normalize_tokens(text: str) -> List[str]:
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def locate_phrase_in_words(
    phrase: str, words: List[Word], fuzzy_threshold: float = 0.82
) -> Optional[Dict]:
    """Find the timestamp span of `phrase` inside a list of word-timing
    dicts ({"word", "start", "end"}), e.g. from Whisper.

    Matching is case-insensitive and punctuation-normalized. If no exact
    token-sequence match is found, falls back to a fuzzy sliding-window
    match (useful for ASR transcription noise / minor mis-transcriptions).

    Returns {"start", "end", "matched_text", "exact"} or None if the words
    list is empty or the phrase can't be reasonably located.
    """
    phrase_tokens = normalize_tokens(phrase)
    if not phrase_tokens or not words:
        return None

    # A single ASR "word" can itself normalize to multiple tokens (e.g.
    # "OPEN-AI," -> "open ai"), so flatten to a token stream while keeping
    # a mapping back to the source word index for start/end lookup.
    flat_tokens: List[str] = []
    token_to_word_idx: List[int] = []
    for idx, w in enumerate(words):
        for tok in normalize_tokens(w.get("word", "")):
            flat_tokens.append(tok)
            token_to_word_idx.append(idx)

    n, m = len(flat_tokens), len(phrase_tokens)
    if m == 0 or n == 0:
        return None

    # 1) Exact contiguous token-sequence match (over flattened tokens).
    for i in range(0, n - m + 1):
        if flat_tokens[i : i + m] == phrase_tokens:
            start_word_idx = token_to_word_idx[i]
            end_word_idx = token_to_word_idx[i + m - 1]
            return {
                "start": float(words[start_word_idx].get("start", 0.0)),
                "end": float(
                    words[end_word_idx].get("end", words[start_word_idx].get("start", 0.0))
                ),
                "matched_text": " ".join(
                    w.get("word", "").strip() for w in words[start_word_idx : end_word_idx + 1]
                ),
                "exact": True,
            }

    word_tokens = [normalize_text(w.get("word", "")) for w in words]

    # 2) Fuzzy sliding window over windows of length m (and m+/-1 to absorb
    # small ASR insertions/deletions), scored by string similarity.
    phrase_norm = " ".join(phrase_tokens)
    best_score = 0.0
    best_span = None
    for width in (m - 1, m, m + 1):
        if width <= 0:
            continue
        for i in range(0, max(0, n - width + 1)):
            window_tokens = word_tokens[i : i + width]
            if not window_tokens:
                continue
            window_norm = " ".join(window_tokens)
            score = _fuzzy_ratio(phrase_norm, window_norm)
            if score > best_score:
                best_score = score
                best_span = (i, i + width)

    if best_span and best_score >= fuzzy_threshold:
        i, j = best_span
        return {
            "start": float(words[i].get("start", 0.0)),
            "end": float(words[j - 1].get("end", words[i].get("start", 0.0))),
            "matched_text": " ".join(w.get("word", "").strip() for w in words[i:j]),
            "exact": False,
            "score": best_score,
        }

    return None


def locate_phrase_in_segment(phrase: str, segment: Dict) -> Dict:
    """Best-effort localization of `phrase` within a transcript_segments
    row (as a dict with start_time/end_time/text/word_timings).

    Uses word-level timing when available (precise); otherwise falls back
    to the whole segment's start/end (chunk-level precision).
    """
    words = segment.get("word_timings") or []
    if words:
        hit = locate_phrase_in_words(phrase, words)
        if hit:
            return {
                "start_time": hit["start"],
                "end_time": hit["end"],
                "matched_text": hit["matched_text"],
                "exact": hit["exact"],
            }

    # No word timings, or phrase not confidently located within them:
    # fall back to chunk-level timestamp.
    return {
        "start_time": segment["start_time"],
        "end_time": segment["end_time"],
        "matched_text": segment.get("text", ""),
        "exact": normalize_text(phrase) in normalize_text(segment.get("text", "")),
    }
