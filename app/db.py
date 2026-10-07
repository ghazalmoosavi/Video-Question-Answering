from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    func,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from pgvector.sqlalchemy import Vector

from app.config import settings
from app import statuses

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    youtube_id = Column(String(20), unique=True, nullable=False, index=True)
    url = Column(Text, nullable=False)
    title = Column(Text)
    channel = Column(Text)
    thumbnail_url = Column(Text)
    duration_seconds = Column(Float)
    transcript_source = Column(String(20))  # "youtube" or "whisper"
    status = Column(String(30), nullable=False, default=statuses.PENDING, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    segments = relationship(
        "TranscriptSegment", back_populates="video", cascade="all, delete-orphan"
    )
    jobs = relationship(
        "ProcessingJob", back_populates="video", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    # Per-word {"word","start","end"} timing, when the source provides it
    # (Whisper always does; YouTube captions generally don't). Enables
    # sub-chunk phrase localization via app.timestamps.locate_phrase_in_words.
    word_timings = Column(JSON, nullable=True)
    embedding = Column(Vector(settings.EMBEDDING_DIM))
    created_at = Column(DateTime, server_default=func.now())

    video = relationship("Video", back_populates="segments")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    youtube_url = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default=statuses.PENDING, index=True)
    progress = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    video = relationship("Video", back_populates="jobs")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if they don't exist yet (the pgvector/pg_trgm
    extensions themselves are created by init_db.sql / docker-compose
    init, not here)."""
    Base.metadata.create_all(bind=engine)
