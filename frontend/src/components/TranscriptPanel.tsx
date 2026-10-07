"use client";

import { useState, type FormEvent } from "react";
import { ApiError, searchVideo } from "@/lib/api";
import type { SearchMode, SearchResultItem, TranscriptSegment } from "@/lib/types";

interface TranscriptPanelProps {
  videoId: number;
  segments: TranscriptSegment[];
  onSeek: (seconds: number) => void;
}

type DisplayRow = { key: number; seconds: number; formatted: string; text: string; matchType?: string };

const MODES: { value: SearchMode; label: string }[] = [
  { value: "hybrid", label: "Hybrid" },
  { value: "semantic", label: "Semantic" },
  { value: "text", label: "Keyword" },
];

export default function TranscriptPanel({ videoId, segments, onSeek }: TranscriptPanelProps) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [results, setResults] = useState<SearchResultItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = async (q: string, m: SearchMode) => {
    if (!q.trim()) {
      setResults(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await searchVideo(videoId, q.trim(), m);
      setResults(data.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (e: FormEvent) => {
    e.preventDefault();
    runSearch(query, mode);
  };

  const handleModeChange = (m: SearchMode) => {
    setMode(m);
    if (results) runSearch(query, m);
  };

  const clearSearch = () => {
    setQuery("");
    setResults(null);
  };

  const rows: DisplayRow[] = results
    ? results.map((r) => ({
        key: r.segment_id,
        seconds: r.start_time.seconds,
        formatted: r.start_time.formatted,
        text: r.text,
        matchType: r.match_type,
      }))
    : segments.map((s) => ({
        key: s.segment_id,
        seconds: s.start_time.seconds,
        formatted: s.start_time.formatted,
        text: s.text,
      }));

  return (
    <div className="flex h-full flex-col rounded-lg border border-white/10 bg-white/[0.03]">
      <div className="border-b border-white/10 p-3">
        <form onSubmit={handleSearch} className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search this video's transcript…"
            className="flex-1 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm outline-none placeholder:text-white/40 focus:border-white/30"
          />
          <button type="submit" className="rounded-md bg-white/10 px-3 py-1.5 text-sm hover:bg-white/20">
            {loading ? "…" : "Search"}
          </button>
          {results && (
            <button
              type="button"
              onClick={clearSearch}
              className="rounded-md px-2 py-1.5 text-xs text-white/50 hover:text-white/80"
            >
              Clear
            </button>
          )}
        </form>

        <div className="mt-2 flex items-center gap-1.5">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => handleModeChange(m.value)}
              className={`rounded-full px-2.5 py-0.5 text-xs transition ${
                mode === m.value
                  ? "bg-red-600/20 text-red-400"
                  : "text-white/40 hover:text-white/70"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        {results && (
          <p className="mt-2 text-xs text-white/40">
            {results.length} match{results.length === 1 ? "" : "es"} for &ldquo;{query}&rdquo;
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {rows.length === 0 ? (
          <p className="text-sm text-white/40">No matches found.</p>
        ) : (
          <ul className="space-y-1">
            {rows.map((row) => (
              <li key={row.key}>
                <button
                  type="button"
                  onClick={() => onSeek(row.seconds)}
                  className="group flex w-full items-start gap-3 rounded-md px-2 py-1.5 text-left text-sm hover:bg-white/5"
                >
                  <span className="mt-0.5 shrink-0 rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-white/60 group-hover:bg-red-600/20 group-hover:text-red-400">
                    {row.formatted}
                  </span>
                  <span className="text-white/80">{row.text}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
