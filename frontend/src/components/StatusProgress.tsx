"use client";

import type { JobOut, VideoStatus } from "@/lib/types";

interface StatusProgressProps {
  status: VideoStatus;
  job: JobOut | null;
  onRetry: () => void;
  retrying: boolean;
}

const STATUS_LABELS: Record<VideoStatus, string> = {
  PENDING: "Queued — waiting for the background worker to pick this up…",
  FETCHING_METADATA: "Fetching video metadata…",
  FETCHING_TRANSCRIPT: "Looking for YouTube captions…",
  DOWNLOADING_AUDIO: "No captions found — downloading audio…",
  TRANSCRIBING: "Transcribing audio locally with Whisper (can take a while)…",
  CHUNKING: "Splitting the transcript into searchable chunks…",
  EMBEDDING: "Generating embeddings…",
  INDEXING: "Saving to the database…",
  READY: "Ready",
  FAILED: "Processing failed",
};

export default function StatusProgress({ status, job, onRetry, retrying }: StatusProgressProps) {
  const progress = job?.progress ?? 0;

  if (status === "FAILED") {
    return (
      <div className="space-y-2 rounded-lg border border-red-500/20 bg-red-500/5 p-3">
        <p className="text-sm text-red-400">
          {STATUS_LABELS.FAILED}
          {job?.error ? `: ${job.error}` : "."}
        </p>
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-40"
        >
          {retrying ? "Retrying…" : "Retry processing"}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-white/60">{STATUS_LABELS[status]}</p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-red-600 transition-all duration-500"
          style={{ width: `${Math.min(100, Math.max(4, progress))}%` }}
        />
      </div>
      {status === "PENDING" && (
        <p className="text-xs text-white/30">
          Nothing happening? Make sure the worker is running: <code>python -m workers.video_processor</code>
        </p>
      )}
    </div>
  );
}
