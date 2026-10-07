# YouTube AI Search — Backend

A modular FastAPI backend that turns a YouTube URL into a searchable,
askable, timestamp-accurate transcript: captions or Whisper fallback ->
semantic chunking -> local embeddings -> pgvector -> hybrid search ->
grounded LLM answers with citations mapped back to real timestamps.

Backend/API only — no frontend, no UI.

## Architecture

```
POST /videos  ──►  creates Video + ProcessingJob (PENDING)  ──►  returns immediately (202)
                                     │
                                     ▼
                     python -m workers.video_processor
                     (polls processing_jobs for PENDING, one at a time)
                                     │
   PENDING → FETCHING_METADATA → FETCHING_TRANSCRIPT
             → [DOWNLOADING_AUDIO → TRANSCRIBING]   (only if no captions)
             → CHUNKING → EMBEDDING → INDEXING → READY  (or FAILED)
```

### Modules (`app/`)

| Module | Responsibility |
|---|---|
| `youtube.py` | Parse any YouTube URL (watch/youtu.be/shorts/embed/live) → video ID. Fetch title/channel/thumbnail/duration via `yt-dlp`. Fetch official captions via `youtube-transcript-api`; if unavailable, download audio and transcribe with `faster-whisper`, requesting **word-level timestamps**. |
| `chunking.py` | Merge fine-grained caption/Whisper lines into ~300–700 char / 20–45s semantic chunks, breaking near sentence boundaries, while preserving each chunk's timestamps and concatenated word-timing data. |
| `timestamps.py` | Single source of truth for timestamp formatting (`MM:SS` / `HH:MM:SS`), text normalization, and **exact phrase localization** — finds the precise start/end of a phrase inside word-level timing data (exact token match, with a fuzzy fallback for ASR noise), not just the chunk it's in. |
| `embeddings.py` | Local `sentence-transformers` embeddings, generated in batches (`EMBEDDING_BATCH_SIZE`). Free, no API key. |
| `db.py` | SQLAlchemy models: `Video`, `TranscriptSegment` (with `word_timings` JSON + `pgvector` embedding column), `ProcessingJob`. |
| `search.py` | `text_search` (ILIKE + trigram ranking), `trigram_search` (fuzzy lexical via `pg_trgm`), `semantic_search` (pgvector cosine similarity), `hybrid_search` (merges all three, de-duped; exact-phrase/quoted queries prioritize lexical matches), `find_all_occurrences` (wide retrieval + precise per-occurrence localization + overlap dedup for "every time X is mentioned" queries). |
| `llm.py` | Calls the LLM in **JSON mode**, requesting `{"answer", "citations":[{"timestamp","text","segment_id"}]}`, and validates the shape with Pydantic. |
| `rag.py` | Retrieves grounding evidence (hybrid or find-all, depending on query intent), calls `llm.py`, then **validates every citation against the segments actually retrieved** — a citation pointing at a `segment_id` we didn't retrieve is dropped, and every surviving citation's timestamp is overwritten with the real stored `start_time`, never trusting whatever the model returned. |
| `main.py` | FastAPI routes (below). |
| `statuses.py` | Shared status-string constants for `ProcessingJob`/`Video`. |
| `workers/video_processor.py` | The background worker (`python -m workers.video_processor`): polls `processing_jobs` for the oldest `PENDING` row (claimed via `SELECT ... FOR UPDATE SKIP LOCKED`, so it's safe to run more than one worker process), and walks it through every pipeline step, persisting status/progress/error at each step. |

## API

| Endpoint | Purpose |
|---|---|
| `POST /videos` | Validate URL, create/reuse `Video`, enqueue a `ProcessingJob`. Returns **immediately** (202) with `video_id` + `job`. Idempotent: a `READY` video isn't re-queued; an in-flight job isn't duplicated. |
| `GET /videos/{video_id}` | Video metadata + current status + latest job (status/progress/error). |
| `GET /videos/{video_id}/transcript` | Full stored transcript, timestamps as `{seconds, formatted}`. |
| `POST /videos/{video_id}/retry` | Re-queue a `FAILED` (or completed) video for reprocessing. 409 if a job is already in flight. |
| `POST /search` | Raw retrieval (`semantic` / `text` / `hybrid`), no LLM call — returns `segment_id`, timestamps, text, `score`, `match_type`. |
| `POST /ask` | Full RAG: retrieves evidence, asks the LLM for a structured JSON answer, validates/maps citations to real timestamps. Handles both normal questions and "find every mention of X" queries. 409 if the video isn't `READY` yet. |

## Setup

```bash
docker compose up -d                      # Postgres + pgvector + pg_trgm
pip install -r requirements.txt           # requires ffmpeg on PATH for Whisper fallback
cp .env.example .env                      # then set OPENAI_API_KEY
uvicorn app.main:app --reload             # API on :8000
python -m workers.video_processor         # run in a second terminal — does the actual work
```

Then open `requests.http` in VS Code (REST Client extension) and step
through: queue a video, poll its status until `READY`, then hit `/search`
and `/ask`.

## Design notes

- **No message broker.** Per the project's scope this is a simple
  single-table DB-polling worker, not Celery/Redis — `processing_jobs` rows
  are claimed with `SELECT ... FOR UPDATE SKIP LOCKED` so multiple worker
  processes can safely run side by side if you need more throughput.
- **Timestamp precision is prioritized everywhere.** Whisper is asked for
  word-level timestamps (`word_timestamps=True`); YouTube captions are
  line-level only, so phrase lookups on those fall back to chunk-level
  timestamps (still accurate to the ~20–45s chunk, just not word-precise).
  `find_all_occurrences` re-localizes every candidate against word timing
  data when available, rather than trusting the chunk's start time.
- **Citations are never trusted blindly.** The LLM is asked to cite a
  `segment_id` it was given in context; `rag.py` looks that segment up in
  what was actually retrieved and substitutes the *real* stored
  `start_time`. Any citation referencing a `segment_id` not in the
  retrieved set is silently dropped rather than surfaced to the user.
- **Errors are sanitized.** The worker never stores a raw stack trace or a
  string containing `sk-`/`Bearer ` in `processing_jobs.error`; the API
  never returns a stack trace to the client (a global `SQLAlchemyError`
  handler and per-route try/except keep responses generic).
- **Embedding model unchanged** (`all-MiniLM-L6-v2`, 384-dim) — swapping it
  would require re-embedding every stored segment and a pgvector column
  migration, and there's no indication of a quality problem with it.

## Tests

```bash
pytest tests/ -v
```

Covers (all pure-logic, external services mocked/not required): YouTube URL
parsing across watch/youtu.be/shorts/embed/live formats, timestamp
formatting (`1421s → "23:41"`, `3725s → "01:02:05"`), text normalization,
exact + fuzzy phrase localization against word-timing data, chunking
(size/duration bounds, sentence-boundary splitting, word-timing
preservation), find-all/exact-phrase query detection, structured LLM JSON
output parsing/validation, and RAG citation validation (fabricated/
hallucinated timestamps and segment IDs are proven to be rejected).

**What was *not* tested end-to-end** (this sandbox has no live Postgres, no
network access to YouTube/OpenAI, and the heavy ML libraries —
`sentence-transformers`, `faster-whisper` — were stubbed out for import
testing rather than installed): the real DB read/write path, real caption
fetching, real Whisper transcription, and real OpenAI calls. Run the
commands under Setup locally to exercise those.
