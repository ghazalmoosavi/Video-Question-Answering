# YouTube AI Search & Chat

Paste a YouTube link, then search the video's dialogue or ask any question about it. Every result and every answer comes with clickable timestamps that jump the embedded player to the exact moment.

Everything runs locally and needs no API keys: embeddings, speech-to-text and the LLM all run on your own machine.

```
YouTube URL ─► captions (or Whisper fallback) ─► sentence-aware chunks ─► local embeddings
            ─► pgvector ─► hybrid search ─► grounded LLM answer ─► validated timestamps ─► player seeks
```

## Features

- **Ask anything about a video.** "What did they say about Elon Musk?", "Find every time they discuss startups."
- **Search by quote.** Type part of a dialogue line and get its timestamp.
- **Exact-moment timestamps.** With Whisper transcripts, results point at the phrase itself (23:41), not the start of a 45-second chunk.
- **Grounded answers.** The LLM only sees retrieved transcript excerpts, and every citation is checked against what was actually retrieved.
- **Captions first, Whisper fallback.** Uses YouTube captions when they exist and transcribes the audio locally when they don't.
- **Live processing status.** A progress bar follows the job through every pipeline step, with a Retry button on failure.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, `react-youtube` |
| API | Python, FastAPI, SQLAlchemy, Pydantic |
| Database | PostgreSQL 16 with `pgvector` (vectors) and `pg_trgm` (fuzzy text) |
| Embeddings | `sentence-transformers`, model `all-MiniLM-L6-v2` (384-dim, normalized) |
| Speech-to-text | `faster-whisper` (word-level timestamps), audio via `yt-dlp` + ffmpeg |
| Transcripts | `youtube-transcript-api` |
| LLM | Qwen3 4B served locally by Ollama |
| Infra | Docker Compose (database), DB-polling background worker |

## How it works

### 1. Ingestion (background worker)

`POST /videos` validates the URL, creates a `Video` and a `ProcessingJob`, and returns immediately. A separate worker process claims the job (`SELECT ... FOR UPDATE SKIP LOCKED`) and moves it through these steps:

```
PENDING → FETCHING_METADATA → FETCHING_TRANSCRIPT
        → [DOWNLOADING_AUDIO → TRANSCRIBING]      only when the video has no captions
        → CHUNKING → EMBEDDING → INDEXING → READY      (or FAILED)
```

The frontend polls `GET /videos/{id}` and shows the status and progress of each step.

### 2. Chunking

Caption lines and Whisper segments are short, so they are merged into chunks of about 300–700 characters and 20–45 seconds. Chunks close at sentence boundaries where possible, and each chunk keeps its start/end time and the word-level timings of everything merged into it.

### 3. Retrieval

`/search` and `/ask` use hybrid retrieval:

- **Keyword:** case-insensitive substring match, ranked by trigram similarity. Best for names and exact phrases.
- **Fuzzy:** `pg_trgm` similarity, used when the keyword pass finds nothing (typos, slightly different wording).
- **Semantic:** cosine similarity over the MiniLM embeddings stored in pgvector.
- **Find-all mode:** queries like "every time" or "find all" trigger a wide retrieval that returns each literal occurrence, localized to the word and de-duplicated within a time window.
- **Quoted queries** (`"open ai"`) put lexical matches ahead of semantic ones.

### 4. Grounded answers

`/ask` retrieves the best excerpts, labels each with its `segment_id` and timestamp, and asks the LLM to answer from those excerpts only and reply as JSON: `{answer, citations: [{segment_id, timestamp, text, quote}]}`.

The response is never trusted blindly:

- JSON is validated with Pydantic (markdown fences and `mm:ss` timestamps are tolerated).
- Citations pointing at a segment that was not retrieved are dropped.
- The returned timestamp is replaced by the real stored one. If the model supplied an exact `quote`, it is located inside the chunk's word timings (exact match, then fuzzy fallback for transcription errors) to pinpoint the moment.
- If the model returns malformed output, the API falls back to showing the top matching segments instead of a made-up answer.

## Project structure

```
youtube-ai-search-3/
├── app/
│   ├── main.py          FastAPI routes
│   ├── db.py            SQLAlchemy models: Video, TranscriptSegment, ProcessingJob
│   ├── youtube.py       URL parsing, metadata, captions, Whisper fallback
│   ├── chunking.py      sentence-aware chunking
│   ├── embeddings.py    local sentence-transformers embeddings
│   ├── search.py        keyword / fuzzy / semantic / hybrid / find-all
│   ├── llm.py           Ollama call + structured-output parsing
│   ├── rag.py           retrieval + citation validation
│   ├── timestamps.py    formatting + exact phrase localization
│   ├── statuses.py      job status constants
│   ├── schemas.py       request/response models
│   └── config.py        settings (overridable via .env)
├── workers/
│   └── video_processor.py   background worker
├── tests/               pytest suite
├── frontend/            Next.js app
│   └── src/
│       ├── app/         page + layout
│       ├── components/  UrlForm, StatusProgress, VideoPlayer, TranscriptPanel, ChatPanel
│       └── lib/         api.ts (typed client), types.ts (mirrors schemas.py)
├── docker-compose.yml   Postgres + pgvector
├── init_db.sql          enables the vector and pg_trgm extensions
├── requirements.txt
└── requests.http        sample API calls (VS Code REST Client)
```

## Prerequisites

