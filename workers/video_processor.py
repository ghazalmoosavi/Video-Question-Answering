"""Background worker for the YouTube AI Search ingestion pipeline.

Run with:
    python -m workers.video_processor

Polls the processing_jobs table for the oldest PENDING job, claims it, and
walks it through the full pipeline:

    PENDING -> FETCHING_METADATA -> FETCHING_TRANSCRIPT
             -> [DOWNLOADING_AUDIO -> TRANSCRIBING]   (only if no captions)
             -> CHUNKING -> EMBEDDING -> INDEXING -> READY

Any exception at any step marks the job (and video) FAILED with a sanitized
error message (no stack traces, no secrets) and leaves the job available
for POST /videos/{video_id}/retry.

This is intentionally a simple single-process DB-polling worker (no
Celery/Redis) per the project's scope — it claims one job at a time via an
atomic UPDATE ... WHERE status = 'PENDING' so multiple worker processes
could run safely side by side, but there's no separate broker to operate.
"""
import logging
import time
import traceback

from sqlalchemy import update

from app.config import settings
from app import statuses
from app.db import SessionLocal, Video, TranscriptSegment, ProcessingJob, init_db
from app.youtube import get_video_metadata, get_transcript
from app.chunking import chunk_segments
from app.embeddings import embed_texts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("video_processor")


def _sanitize_error(exc: Exception) -> str:
    """Return a short, safe error message — never a raw stack trace or
    anything that might contain an API key."""
    message = str(exc).strip() or exc.__class__.__name__
    # Defensively strip anything that looks like a bearer/API key.
    for marker in ("sk-", "Bearer "):
        idx = message.find(marker)
        if idx != -1:
            message = message[:idx] + "[redacted]"
    return message[:500]


def _claim_next_job(db) -> "ProcessingJob | None":
    """Atomically claim the oldest PENDING job so multiple worker
    processes don't double-process the same video."""
    job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status == statuses.PENDING)
        .order_by(ProcessingJob.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None
    job.status = statuses.FETCHING_METADATA
    job.progress = statuses.PROGRESS_BY_STATUS[statuses.FETCHING_METADATA]
    job.attempts = (job.attempts or 0) + 1
    db.commit()
    db.refresh(job)
    return job


def _set_status(db, job: ProcessingJob, video: Video, status: str, error: str = None) -> None:
    job.status = status
    job.progress = statuses.PROGRESS_BY_STATUS.get(status, job.progress)
    job.error = error
    video.status = status
    db.commit()


def process_job(db, job: ProcessingJob) -> None:
    video = db.query(Video).filter(Video.id == job.video_id).first()
    if video is None:
        logger.error("Job %s references missing video_id=%s", job.id, job.video_id)
        job.status = statuses.FAILED
        job.error = "Video record missing."
        db.commit()
        return

    logger.info("Processing job %s for video %s (%s)", job.id, video.id, video.youtube_id)

    try:
        # --- FETCHING_METADATA ---
        _set_status(db, job, video, statuses.FETCHING_METADATA)
        meta = get_video_metadata(video.youtube_id)
        video.title = meta.get("title")
        video.channel = meta.get("channel")
        video.thumbnail_url = meta.get("thumbnail_url")
        video.duration_seconds = meta.get("duration")
        db.commit()

        # --- FETCHING_TRANSCRIPT / DOWNLOADING_AUDIO / TRANSCRIBING ---
        def on_step(step):
            _set_status(db, job, video, step)

        result = get_transcript(video.url, settings, on_step=on_step)
        video.transcript_source = result["source"]
        db.commit()

        # --- CHUNKING ---
        _set_status(db, job, video, statuses.CHUNKING)
        chunks = chunk_segments(result["segments"])
        if not chunks:
            raise RuntimeError("Transcript produced no usable chunks.")

        # --- EMBEDDING ---
        _set_status(db, job, video, statuses.EMBEDDING)
        texts = [c["text"] for c in chunks]
        vectors = embed_texts(texts, batch_size=settings.EMBEDDING_BATCH_SIZE)

        # --- INDEXING ---
        _set_status(db, job, video, statuses.INDEXING)
        db.query(TranscriptSegment).filter(TranscriptSegment.video_id == video.id).delete()
        for chunk, vector in zip(chunks, vectors):
            db.add(
                TranscriptSegment(
                    video_id=video.id,
                    start_time=float(chunk["start"]),
                    end_time=float(chunk["end"]),
                    text=chunk["text"],
                    word_timings=chunk.get("words") or None,
                    embedding=vector,
                )
            )
        db.commit()

        # --- READY ---
        _set_status(db, job, video, statuses.READY)
        logger.info("Job %s complete: %d segments indexed for video %s", job.id, len(chunks), video.id)

    except Exception as exc:  # noqa: BLE001 - top-level job guard, must not crash the worker loop
        db.rollback()
        logger.error("Job %s failed: %s", job.id, exc)
        logger.debug("Traceback for job %s:\n%s", job.id, traceback.format_exc())
        
        job.status = statuses.FAILED
        job.error = _sanitize_error(exc)
        video.status = statuses.FAILED
        db.commit()


def run_once() -> bool:
    """Claim and process a single job. Returns True if a job was found."""
    db = SessionLocal()
    try:
        job = _claim_next_job(db)
        if job is None:
            return False
        process_job(db, job)
        return True
    finally:
        db.close()


def main():
    init_db()
    logger.info(
        "Worker started. Polling every %ss for PENDING jobs. Ctrl+C to stop.",
        settings.WORKER_POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            found = run_once()
        except Exception:
            logger.exception("Unexpected error in worker loop; continuing.")
            found = False
        if not found:
            time.sleep(settings.WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
