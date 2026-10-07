import type {
  AskResponse,
  ProcessVideoResponse,
  RetryResponse,
  SearchMode,
  SearchResponse,
  TranscriptSegment,
  VideoInfo,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore non-JSON error bodies
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

export function createVideo(youtube_url: string): Promise<ProcessVideoResponse> {
  return request<ProcessVideoResponse>("/videos", {
    method: "POST",
    body: JSON.stringify({ youtube_url }),
  });
}

export function retryVideo(videoId: number): Promise<RetryResponse> {
  return request<RetryResponse>(`/videos/${videoId}/retry`, { method: "POST" });
}

export function getVideo(videoId: number): Promise<VideoInfo> {
  return request<VideoInfo>(`/videos/${videoId}`);
}

export function getTranscript(videoId: number): Promise<TranscriptSegment[]> {
  return request<TranscriptSegment[]>(`/videos/${videoId}/transcript`);
}

export function searchVideo(
  videoId: number,
  query: string,
  mode: SearchMode = "hybrid",
  top_k = 15
): Promise<SearchResponse> {
  return request<SearchResponse>("/search", {
    method: "POST",
    body: JSON.stringify({ video_id: videoId, query, mode, top_k }),
  });
}

export function askVideo(videoId: number, question: string): Promise<AskResponse> {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify({ video_id: videoId, question }),
  });
}
