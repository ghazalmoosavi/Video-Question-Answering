// Mirrors app/statuses.py and app/schemas.py exactly — keep in sync with the backend.

export type VideoStatus =
  | "PENDING"
  | "FETCHING_METADATA"
  | "FETCHING_TRANSCRIPT"
  | "DOWNLOADING_AUDIO"
  | "TRANSCRIBING"
  | "CHUNKING"
  | "EMBEDDING"
  | "INDEXING"
  | "READY"
  | "FAILED";

export interface JobOut {
  job_id: number;
  status: VideoStatus;
  progress: number; // 0-100
  error: string | null;
}

export interface ProcessVideoResponse {
  video_id: number;
  youtube_id: string;
  status: VideoStatus;
  job: JobOut;
  message: string;
}

export interface RetryResponse {
  video_id: number;
  job: JobOut;
  message: string;
}

export interface VideoInfo {
  id: number;
  youtube_id: string;
  url: string;
  title: string | null;
  channel: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  transcript_source: "youtube" | "whisper" | null;
  status: VideoStatus;
  num_segments: number;
  latest_job: JobOut | null;
}

export interface Timestamp {
  seconds: number;
  formatted: string; // already MM:SS / HH:MM:SS from the backend
}

export interface TranscriptSegment {
  segment_id: number;
  start_time: Timestamp;
  end_time: Timestamp;
  text: string;
  has_word_timings: boolean;
}

export type SearchMode = "semantic" | "text" | "hybrid";

export interface SearchResultItem {
  segment_id: number;
  start_time: Timestamp;
  end_time: Timestamp;
  text: string;
  score: number;
  match_type: "semantic" | "keyword" | "fuzzy";
}

export interface SearchResponse {
  query: string;
  mode: SearchMode;
  results: SearchResultItem[];
}

export interface Citation {
  segment_id: number | null;
  start_time: Timestamp;
  text: string;
}

export interface AskResponse {
  question: string;
  answer: string;
  is_find_all: boolean;
  citations: Citation[];
}

// Frontend-only shape for rendering the chat thread
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isFindAll?: boolean;
}
