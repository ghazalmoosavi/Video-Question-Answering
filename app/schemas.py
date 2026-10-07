from typing import List, Optional
from pydantic import BaseModel, Field


# ---------- Videos / processing jobs ----------

class ProcessVideoRequest(BaseModel):
    youtube_url: str


class JobOut(BaseModel):
    job_id: int
    status: str
    progress: int
    error: Optional[str] = None


class ProcessVideoResponse(BaseModel):
    video_id: int
    youtube_id: str
    status: str
    job: JobOut
    message: str


class VideoInfo(BaseModel):
    id: int
    youtube_id: str
    url: str
    title: Optional[str]
    channel: Optional[str]
    thumbnail_url: Optional[str]
    duration_seconds: Optional[float]
    transcript_source: Optional[str]
    status: str
    num_segments: int
    latest_job: Optional[JobOut] = None


class RetryResponse(BaseModel):
    video_id: int
    job: JobOut
    message: str


# ---------- Transcript ----------

class TimestampOut(BaseModel):
    seconds: float
    formatted: str


class TranscriptSegmentOut(BaseModel):
    segment_id: int
    start_time: TimestampOut
    end_time: TimestampOut
    text: str
    has_word_timings: bool


# ---------- Search ----------

class SearchRequest(BaseModel):
    video_id: int
    query: str
    top_k: int = 5
    mode: str = Field(default="hybrid", description="'semantic', 'text', or 'hybrid'")


class SearchResultItem(BaseModel):
    segment_id: int
    start_time: TimestampOut
    end_time: TimestampOut
    text: str
    score: float
    match_type: str


class SearchResponse(BaseModel):
    query: str
    mode: str
    results: List[SearchResultItem]


# ---------- Ask (RAG) ----------

class AskRequest(BaseModel):
    video_id: int
    question: str
    top_k: Optional[int] = None


class CitationOut(BaseModel):
    segment_id: Optional[int]
    start_time: TimestampOut
    text: str


class AskResponse(BaseModel):
    question: str
    answer: str
    is_find_all: bool
    citations: List[CitationOut]