- Python 3.10+ (developed on 3.13)
- Node.js 18+
- Docker Desktop (for the database)
- [Ollama](https://ollama.com)
- ffmpeg on your PATH (only needed for the Whisper fallback; macOS: `brew install ffmpeg`)

## Setup

Run everything from the project root (`youtube-ai-search-3/`) unless noted.

**1. Database**

```bash
docker compose up -d db
docker compose exec db psql -U postgres -d youtube_ai_search -c "\dx"   # should list vector and pg_trgm
```

**2. LLM**

```bash
ollama pull qwen3:4b
curl http://127.0.0.1:11434/api/tags      # should list qwen3:4b
```

If `ollama serve` says the port is already in use, Ollama is already running, which is fine.

**3. Backend dependencies**

```bash
python -m venv venv
source venv/bin/activate                  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**4. Allow the frontend to call the API (CORS)**

Add this to `app/main.py`, right after `app = FastAPI(...)`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**5. Frontend dependencies**

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

## Run

Open three terminals (Ollama runs in the background on its own).

```bash
# Terminal 1: API (project root, venv active)
uvicorn app.main:app --reload --port 8000

# Terminal 2: worker (project root, venv active)
python -m workers.video_processor

# Terminal 3: frontend
cd frontend && npm run dev
```

Open **http://localhost:3000**, paste a YouTube URL, and wait for the status to reach READY. The first run is slower because the embedding model (and the Whisper model, if needed) is downloaded once.

## Configuration

Defaults live in `app/config.py`. Override any of them with a `.env` file in the project root.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/youtube_ai_search` | Postgres connection (matches `docker-compose.yml`) |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `all-MiniLM-L6-v2` / `384` | Changing the model means re-embedding all data and migrating the vector column |
| `WHISPER_MODEL` | `base` | Larger models are more accurate but slower |
| `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | `cpu` / `int8` | Whisper runtime |
| `CHUNK_MIN_CHARS` / `CHUNK_MAX_CHARS` | `300` / `700` | Chunk size |
| `CHUNK_MIN_SECONDS` / `CHUNK_MAX_SECONDS` | `20` / `45` | Chunk duration |
| `DEFAULT_TOP_K` | `5` | Excerpts sent to the LLM for normal questions |
| `FIND_ALL_TOP_K` | `30` | Candidates for "find every mention" queries |
| `FIND_ALL_DEDUP_WINDOW_SECONDS` | `8` | Mentions closer than this are merged |
| `WORKER_POLL_INTERVAL_SECONDS` | `2` | How often the worker checks for jobs |

The Ollama URL and model name (`qwen3:4b`) are constants at the top of `app/llm.py`.

## API

Interactive docs are available at http://localhost:8000/docs.

| Endpoint | Purpose |
|---|---|
| `POST /videos` | Queue a video: `{"youtube_url": "..."}`. Returns 202 immediately. A READY video is not re-queued, and an in-flight job is not duplicated. |
| `GET /videos/{id}` | Metadata, status, and latest job progress/error |
| `GET /videos/{id}/transcript` | Full transcript with `{seconds, formatted}` timestamps |
| `POST /videos/{id}/retry` | Re-queue a video (409 if a job is already running) |
| `POST /search` | Retrieval only, no LLM: `{video_id, query, mode: hybrid\|semantic\|text, top_k}` |
| `POST /ask` | Grounded answer with citations: `{video_id, question}` (409 until the video is READY) |
| `GET /health` | Liveness check |

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"video_id": 1, "question": "What did they say about startups?"}'
```

## Tests

```bash
pytest tests/ -v
```

The suite covers URL parsing, timestamp formatting and phrase localization, chunking, query-intent detection, structured LLM output parsing, and citation validation (fabricated timestamps and segment IDs are rejected). External services are not required.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Status stays on **PENDING** | The worker isn't running. Start `python -m workers.video_processor`. |
| Browser shows CORS errors, requests fail | Step 4 (CORS middleware) is missing, or the frontend origin isn't `http://localhost:3000`. |
| `role "postgres" does not exist` | Another Postgres (e.g. Homebrew's) is bound to port 5432 and answering instead of the Docker one. Run `brew services stop postgresql@16`, then `docker compose up -d db`. Check with `lsof -iTCP:5432 -sTCP:LISTEN -n -P`. |
| `Could not connect to Ollama` | Ollama isn't running, or `qwen3:4b` isn't pulled. Run `ollama list`. |
| Whisper step fails | ffmpeg is missing from your PATH, or `yt-dlp` is outdated and YouTube changed something. Try `pip install -U yt-dlp`. |
| Video fails immediately | Private, age-restricted, or region-blocked videos can't be fetched. Try a public one. |

## Limitations

- **Timestamp precision depends on the source.** Whisper transcripts give word-level timing. YouTube captions are line-level only, so results from caption-based videos are accurate to the chunk (about 20–45 seconds).
- **`/ask` is single-turn.** Each question is answered independently, which keeps every answer tied to its own retrieval, but there is no follow-up memory.
- **Answer quality is bounded by the local model.** Qwen3 4B is small. A larger Ollama model can be dropped in by changing `OLLAMA_MODEL` in `app/llm.py`.
- **English-first.** Caption selection prefers English, and the default MiniLM embedding model is English-centric.

## Roadmap ideas

Multi-turn chat, a multilingual embedding model, re-ranking, auth and per-user libraries, and a production deployment setup.
