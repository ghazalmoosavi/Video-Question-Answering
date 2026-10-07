from unittest.mock import patch
from app.llm import LLMAnswer, LLMCitation
from app import rag


REAL_SEGMENTS = [
    {"id": 1, "video_id": 1, "start_time": 10.0, "end_time": 20.0, "text": "we talked about OpenAI", "word_timings": None},
    {"id": 2, "video_id": 1, "start_time": 1421.0, "end_time": 1440.0, "text": "AI replacing programmers came up", "word_timings": None},
]


def test_citations_mapped_to_real_stored_timestamps():
    fake_llm_answer = LLMAnswer(
        answer="They discuss this around 23:41.",
        citations=[LLMCitation(timestamp=999999.0, text="fabricated wrong time", segment_id=2)],
    )
    with patch("app.rag.hybrid_search", return_value=REAL_SEGMENTS), \
         patch("app.rag.generate_answer", return_value=fake_llm_answer):
        result = rag.answer_question(db=None, video_id=1, question="What do they say about AI replacing programmers?")

    assert len(result["citations"]) == 1
    # The LLM's fabricated timestamp (999999.0) must NOT survive — it's
    # replaced with the real, stored segment start_time.
    assert result["citations"][0]["start_time"]["seconds"] == 1421.0
    assert result["citations"][0]["start_time"]["formatted"] == "23:41"
    assert result["citations"][0]["segment_id"] == 2
    assert result["is_find_all"] is False


def test_citation_pointing_at_unretrieved_segment_is_dropped():
    fake_llm_answer = LLMAnswer(
        answer="Some answer.",
        citations=[
            LLMCitation(timestamp=10.0, text="real", segment_id=1),
            LLMCitation(timestamp=5000.0, text="hallucinated segment", segment_id=999),
        ],
    )
    with patch("app.rag.hybrid_search", return_value=REAL_SEGMENTS), \
         patch("app.rag.generate_answer", return_value=fake_llm_answer):
        result = rag.answer_question(db=None, video_id=1, question="Tell me about OpenAI")

    assert len(result["citations"]) == 1
    assert result["citations"][0]["segment_id"] == 1


def test_find_all_query_uses_find_all_occurrences():
    with patch("app.rag.find_all_occurrences", return_value=REAL_SEGMENTS) as mock_find_all, \
         patch("app.rag.generate_answer", return_value=LLMAnswer(answer="listed", citations=[])):
        result = rag.answer_question(db=None, video_id=1, question="Find every time they mention OpenAI")

    mock_find_all.assert_called_once()
    assert result["is_find_all"] is True


def test_no_segments_returns_helpful_message_without_calling_llm():
    with patch("app.rag.hybrid_search", return_value=[]), \
         patch("app.rag.generate_answer") as mock_generate:
        result = rag.answer_question(db=None, video_id=1, question="anything")

    mock_generate.assert_not_called()
    assert result["citations"] == []
    assert "processing" in result["answer"].lower() or "found" in result["answer"].lower()


def test_malformed_llm_output_falls_back_safely():
    with patch("app.rag.hybrid_search", return_value=REAL_SEGMENTS), \
         patch("app.rag.generate_answer", side_effect=ValueError("bad json")):
        result = rag.answer_question(db=None, video_id=1, question="anything")

    # Falls back to raw retrieved segments as citations rather than crashing.
    assert len(result["citations"]) > 0
    assert all(c["segment_id"] in {1, 2} for c in result["citations"])


def test_citation_pinpointed_to_quoted_phrase_not_chunk_start():
    # Chunk spans 1380-1440 (23:00-24:00); the actual sentence is spoken at 23:41 (1421s).
    # First ~40s of filler speech, then the target phrase starting at 1421s (23:41).
    words = []
    t = 1380.0
    for i in range(80):
        words.append({"word": f"filler{i}", "start": t, "end": t + 0.4})
        t += 0.5
    t = 1421.0
    for w in ["ai", "may", "automate", "a", "significant", "portion", "of", "programming", "work"]:
        words.append({"word": w, "start": t, "end": t + 0.4})
        t += 0.5
    segment = {
        "id": 5, "video_id": 1, "start_time": 1380.0, "end_time": 1440.0,
        "text": "ai may automate a significant portion of programming work",
        "word_timings": words,
    }
    fake_llm_answer = LLMAnswer(
        answer="They discuss this around 23:41.",
        citations=[LLMCitation(
            timestamp=1380.0, text="chunk text", segment_id=5,
            quote="a significant portion of programming",
        )],
    )
    with patch("app.rag.hybrid_search", return_value=[segment]), \
         patch("app.rag.generate_answer", return_value=fake_llm_answer):
        result = rag.answer_question(db=None, video_id=1, question="Where do they talk about AI replacing programmers?")

    ts = result["citations"][0]["start_time"]["seconds"]
    # Must be pinpointed near 23:41 (~1421s), not the chunk start (1380s).
    assert ts > 1400.0
    assert ts != 1380.0


def test_citation_falls_back_to_chunk_start_when_no_quote_given():
    segment = {"id": 5, "video_id": 1, "start_time": 1380.0, "end_time": 1440.0, "text": "some text here", "word_timings": None}
    fake_llm_answer = LLMAnswer(
        answer="x", citations=[LLMCitation(timestamp=1380.0, text="chunk text", segment_id=5, quote=None)]
    )
    with patch("app.rag.hybrid_search", return_value=[segment]), \
         patch("app.rag.generate_answer", return_value=fake_llm_answer):
        result = rag.answer_question(db=None, video_id=1, question="anything")

    assert result["citations"][0]["start_time"]["seconds"] == 1380.0
