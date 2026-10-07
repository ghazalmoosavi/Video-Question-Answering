"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import YouTube, { type YouTubeEvent, type YouTubePlayer } from "react-youtube";

export interface VideoPlayerHandle {
  seekTo: (seconds: number) => void;
}

interface VideoPlayerProps {
  videoId: string;
}

const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(function VideoPlayer(
  { videoId },
  ref
) {
  const playerRef = useRef<YouTubePlayer | null>(null);

  useImperativeHandle(ref, () => ({
    seekTo: (seconds: number) => {
      const player = playerRef.current;
      if (!player) return;
      player.seekTo(seconds, true);
      player.playVideo();
    },
  }));

  const handleReady = (event: YouTubeEvent) => {
    playerRef.current = event.target;
  };

  return (
    <div className="aspect-video w-full overflow-hidden rounded-lg border border-white/10 bg-black">
      <YouTube
        videoId={videoId}
        onReady={handleReady}
        opts={{ width: "100%", height: "100%", playerVars: { rel: 0 } }}
        className="h-full w-full"
        iframeClassName="h-full w-full"
      />
    </div>
  );
});

export default VideoPlayer;
