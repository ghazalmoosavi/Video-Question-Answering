
import logging
from typing import List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db, init_db, Video, TranscriptSegment, ProcessingJob
from app import schemas, statuses
from app.config import settings
from app.youtube import extract_video_id, InvalidYouTubeURLError
from app.search import semantic_search, text_search, hybrid_search, is_find_all_query
from app.rag import answer_question
from app.timestamps import format_timestamp, timestamp_pair

logger = logging.getLogger("youtube_ai_search")

app = FastAPI(
    title="YouTube AI Search — Core Pipeline",
    description=(
        "YouTube URL -> background processing -> transcript -> timestamps -> "
        "semantic/hybrid search -> grounded LLM answer with real timestamps. "
        "Backend/API only, no UI."
    ),
    version="0.2.0",
)

# CORS
# Frontend runs on localhost:3000 or localhost:3001.
# This allows the browser to send requests from the Next.js frontend
# to the FastAPI backend running on localhost:8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.exception_handler(SQLAlchemyError)
def db_error_handler(request, exc):
    logger.exception("Database error")
    return JSONResponse(
        status_code=500,
        content={"detail": "A database error occurred."},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


def _job_out(job: ProcessingJob) -> schemas.JobOut:
    return schemas.JobOut(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        error=job.error,
    )


def _job_in_flight(job: ProcessingJob) -> bool:
    return job is not None and job.status not in statuses.TERMINAL_STATUSES


@app.post(
    "/videos",
    response_model=schemas.ProcessVideoResponse,
    status_code=202,
)
def create_video(
    payload: schemas.ProcessVideoRequest,
    db: Session = Depends(get_db),
):
    """Validate the URL, create/reuse the Video row, and enqueue a
    ProcessingJob for the background worker."""

    try:
        youtube_id = extract_video_id(payload.youtube_url)
    except InvalidYouTubeURLError as e:
        raise HTTPException(status_code=422, detail=str(e))

    video = (
        db.query(Video)
        .filter(Video.youtube_id == youtube_id)
        .first()
    )

    if video:
        latest_job = (
            db.query(ProcessingJob)
            .filter(ProcessingJob.video_id == video.id)
            .order_by(ProcessingJob.id.desc())
            .first()
        )

        if video.status == statuses.READY:
            return schemas.ProcessVideoResponse(
                video_id=video.id,
                youtube_id=video.youtube_id,
                status=video.status,
                job=(
                    _job_out(latest_job)
                    if latest_job
                    else schemas.JobOut(
                        job_id=0,
                        status=statuses.READY,
                        progress=100,
                    )
                ),
                message=(
                    "Video already processed. Use /search or /ask directly, "
                    "or POST /videos/{video_id}/retry to reprocess."
                ),
            )

        if _job_in_flight(latest_job):
            return schemas.ProcessVideoResponse(
                video_id=video.id,
                youtube_id=video.youtube_id,
                status=video.status,
                job=_job_out(latest_job),
                message="Processing is already in progress for this video.",
            )

    else:
        video = Video(
            youtube_id=youtube_id,
            url=payload.youtube_url,
            status=statuses.PENDING,
        )
        db.add(video)
        db.flush()

    job = ProcessingJob(
        video_id=video.id,
        youtube_url=payload.youtube_url,
        status=statuses.PENDING,
        progress=0,
    )

    video.status = statuses.PENDING

    db.add(job)
    db.commit()

    db.refresh(job)
    db.refresh(video)

    return schemas.ProcessVideoResponse(
        video_id=video.id,
        youtube_id=video.youtube_id,
        status=video.status,
        job=_job_out(job),
        message=(
            "Video queued for processing. Run "
            "`python -m workers.video_processor` and poll "
            "GET /videos/{video_id} for status."
        ),
    )


@app.post(
    "/videos/{video_id}/retry",
    response_model=schemas.RetryResponse,
)
def retry_video(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = (
        db.query(Video)
        .filter(Video.id == video_id)
        .first()
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found",
        )

    latest_job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.video_id == video.id)
        .order_by(ProcessingJob.id.desc())
        .first()
    )

    if _job_in_flight(latest_job):
        raise HTTPException(
            status_code=409,
            detail="Processing is already in progress for this video.",
        )

    job = ProcessingJob(
        video_id=video.id,
        youtube_url=video.url,
        status=statuses.PENDING,
        progress=0,
    )

    video.status = statuses.PENDING

    db.add(job)
    db.commit()
    db.refresh(job)

    return schemas.RetryResponse(
        video_id=video.id,
        job=_job_out(job),
        message="Reprocessing queued.",
    )


