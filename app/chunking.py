import re
from typing import List, Dict, Optional

from app.config import settings

_SENTENCE_END_RE = re.compile(r"[.!?]['\"]?\s*$")


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END_RE.search(text.strip()))


def chunk_segments(
    segments: List[Dict],
    min_chars: Optional[int] = None,
    max_chars: Optional[int] = None,
    min_seconds: Optional[float] = None,
    max_seconds: Optional[float] = None,
) -> List[Dict]:
    """Merge fine-grained transcript lines (YouTube captions are often just
    a few words each; Whisper segments are usually a sentence or so) into
    semantic chunks of roughly `min_chars`-`max_chars` characters / a
    `min_seconds`-`max_seconds` duration, breaking near sentence
    boundaries where possible, while preserving:
      - the chunk's start/end timestamps
      - the concatenated word-level timing data of everything merged in
        (each chunk's "words" list, used later for exact phrase lookup)

    A chunk is closed (and a new one started) when:
      - it has already reached min_chars/min_seconds AND the next line
        ends a sentence (clean semantic boundary), or
      - adding the next line would push it past max_chars or max_seconds
        regardless of sentence boundaries (hard cap, avoids runaway chunks).
    """
    min_chars = min_chars if min_chars is not None else settings.CHUNK_MIN_CHARS
    max_chars = max_chars if max_chars is not None else settings.CHUNK_MAX_CHARS
    min_seconds = min_seconds if min_seconds is not None else settings.CHUNK_MIN_SECONDS
    max_seconds = max_seconds if max_seconds is not None else settings.CHUNK_MAX_SECONDS

    if not segments:
        return []

    chunks: List[Dict] = []
    current_text: List[str] = []
    current_words: List[Dict] = []
    current_start = None
    current_end = None

    def flush():
        if not current_text:
            return
        chunks.append(
            {
                "start": current_start,
                "end": current_end,
                "text": " ".join(current_text).strip(),
                "words": list(current_words),
            }
        )

    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue

        if current_start is None:
            current_start = seg["start"]

        prospective_text_len = len(" ".join(current_text + [text]))
        prospective_duration = seg["end"] - (current_start or seg["start"])
        has_min = (
            len(" ".join(current_text)) >= min_chars
            or (current_end is not None and current_end - current_start >= min_seconds)
        )
        at_sentence_boundary = bool(current_text) and _ends_sentence(current_text[-1])

        should_close_soft = current_text and has_min and at_sentence_boundary
        should_close_hard = current_text and (
            prospective_text_len > max_chars or prospective_duration > max_seconds
        )

        if should_close_soft or should_close_hard:
            flush()
            current_text = [text]
            current_words = list(seg.get("words") or [])
            current_start = seg["start"]
            current_end = seg["end"]
        else:
            current_text.append(text)
            current_words.extend(seg.get("words") or [])
            current_end = seg["end"]

    flush()
    return chunks
