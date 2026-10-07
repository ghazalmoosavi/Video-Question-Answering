import pytest
from app.timestamps import (
    format_timestamp,
    normalize_text,
    locate_phrase_in_words,
    locate_phrase_in_segment,
)


@pytest.mark.parametrize("seconds,expected", [
    (0, "00:00"),
    (31, "00:31"),
    (1421, "23:41"),
    (3725, "01:02:05"),
    (59, "00:59"),
    (60, "01:00"),
    (3599, "59:59"),
    (3600, "01:00:00"),
])
def test_format_timestamp(seconds, expected):
    assert format_timestamp(seconds) == expected


def test_format_timestamp_none():
    assert format_timestamp(None) == "00:00"


def test_normalize_text():
    assert normalize_text("Hello, WORLD!!") == "hello world"
    assert normalize_text("don't   stop") == "don't stop"
    assert normalize_text("  multiple   spaces  ") == "multiple spaces"


def _words(pairs):
    words = []
    t = 0.0
    for w, dur in pairs:
        words.append({"word": w, "start": t, "end": t + dur})
        t += dur
    return words


def test_locate_phrase_exact_match():
    words = _words([("They", 0.3), ("mentioned", 0.4), ("OpenAI", 0.5), ("today", 0.4)])
    hit = locate_phrase_in_words("OpenAI", words)
    assert hit is not None
    assert hit["exact"] is True
    assert hit["start"] == pytest.approx(0.7)
    assert hit["end"] == pytest.approx(1.2)


def test_locate_phrase_multi_word_exact():
    words = _words([("we", 0.2), ("use", 0.2), ("open", 0.3), ("a", 0.1), ("i", 0.3), ("daily", 0.4)])
    hit = locate_phrase_in_words("open a i", words)
    assert hit is not None
    assert hit["exact"] is True


def test_locate_phrase_case_insensitive_and_punctuation():
    words = _words([("OPEN-AI,", 0.4), ("is", 0.2), ("great", 0.4)])
    hit = locate_phrase_in_words("open ai", words)
    assert hit is not None
    assert hit["exact"] is True


def test_locate_phrase_fuzzy_match():
    # Slight ASR mis-transcription: "opening eye" instead of "open ai"
    words = _words([("they", 0.2), ("said", 0.2), ("opening", 0.3), ("eye", 0.3), ("again", 0.3)])
    hit = locate_phrase_in_words("open ai", words, fuzzy_threshold=0.5)
    assert hit is not None
    assert hit["exact"] is False


def test_locate_phrase_not_found_returns_none_for_unrelated_words():
    words = _words([("completely", 0.3), ("different", 0.3), ("topic", 0.3)])
    hit = locate_phrase_in_words("open ai", words, fuzzy_threshold=0.95)
    assert hit is None


def test_locate_phrase_empty_words():
    assert locate_phrase_in_words("open ai", []) is None


def test_locate_phrase_in_segment_with_word_timings():
    segment = {
        "start_time": 100.0,
        "end_time": 110.0,
        "text": "we talked about OpenAI today",
        "word_timings": _words([("we", 0.3), ("talked", 0.3), ("about", 0.3), ("OpenAI", 0.4), ("today", 0.3)]),
    }
    for w in segment["word_timings"]:
        w["start"] += 100.0
        w["end"] += 100.0
    hit = locate_phrase_in_segment("OpenAI", segment)
    assert hit["exact"] is True
    assert hit["start_time"] > 100.0
    assert hit["start_time"] < segment["end_time"]


def test_locate_phrase_in_segment_without_word_timings_falls_back_to_chunk():
    segment = {"start_time": 50.0, "end_time": 70.0, "text": "OpenAI came up here", "word_timings": None}
    hit = locate_phrase_in_segment("OpenAI", segment)
    assert hit["start_time"] == 50.0
    assert hit["end_time"] == 70.0
    assert hit["exact"] is True