@app.get(
    "/videos/{video_id}",
    response_model=schemas.VideoInfo,
)
def get_video(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = (
        db.query(Video)
        .filter(Video.id == video_id)
        .first()
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found",
        )

    num_segments = (
        db.query(TranscriptSegment)
        .filter(
            TranscriptSegment.video_id == video_id
        )
        .count()
    )

    latest_job = (
        db.query(ProcessingJob)
        .filter(
            ProcessingJob.video_id == video_id
        )
        .order_by(ProcessingJob.id.desc())
        .first()
    )

    return schemas.VideoInfo(
        id=video.id,
        youtube_id=video.youtube_id,
        url=video.url,
        title=video.title,
        channel=video.channel,
        thumbnail_url=video.thumbnail_url,
        duration_seconds=video.duration_seconds,
        transcript_source=video.transcript_source,
        status=video.status,
        num_segments=num_segments,
        latest_job=(
            _job_out(latest_job)
            if latest_job
            else None
        ),
    )


@app.get(
    "/videos/{video_id}/transcript",
    response_model=List[schemas.TranscriptSegmentOut],
)
def get_transcript_for_video(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = (
        db.query(Video)
        .filter(Video.id == video_id)
        .first()
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found",
        )

    segments = (
        db.query(TranscriptSegment)
        .filter(
            TranscriptSegment.video_id == video_id
        )
        .order_by(TranscriptSegment.start_time)
        .all()
    )

    if not segments:
        detail = (
            "No transcript found for this video."
            if video.status == statuses.READY
            else (
                f"Video is still processing "
                f"(status={video.status})."
            )
        )

        raise HTTPException(
            status_code=404,
            detail=detail,
        )

    return [
        schemas.TranscriptSegmentOut(
            segment_id=s.id,
            start_time=schemas.TimestampOut(
                **timestamp_pair(s.start_time)
            ),
            end_time=schemas.TimestampOut(
                **timestamp_pair(s.end_time)
            ),
            text=s.text,
            has_word_timings=bool(s.word_timings),
        )
        for s in segments
    ]


@app.post(
    "/search",
    response_model=schemas.SearchResponse,
)
def search(
    payload: schemas.SearchRequest,
    db: Session = Depends(get_db),
):
    """Raw retrieval endpoint."""

    video = (
        db.query(Video)
        .filter(Video.id == payload.video_id)
        .first()
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found",
        )

    if payload.mode not in (
        "semantic",
        "text",
        "hybrid",
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "mode must be 'semantic', "
                "'text', or 'hybrid'"
            ),
        )

    if payload.mode == "semantic":
        results = semantic_search(
            db,
            payload.video_id,
            payload.query,
            top_k=payload.top_k,
        )

    elif payload.mode == "text":
        results = text_search(
            db,
            payload.video_id,
            payload.query,
            limit=payload.top_k,
        )

    else:
        results = hybrid_search(
            db,
            payload.video_id,
            payload.query,
            top_k=payload.top_k,
        )

    return schemas.SearchResponse(
        query=payload.query,
        mode=payload.mode,
        results=[
            schemas.SearchResultItem(
                segment_id=r["id"],
                start_time=schemas.TimestampOut(
                    **timestamp_pair(r["start_time"])
                ),
                end_time=schemas.TimestampOut(
                    **timestamp_pair(r["end_time"])
                ),
                text=r["text"],
                score=r["score"],
                match_type=r["match_type"],
            )
            for r in results
        ],
    )


@app.post(
    "/ask",
    response_model=schemas.AskResponse,
)
def ask(
    payload: schemas.AskRequest,
    db: Session = Depends(get_db),
):
    """Full RAG endpoint."""

    video = (
        db.query(Video)
        .filter(Video.id == payload.video_id)
        .first()
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found",
        )

    if video.status != statuses.READY:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Video is not ready yet "
                f"(status={video.status}). "
                "Wait for processing to complete "
                "before asking questions."
            ),
        )

    try:
        result = answer_question(
            db,
            payload.video_id,
            payload.question,
            top_k=payload.top_k,
        )

    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

    except Exception:
        logger.exception(
            "Unhandled error answering question"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to generate an answer.",
        )

    return schemas.AskResponse(
        question=payload.question,
        answer=result["answer"],
        is_find_all=result["is_find_all"],
        citations=[
            schemas.CitationOut(
                segment_id=c["segment_id"],
                start_time=schemas.TimestampOut(
                    **c["start_time"]
                ),
                text=c["text"],
            )
            for c in result["citations"]
        ],
    )

