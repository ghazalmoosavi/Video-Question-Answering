import pytest
from app.llm import parse_structured_answer, LLMAnswer


def test_parse_valid_json():
    raw = '{"answer": "They discuss OpenAI at 23:41.", "citations": [{"timestamp": 1421, "text": "...", "segment_id": 7}]}'
    result = parse_structured_answer(raw)
    assert isinstance(result, LLMAnswer)
    assert result.answer.startswith("They discuss")
    assert result.citations[0].segment_id == 7
    assert result.citations[0].timestamp == 1421


def test_parse_strips_markdown_fences():
    raw = '```json\n{"answer": "Hi", "citations": []}\n```'
    result = parse_structured_answer(raw)
    assert result.answer == "Hi"
    assert result.citations == []


def test_parse_converts_mmss_timestamp_string():
    raw = '{"answer": "x", "citations": [{"timestamp": "23:41", "text": "y", "segment_id": 1}]}'
    result = parse_structured_answer(raw)
    assert result.citations[0].timestamp == 1421.0


def test_parse_invalid_json_raises_value_error():
    with pytest.raises(ValueError):
        parse_structured_answer("not json at all")


def test_parse_missing_required_field_raises():
    with pytest.raises(ValueError):
        parse_structured_answer('{"citations": []}')


def test_parse_defaults_missing_citations_to_empty_list():
    result = parse_structured_answer('{"answer": "no citations needed"}')
    assert result.citations == []
