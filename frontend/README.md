# Frontend — YouTube AI Search & Chat

A Next.js (App Router + TypeScript + Tailwind) frontend for your existing
FastAPI backend (`app/main.py`, `app/schemas.py`, `app/statuses.py`, the
`workers/video_processor.py` worker, etc.). It talks to your backend's
routes exactly as they are — `/videos`, `/videos/{id}`,
`/videos/{id}/retry`, `/videos/{id}/transcript`, `/search`, `/ask` — no
backend changes needed.

## What it does

1. Paste a YouTube URL → `POST /videos` queues a `ProcessingJob`.
2. Polls `GET /videos/{id}` every 1.5s and shows a live progress bar
   driven by `latest_job.status` / `latest_job.progress` (PENDING →
   FETCHING_METADATA → … → READY, or FAILED with a **Retry** button that
   calls `POST /videos/{id}/retry`).
3. Once `READY`: embeds the YouTube player, loads the full transcript
   (`GET /videos/{id}/transcript`), and shows a search box
   (`POST /search`, switchable between `hybrid` / `semantic` / `text`
   modes) and a chat box (`POST /ask`).
4. Every search result and every chat citation is a clickable timestamp
   chip. Clicking one seeks the embedded YouTube player to that exact
   second via the IFrame Player API — using the `start_time.seconds`
   your backend already computed (including the word-level pinpointing
   from `app/rag.py` / `app/timestamps.py`, not just the chunk start).

Because `POST /ask` is single-turn (your backend doesn't accept prior
chat history), each question is sent independently — this is intentional
and keeps every answer's citations grounded in that one retrieval, with
no risk of stale context from earlier turns.

## Setup

**1. Add CORS to your backend** (not currently in `app/main.py` — without
it the browser blocks every request from `localhost:3000`):

```python
# app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**2. Install and run the frontend:**

```bash
cd frontend
npm install
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_URL at your backend
npm run dev
```

Open **http://localhost:3000**.

## Before you paste a URL

Your backend processes videos asynchronously via a separate worker
process — the API only enqueues a job. Make sure both of these are
running (from your backend's project root):

```bash
uvicorn app.main:app --reload          # API
python -m workers.video_processor      # background worker that actually
                                        # does the fetching/transcribing/
                                        # embedding
```

If you paste a URL and the status bar sits on **PENDING** forever, the
worker isn't running — the UI surfaces a hint for this under the
progress bar.

## Project structure

```
frontend/
  src/
    app/
      layout.tsx        root layout
      page.tsx           orchestrator: URL input, polling, layout
      globals.css
    components/
      UrlForm.tsx         YouTube URL input
      StatusProgress.tsx  status label + progress bar + retry-on-fail
      VideoPlayer.tsx      react-youtube wrapper exposing seekTo()
      TranscriptPanel.tsx  full transcript + in-video search (hybrid/semantic/text)
      ChatPanel.tsx         /ask chat with clickable citation chips
    lib/
      types.ts   mirrors app/schemas.py + app/statuses.py exactly
      api.ts      typed fetch wrapper for every backend route
  .env.local.example
  package.json / tsconfig.json / tailwind.config.js / next.config.js
```

## Notes on a few design choices

- **`lib/types.ts` mirrors your Pydantic schemas field-for-field**
  (`start_time: {seconds, formatted}`, `latest_job`, `is_find_all`,
  etc.) — if you change `app/schemas.py`, update this file to match.
- **Timestamps are never reformatted client-side.** The backend already
  returns both the raw seconds (for `player.seekTo()`) and a
  human-readable string (`formatted`, e.g. `"23:41"`) — the frontend
  just displays what it's given, so `app/timestamps.py` stays the one
  source of truth for formatting.
- **Search mode toggle** (Hybrid / Semantic / Keyword) maps directly to
  your `SearchRequest.mode` field and re-runs the current query when
  switched.
