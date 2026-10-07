from app.search import is_find_all_query, is_exact_phrase_query, _strip_quotes


def test_find_all_detection_positive():
    for q in [
        "Find every time they mention OpenAI",
        "list all the times he talks about funding",
        "How many times do they say Python?",
        "give me all mentions of GPT-4",
    ]:
        assert is_find_all_query(q) is True


def test_find_all_detection_negative():
    for q in [
        "What do they say about AI replacing programmers?",
        "Summarize the video",
        "When does he mention OpenAI?",
    ]:
        assert is_find_all_query(q) is False


def test_exact_phrase_detection():
    assert is_exact_phrase_query('"open ai"') is True
    assert is_exact_phrase_query("'gpt-4'") is True
    assert is_exact_phrase_query("open ai") is False
    assert is_exact_phrase_query('"') is False


def test_strip_quotes():
    assert _strip_quotes('"open ai"') == "open ai"
    assert _strip_quotes("open ai") == "open ai"
    assert _strip_quotes("'gpt-4'") == "gpt-4"
