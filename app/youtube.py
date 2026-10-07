import re
import os
import tempfile
from typing import List, Dict, Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# Handles watch?v=, youtu.be/, /embed/, /shorts/, /live/, and bare 11-char IDs.
_ID_PATTERN = r"[0-9A-Za-z_-]{11}"
YOUTUBE_URL_PATTERNS = [
    re.compile(rf"(?:youtube\.com/watch\?v=)({_ID_PATTERN})"),
    re.compile(rf"(?:youtube\.com/shorts/)({_ID_PATTERN})"),
    re.compile(rf"(?:youtube\.com/live/)({_ID_PATTERN})"),
    re.compile(rf"(?:youtube\.com/embed/)({_ID_PATTERN})"),
    re.compile(rf"(?:youtu\.be/)({_ID_PATTERN})"),
]
_BARE_ID_RE = re.compile(rf"^{_ID_PATTERN}$")


class InvalidYouTubeURLError(ValueError):
    pass


def extract_video_id(url_or_id: str) -> str:
    """Pull the 11-character YouTube video ID out of a full URL (watch,
    youtu.be, shorts, embed, live) or pass through a bare ID."""
    if not url_or_id or not url_or_id.strip():
        raise InvalidYouTubeURLError("Empty YouTube URL/ID.")
    candidate = url_or_id.strip()

    if _BARE_ID_RE.match(candidate):
        return candidate

    # Also handle a leading v= query param anywhere, and query strings/
    # fragments trailing the ID (?, &, #), by checking against watch?v=
    # explicitly plus the generic patterns above.
    for pattern in YOUTUBE_URL_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1)

    # Fallback: some URLs put the ID right after the last "/" (e.g. a
    # shortened redirect) — only accept it if it looks like a real ID.
    tail = candidate.rstrip("/").rsplit("/", 1)[-1]
    tail = tail.split("?")[0].split("&")[0]
    if _BARE_ID_RE.match(tail):
        return tail

    raise InvalidYouTubeURLError(f"Could not extract a YouTube video ID from: {url_or_id!r}")


def get_video_metadata(video_id: str) -> Dict:
    """Fetch title/channel/thumbnail/duration via yt-dlp without
    downloading any media."""
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    thumbnail = info.get("thumbnail")
    if not thumbnail:
        thumbnails = info.get("thumbnails") or []
        thumbnail = thumbnails[-1]["url"] if thumbnails else None

    return {
        "title": info.get("title"),
        "channel": info.get("uploader") or info.get("channel"),
        "thumbnail_url": thumbnail,
        "duration": info.get("duration"),
    }


def fetch_official_transcript(video_id: str) -> Optional[List[Dict]]:
    """Try to get YouTube's own transcript (manual, or auto-generated as a
    fallback). Returns None if no transcript is available at all.

    Note: YouTube captions are line-level only, so `words` is left empty —
    phrase localization for these segments falls back to chunk-level
    timestamps (see app.timestamps.locate_phrase_in_segment).
    """
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(["en"])
        except NoTranscriptFound:
            transcript = next(iter(transcript_list))

        fetched = transcript.fetch()
        return [
            {
                "start": item["start"],
                "end": item["start"] + item.get("duration", 0.0),
                "text": item["text"],
                "words": [],
            }
            for item in fetched
            if item["text"].strip()
        ]
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except Exception:
        # Any other transient failure -> treat as "no transcript", trigger
        # the Whisper fallback rather than hard-failing the whole request.
        return None


def download_audio(video_id: str, out_dir: Optional[str] = None) -> str:
    """Download best-audio track and convert to WAV via ffmpeg (required)."""
    import yt_dlp

    out_dir = out_dir or tempfile.mkdtemp(prefix="yt_audio_")
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_template = os.path.join(out_dir, f"{video_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "quiet": True,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    wav_path = os.path.join(out_dir, f"{video_id}.wav")
    if not os.path.exists(wav_path):
        raise RuntimeError(
            "Audio download/conversion failed. Make sure ffmpeg is installed and on PATH."
        )
    return wav_path

def cleanup_audio_dir(audio_path: str) -> None:
    """Remove the temp audio file and its containing temp dir, best-effort."""
    try:
        directory = os.path.dirname(audio_path)
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if directory and os.path.isdir(directory) and directory.startswith(tempfile.gettempdir()):
            if not os.listdir(directory):
                os.rmdir(directory)
    except OSError:
        pass


_whisper_model = None
_whisper_model_key = None


def _get_whisper_model(settings):
    global _whisper_model, _whisper_model_key
    key = (settings.WHISPER_MODEL, settings.WHISPER_DEVICE, settings.WHISPER_COMPUTE_TYPE)
    if _whisper_model is None or _whisper_model_key != key:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
        )
        _whisper_model_key = key
    return _whisper_model


def transcribe_with_whisper(audio_path: str, settings) -> List[Dict]:
    """Local speech-to-text fallback for videos with no YouTube transcript.
    Requests word-level timestamps so exact phrases can be localized
    precisely later (see app.timestamps.locate_phrase_in_words)."""
    model = _get_whisper_model(settings)
    #segments, _info = model.transcribe(audio_path, vad_filter=True, word_timestamps=True)# first edit
    segments, _info = model.transcribe(audio_path, vad_filter=False, word_timestamps=True)
    result = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        words = [
            {"word": w.word.strip(), "start": w.start, "end": w.end}
            for w in (seg.words or [])
            if w.word and w.word.strip()
        ]
        result.append({"start": seg.start, "end": seg.end, "text": text, "words": words})
    return result


def get_transcript(youtube_url: str, settings, on_step=None) -> Dict:
    """Main entry point used by the worker.

    `on_step(status)` is an optional callback invoked as the pipeline moves
    through FETCHING_TRANSCRIPT / DOWNLOADING_AUDIO / TRANSCRIBING, so the
    caller can persist progress without this module knowing about the DB.

    Returns:
        {
          "video_id": str,
          "title": str | None, "channel": str | None,
          "thumbnail_url": str | None, "duration": float | None,
          "source": "youtube" | "whisper",
          "segments": [{"start","end","text","words":[...]}]
        }
    """
    from app import statuses

    video_id = extract_video_id(youtube_url)

    if on_step:
        on_step(statuses.FETCHING_TRANSCRIPT)
    segments = fetch_official_transcript(video_id)
    source = "youtube"

    if not segments:
        if on_step:
            on_step(statuses.DOWNLOADING_AUDIO)
        audio_path = download_audio(video_id)
        try:
            if on_step:
                on_step(statuses.TRANSCRIBING)
            segments = transcribe_with_whisper(audio_path, settings)
            source = "whisper"
        finally:
            cleanup_audio_dir(audio_path)

    if not segments:
        raise RuntimeError(
            "Failed to obtain a transcript via YouTube captions or the Whisper fallback."
        )

    return {"video_id": video_id, "source": source, "segments": segments}
