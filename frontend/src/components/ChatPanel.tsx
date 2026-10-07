"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, askVideo } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

interface ChatPanelProps {
  videoId: number;
  onSeek: (seconds: number) => void;
}

const SUGGESTIONS = [
  "Where do they talk about AI?",
  "Find where they mention OpenAI.",
  "Find every time they discuss startups.",
  "What did they say about Elon Musk?",
];

export default function ChatPanel({ videoId, onSeek }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const ask = async (question: string) => {
    if (!question.trim() || loading) return;
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      // Note: /ask is single-turn — the backend doesn't accept prior chat
      // history, so each question is answered independently against the
      // transcript (this is what keeps every answer grounded and avoids
      // hallucinated timestamps).
      const res = await askVideo(videoId, question);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.answer, citations: res.citations, isFindAll: res.is_find_all },
      ]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong asking that question.");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(input);
  };

  return (
    <div className="flex h-full flex-col rounded-lg border border-white/10 bg-white/[0.03]">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-white/40">Ask anything about this video. Try:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => ask(s)}
                  className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/60 hover:border-white/30 hover:text-white/90"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                m.role === "user"
                  ? "max-w-[85%] rounded-lg rounded-br-sm bg-red-600/90 px-3 py-2 text-sm text-white"
                  : "max-w-[85%] rounded-lg rounded-bl-sm bg-white/10 px-3 py-2 text-sm text-white/90"
              }
            >
              {m.isFindAll && (
                <span className="mb-1 inline-block rounded bg-black/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white/50">
                  Every occurrence
                </span>
              )}
              <p className="whitespace-pre-wrap">{m.content}</p>
              {m.citations && m.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5 border-t border-white/10 pt-2">
                  {m.citations.map((c, ci) => (
                    <button
                      key={c.segment_id ?? ci}
                      type="button"
                      onClick={() => onSeek(c.start_time.seconds)}
                      title={c.text}
                      className="inline-flex items-center rounded-md bg-black/20 px-2 py-0.5 text-xs font-mono text-red-300 hover:bg-black/40"
                    >
                      ▶ {c.start_time.formatted}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && <p className="text-sm text-white/40">Thinking…</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-white/10 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this video…"
          className="flex-1 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none placeholder:text-white/40 focus:border-white/30"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
