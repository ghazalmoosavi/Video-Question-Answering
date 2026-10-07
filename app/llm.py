import json
from typing import Dict, List, Optional

import requests
from pydantic import BaseModel, ValidationError

from app.timestamps import format_timestamp


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3:4b"


class LLMCitation(BaseModel):
    timestamp: float
    text: str
    segment_id: Optional[int] = None
    quote: Optional[str] = None


class LLMAnswer(BaseModel):
    answer: str
    citations: List[LLMCitation] = []


def build_context(segments: List[Dict]) -> str:
    """
    Convert retrieved transcript segments into labeled context
    that the local LLM can cite.
    """
    lines = []

    for seg in segments:
        ts = format_timestamp(seg["start_time"])

        lines.append(
            f"[segment_id={seg['id']}] "
            f"[{ts}] "
            f"{seg['text']}"
        )

    return "\n".join(lines)


SYSTEM_PROMPT = """You are an assistant that answers questions about a YouTube
video using ONLY the transcript excerpts provided by the user.

Rules:

1. Use ONLY information contained in the transcript excerpts.

2. If the answer cannot be determined from the excerpts, say that clearly
in the answer and return an empty citations list.

3. Every factual claim must have at least one citation.

4. Never invent a segment_id.

5. Never invent a timestamp.

6. The timestamp must correspond to the cited segment.

7. For every citation, include:
   - timestamp: timestamp in seconds as a number
   - segment_id: the exact segment_id
   - text: the transcript text of that segment
   - quote: a short exact phrase copied from that transcript

8. Return ONLY valid JSON.

The JSON must have exactly this general structure:

{
  "answer": "your answer",
  "citations": [
    {
      "timestamp": 12.5,
      "text": "transcript text",
      "segment_id": 123,
      "quote": "exact phrase from transcript"
    }
  ]
}
"""


def _mm_ss_to_seconds(ts) -> float:
    """
    Convert timestamps such as:
    12
    12.5
    01:23
    01:02:03
    into seconds.
    """

    if isinstance(ts, (int, float)):
        return float(ts)

    try:
        parts = [float(p) for p in str(ts).split(":")]
    except (ValueError, TypeError):
        return 0.0

    seconds = 0.0

    for p in parts:
        seconds = seconds * 60 + p

    return seconds


def _parse_llm_json(raw: str) -> Dict:
    """
    Parse JSON returned by Ollama.

    Also handles accidental markdown code fences.
    """

    if not raw:
        raise ValueError("Ollama returned an empty response.")

    cleaned = raw.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)

    except json.JSONDecodeError as e:
        raise ValueError(
            f"Ollama did not return valid JSON: {e}\n"
            f"Raw response: {cleaned[:1000]}"
        ) from e


def parse_structured_answer(raw: str) -> LLMAnswer:
    """
    Validate Ollama's JSON response against our Pydantic model.
    """

    data = _parse_llm_json(raw)

    if "citations" in data and isinstance(data["citations"], list):

        for citation in data["citations"]:

            if "timestamp" in citation:
                citation["timestamp"] = _mm_ss_to_seconds(
                    citation["timestamp"]
                )

    try:
        return LLMAnswer.model_validate(data)

    except ValidationError as e:
        raise ValueError(
            f"Ollama returned an unexpected JSON structure: {e}"
        ) from e


def _call_ollama(
    question: str,
    context: str,
    instruction: str,
) -> str:

    user_prompt = f"""Transcript excerpts:

{context}

Question:
{question}

Instruction:
{instruction}

Return ONLY valid JSON.
"""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "stream": False,
        
        "options": {
            "temperature": 0.1,
        },
    }

    try:

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=500,
        )

    except requests.RequestException as e:

        raise RuntimeError(
            f"Could not connect to Ollama: {type(e).__name__}: {e}"
        ) from e

    if response.status_code != 200:

        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    try:
        data = response.json()

    except ValueError as e:

        raise RuntimeError(
            f"Ollama returned invalid JSON: {response.text[:1000]}"
        ) from e

    message = data.get("message", {})

    content = message.get("content")

    if not content:

        raise RuntimeError(
            f"Ollama response did not contain message.content: {data}"
        )

    return content


def generate_answer(
    question: str,
    segments: List[Dict],
    multi: bool = False,
) -> LLMAnswer:

    if not segments:

        return LLMAnswer(
            answer="I could not find relevant transcript excerpts.",
            citations=[],
        )

    context = build_context(segments)

    if multi:

        instruction = (
            "This is a find-all query. "
            "List every distinct relevant occurrence, "
            "one citation per occurrence, in chronological order."
        )

    else:

        instruction = (
            "Give a concise answer. "
            "Use the single most relevant segment when possible. "
            "Use multiple citations only when genuinely necessary."
        )

    raw = _call_ollama(
        question=question,
        context=context,
        instruction=instruction,
    )

    return parse_structured_answer(raw)