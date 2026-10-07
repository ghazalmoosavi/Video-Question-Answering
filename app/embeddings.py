from typing import List

from app.config import settings

# Embeddings run locally via sentence-transformers so that indexing a video
# doesn't require an API key or incur cost. Only the final answer-generation
# step (app/llm.py) calls out to an LLM API.
#
# NOTE: keeping the existing model (all-MiniLM-L6-v2 / 384-dim) as-is per
# requirements — there's no indication it's causing quality issues, and
# swapping it would require re-embedding every stored segment and a
# migration of the pgvector column dimension.

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def embed_texts(texts: List[str], batch_size: int = None) -> List[List[float]]:
    """Embed a list of texts in batches (keeps memory/latency predictable
    for long transcripts with many chunks)."""
    if not texts:
        return []
    batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
    model = _get_model()

    vectors: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_vectors = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        vectors.extend(v.tolist() for v in batch_vectors)
    return vectors


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
