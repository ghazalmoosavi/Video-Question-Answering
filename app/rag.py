from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.search import hybrid_search, find_all_occurrences, is_find_all_query
from app.llm import generate_answer, LLMAnswer
from app.timestamps import timestamp_pair, locate_phrase_in_segment, normalize_text
from app.config import settings


def _pinpoint_timestamp(real_segment: Dict, quote: Optional[str]) -> Dict:
    """A retrieved chunk can span up to ~45s. If the LLM gave us the exact
    quoted phrase it based the claim on, localize *that* within the
    segment (word-level precision when available) instead of returning
    the chunk's start — this is the core "23:41, not 23:00" requirement.
    """
    if not quote or not quote.strip():
        return timestamp_pair(real_segment["start_time"])

    # Only trust the quote if it's actually present in this segment's text
    # (word-boundary-safe check) — otherwise the model may have mixed up
    # which excerpt a quote came from, and we fall back to chunk start.
    if normalize_text(quote) not in normalize_text(real_segment["text"]):
        return timestamp_pair(real_segment["start_time"])

    located = locate_phrase_in_segment(quote, real_segment)
    return timestamp_pair(located["start_time"])


def answer_question(
    db: Session, video_id: int, question: str, top_k: Optional[int] = None
) -> Dict:
    """Full RAG flow: retrieve grounding evidence, ask the LLM for a
    structured JSON answer, then validate every citation against the
    segments we actually retrieved — never trust an LLM-generated
    timestamp, always map back to the real stored one.
    """
    multi = is_find_all_query(question)

    if multi:
        segments = find_all_occurrences(db, video_id, question)
        if not segments:
            # The literal-phrase pass found nothing; fall back to a wide
            # semantic retrieval so the model can still try to help.
            segments = hybrid_search(db, video_id, question, top_k=settings.FIND_ALL_TOP_K)
    else:
        k = top_k or settings.DEFAULT_TOP_K
        segments = hybrid_search(db, video_id, question, top_k=k)

    if not segments:
        return {
            "answer": "No transcript segments were found for this video. "
            "Has it finished processing? Check GET /videos/{video_id}.",
            "citations": [],
            "is_find_all": multi,
        }

    segments_by_id = {s["id"]: s for s in segments}

    try:
        llm_answer: LLMAnswer = generate_answer(question, segments, multi=multi)
    except RuntimeError:
        raise
    except ValueError as e:
        # Malformed JSON from the model: fail safe with grounding evidence
        # returned as citations, but no fabricated prose answer.
        return {
            "answer": f"The model's response could not be parsed reliably ({e}). "
            "Here are the most relevant transcript segments instead.",
            "citations": [
                {
                    "start_time": timestamp_pair(s["start_time"]),
                    "text": s["text"],
                    "segment_id": s["id"],
                }
                for s in segments[: (top_k or settings.DEFAULT_TOP_K)]
            ],
            "is_find_all": multi,
        }

    validated_citations: List[Dict] = []
    for citation in llm_answer.citations:
        real_segment = segments_by_id.get(citation.segment_id)
        if real_segment is None:
            # Drop citations pointing at a segment_id we never retrieved —
            # the LLM cannot be trusted to invent grounding evidence.
            continue
        validated_citations.append(
            {
                "start_time": _pinpoint_timestamp(real_segment, citation.quote),
                "text": real_segment["text"],
                "segment_id": real_segment["id"],
            }
        )

    return {"answer": llm_answer.answer, "citations": validated_citations, "is_find_all": multi}
