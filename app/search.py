import re
from typing import Dict, List
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import TranscriptSegment
from app.embeddings import embed_query
from app.config import settings
from app.timestamps import normalize_text, locate_phrase_in_segment

# Heuristics for query intent, shared by /search and /ask.
FIND_ALL_KEYWORDS = [
    "every time",
    "all mentions",
    "each time",
    "every mention",
    "how many times",
    "list all",
    "all the times",
    "every occurrence",
    "find every",
    "find all",
]


def is_find_all_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in FIND_ALL_KEYWORDS)


def is_exact_phrase_query(query: str) -> bool:
    """A query is treated as an exact phrase when it's quoted, e.g.
    `"open ai"`, or when the user's intent is clearly to find literal
    occurrences of a short term (handled by the find-all path instead, so
    here we only need to catch explicit quoting)."""
    q = query.strip()
    return (q.startswith('"') and q.endswith('"') and len(q) > 2) or (
        q.startswith("'") and q.endswith("'") and len(q) > 2
    )


def _strip_quotes(query: str) -> str:
    q = query.strip()
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'":
        return q[1:-1].strip()
    return q


def _segment_to_dict(seg: TranscriptSegment) -> Dict:
    return {
        "id": seg.id,
        "video_id": seg.video_id,
        "start_time": seg.start_time,
        "end_time": seg.end_time,
        "text": seg.text,
        "word_timings": seg.word_timings,
    }


def semantic_search(db: Session, video_id: int, query: str, top_k: int = 5) -> List[Dict]:
    """Cosine-similarity nearest-neighbor search via pgvector."""
    query_vector = embed_query(query)
    rows = (
        db.query(
            TranscriptSegment,
            TranscriptSegment.embedding.cosine_distance(query_vector).label("distance"),
        )
        .filter(TranscriptSegment.video_id == video_id)
        .order_by("distance")
        .limit(top_k)
        .all()
    )
    results = []
    for seg, distance in rows:
        d = _segment_to_dict(seg)
        d["score"] = max(0.0, 1.0 - float(distance))
        d["match_type"] = "semantic"
        results.append(d)
    return results


def text_search(db: Session, video_id: int, query: str, limit: int = 5) -> List[Dict]:
    """Keyword / lexical search: exact case-insensitive substring match
    first (highest precision for names, product terms, exact phrases),
    ranked by trigram similarity as a tiebreaker."""
    clean_query = _strip_quotes(query)
    like_query = f"%{clean_query}%"

    similarity = func.similarity(TranscriptSegment.text, clean_query)
    rows = (
        db.query(TranscriptSegment, similarity.label("sim"))
        .filter(TranscriptSegment.video_id == video_id)
        .filter(TranscriptSegment.text.ilike(like_query))
        .order_by(similarity.desc())
        .limit(limit)
        .all()
    )
    results = []
    for seg, sim in rows:
        d = _segment_to_dict(seg)
        d["score"] = float(sim) if sim is not None else 1.0
        d["match_type"] = "keyword"
        results.append(d)
    return results


def trigram_search(db: Session, video_id: int, query: str, limit: int = 5, min_similarity: float = 0.15) -> List[Dict]:
    """Fuzzy lexical search via pg_trgm similarity — catches near-matches
    (typos, slightly different phrasing) that a strict ILIKE would miss."""
    clean_query = _strip_quotes(query)
    similarity = func.similarity(TranscriptSegment.text, clean_query)
    rows = (
        db.query(TranscriptSegment, similarity.label("sim"))
        .filter(TranscriptSegment.video_id == video_id)
        .filter(similarity > min_similarity)
        .order_by(similarity.desc())
        .limit(limit)
        .all()
    )
    results = []
    for seg, sim in rows:
        d = _segment_to_dict(seg)
        d["score"] = float(sim)
        d["match_type"] = "fuzzy"
        results.append(d)
    return results


def hybrid_search(db: Session, video_id: int, query: str, top_k: int = 5) -> List[Dict]:
    """Combine keyword + fuzzy lexical matches (high precision) with
    semantic matches (high recall), de-duplicated by segment id.

    Exact-phrase queries (quoted, e.g. `"open ai"`) put lexical matches
    first and give them full priority over semantic results.
    """
    exact = is_exact_phrase_query(query)

    keyword = text_search(db, video_id, query, limit=top_k)
    fuzzy = trigram_search(db, video_id, query, limit=top_k) if not keyword else []
    semantic = semantic_search(db, video_id, query, top_k=top_k)

    ordered_sources = [keyword, fuzzy, semantic] if exact else [keyword, semantic, fuzzy]

    seen_ids = set()
    combined: List[Dict] = []
    for source in ordered_sources:
        for item in source:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                combined.append(item)

    limit = top_k if not exact else max(top_k, len(keyword))
    return combined[:limit]


def find_all_occurrences(
    db: Session,
    video_id: int,
    phrase: str,
    dedup_window_seconds: float = None,
    wide_top_k: int = None,
) -> List[Dict]:
    """Retrieve every distinct occurrence of `phrase` in a video, precisely
    localized (word-level when available), deduplicated when multiple
    matches fall within `dedup_window_seconds` of each other (the same
    mention often spans/duplicates across adjacent chunks).
    """
    dedup_window_seconds = dedup_window_seconds or settings.FIND_ALL_DEDUP_WINDOW_SECONDS
    wide_top_k = wide_top_k or settings.FIND_ALL_TOP_K
    clean_phrase = _strip_quotes(phrase)

    keyword_hits = text_search(db, video_id, clean_phrase, limit=wide_top_k)
    semantic_hits = semantic_search(db, video_id, clean_phrase, top_k=wide_top_k)

    seen_ids = set()
    candidates: List[Dict] = []
    for hit in keyword_hits + semantic_hits:
        if hit["id"] in seen_ids:
            continue
        seen_ids.add(hit["id"])
        # Only keep candidates that plausibly contain the phrase (lexical
        # match, or a normalized substring match on semantic hits) — a
        # find-all query should return literal mentions, not "related" text.
        if normalize_text(clean_phrase) in normalize_text(hit["text"]):
            candidates.append(hit)

    localized = []
    for hit in candidates:
        loc = locate_phrase_in_segment(clean_phrase, hit)
        localized.append({**hit, **loc})

    localized.sort(key=lambda h: h["start_time"])

    deduped: List[Dict] = []
    for item in localized:
        if deduped and item["start_time"] - deduped[-1]["start_time"] < dedup_window_seconds:
            continue
        deduped.append(item)

    return deduped
