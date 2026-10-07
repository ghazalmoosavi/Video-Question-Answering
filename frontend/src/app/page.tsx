"use client";

import { useEffect, useRef, useState } from "react";
import ChatPanel from "@/components/ChatPanel";
import StatusProgress from "@/components/StatusProgress";
import TranscriptPanel from "@/components/TranscriptPanel";
import UrlForm from "@/components/UrlForm";
import VideoPlayer, { type VideoPlayerHandle } from "@/components/VideoPlayer";
import { ApiError, createVideo, getTranscript, getVideo, retryVideo } from "@/lib/api";
import type { TranscriptSegment, VideoInfo } from "@/lib/types";

const POLL_INTERVAL_MS = 1500;

export default function Home() {
  const [video, setVideo] = useState<VideoInfo | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loadingCreate, setLoadingCreate] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const playerRef = useRef<VideoPlayerHandle>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  const pollUntilDone = (videoId: number) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getVideo(videoId);
        setVideo(updated);
        if (updated.status === "READY") {
          stopPolling();
          setSegments(await getTranscript(videoId));
        } else if (updated.status === "FAILED") {
          stopPolling();
        }
      } catch {
        stopPolling();
      }
    }, POLL_INTERVAL_MS);
  };

  const handleSubmitUrl = async (url: string) => {
    setError(null);
    setLoadingCreate(true);
    stopPolling();
    setSegments([]);
    setVideo(null);

    try {
      const created = await createVideo(url);
      const info = await getVideo(created.video_id);
      setVideo(info);

      if (info.status === "READY") {
        setSegments(await getTranscript(info.id));
      } else if (info.status !== "FAILED") {
        pollUntilDone(info.id);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not process that URL.");
    } finally {
      setLoadingCreate(false);
    }
  };

  const handleRetry = async () => {
    if (!video) return;
    setRetrying(true);
    setError(null);
    try {
      await retryVideo(video.id);
      const info = await getVideo(video.id);
      setVideo(info);
      pollUntilDone(video.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not retry processing.");
    } finally {
      setRetrying(false);
    }
  };

  const handleSeek = (seconds: number) => {
    playerRef.current?.seekTo(seconds);
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">YouTube AI Search &amp; Chat</h1>
        <p className="text-sm text-white/50">
          Paste a link, search the transcript, and ask questions — every answer links back to the
          exact moment in the video.
        </p>
      </header>

      <UrlForm onSubmit={handleSubmitUrl} loading={loadingCreate} />

      {error && <p className="text-sm text-red-400">{error}</p>}

      {video && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <StatusDot status={video.status} />
            {video.title && <span className="text-white/80">{video.title}</span>}
            {video.channel && <span className="text-white/40">· {video.channel}</span>}
          </div>

          {video.status !== "READY" && (
            <StatusProgress
              status={video.status}
              job={video.latest_job}
              onRetry={handleRetry}
              retrying={retrying}
            />
          )}

          {video.status === "READY" && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="flex flex-col gap-4">
                <VideoPlayer ref={playerRef} videoId={video.youtube_id} />
                <div className="h-80">
                  <TranscriptPanel videoId={video.id} segments={segments} onSeek={handleSeek} />
                </div>
              </div>
              <div className="h-[34rem]">
                <ChatPanel videoId={video.id} onSeek={handleSeek} />
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}

function StatusDot({ status }: { status: VideoInfo["status"] }) {
  const styles: Record<VideoInfo["status"], string> = {
    PENDING: "bg-white/10 text-white/60",
    FETCHING_METADATA: "bg-amber-500/15 text-amber-400",
    FETCHING_TRANSCRIPT: "bg-amber-500/15 text-amber-400",
    DOWNLOADING_AUDIO: "bg-amber-500/15 text-amber-400",
    TRANSCRIBING: "bg-amber-500/15 text-amber-400",
    CHUNKING: "bg-amber-500/15 text-amber-400",
    EMBEDDING: "bg-amber-500/15 text-amber-400",
    INDEXING: "bg-amber-500/15 text-amber-400",
    READY: "bg-emerald-500/15 text-emerald-400",
    FAILED: "bg-red-500/15 text-red-400",
  };
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  );
}
