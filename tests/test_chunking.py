from app.chunking import chunk_segments


def make_segments(n, start=0.0, gap=2.0, words_per=5, sentence_every=1):
    """Generate n fake caption lines, each a short sentence."""
    segs = []
    t = start
    for i in range(n):
        text = f"this is sentence number {i}."
        segs.append({"start": t, "end": t + gap, "text": text, "words": []})
        t += gap
    return segs


def test_empty_input():
    assert chunk_segments([]) == []


def test_chunks_respect_max_chars():
    # Many short sentences; max_chars should force multiple chunks.
    segs = make_segments(50, gap=1.0)
    chunks = chunk_segments(segs, min_chars=50, max_chars=120, min_seconds=1000, max_seconds=1000)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c["text"]) <= 130  # small slack for boundary sentence


def test_chunks_respect_max_seconds():
    segs = make_segments(50, gap=5.0)
    chunks = chunk_segments(segs, min_chars=10000, max_chars=10000, min_seconds=10, max_seconds=20)
    assert len(chunks) > 1
    for c in chunks:
        assert c["end"] - c["start"] <= 25  # small slack


def test_chunk_preserves_timestamps_and_order():
    segs = make_segments(10, gap=3.0)
    chunks = chunk_segments(segs, min_chars=10, max_chars=1000, min_seconds=5, max_seconds=1000)
    assert chunks[0]["start"] == segs[0]["start"]
    assert chunks[-1]["end"] == segs[-1]["end"]
    # chunks should be in chronological, non-overlapping order
    for a, b in zip(chunks, chunks[1:]):
        assert a["end"] <= b["start"]


def test_chunk_word_timings_preserved():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "hello there.", "words": [{"word": "hello", "start": 0.0, "end": 0.5}, {"word": "there", "start": 0.5, "end": 1.0}]},
        {"start": 2.0, "end": 4.0, "text": "general kenobi.", "words": [{"word": "general", "start": 2.0, "end": 2.5}, {"word": "kenobi", "start": 2.5, "end": 3.0}]},
    ]
    chunks = chunk_segments(segs, min_chars=1000, max_chars=1000, min_seconds=1000, max_seconds=1000)
    assert len(chunks) == 1
    assert len(chunks[0]["words"]) == 4


def test_target_size_around_300_700_chars():
    # Sentences long enough to approach the target window.
    segs = []
    t = 0.0
    for i in range(30):
        text = f"here is a somewhat longer sentence about topic {i} that adds some length."
        segs.append({"start": t, "end": t + 4.0, "text": text, "words": []})
        t += 4.0
    chunks = chunk_segments(segs, min_chars=300, max_chars=700, min_seconds=20, max_seconds=45)
    assert len(chunks) > 1
    for c in chunks[:-1]:  # last chunk may be shorter (leftover)
        assert len(c["text"]) <= 700
