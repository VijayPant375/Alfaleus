"""
Transcriber Service — Day 4, Phase 1

Downloads a video from a public URL and transcribes it using OpenAI Whisper.

Key design decisions:
- Whisper model is loaded lazily (only on first call) and cached as a module-level singleton.
- Whisper's transcribe() is CPU-bound and synchronous; it must always run via
  asyncio.run_in_executor to avoid blocking the FastAPI event loop.
- On any failure, the function logs and returns "" — it never raises, so that a
  transcription failure does not crash the wider answer-submission pipeline.
"""

import asyncio
import os
import tempfile
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Lazy singleton — Whisper model loaded once on first call
# ---------------------------------------------------------------------------

_whisper_model = None


def _get_whisper_model():
    """Load and cache the Whisper 'base' model (thread-safe for GIL-bound Python)."""
    global _whisper_model
    if _whisper_model is None:
        import whisper  # noqa: PLC0415 — intentional lazy import

        print("[transcriber] Loading Whisper 'base' model …")
        _whisper_model = whisper.load_model("base")
        print("[transcriber] Whisper model loaded.")
    return _whisper_model


# ---------------------------------------------------------------------------
# Core transcription function
# ---------------------------------------------------------------------------


async def transcribe_answer(
    video_url: str,
    candidate_id: str,
    question_id: int,
) -> str:
    """
    Download a video from *video_url* and return its Whisper transcript.

    Args:
        video_url:    Public URL of the recorded video chunk (webm format).
        candidate_id: Candidate UUID string — used only for log messages.
        question_id:  Question ID integer — used only for log messages.

    Returns:
        The transcript string, or "" if transcription fails for any reason.
    """
    tmp_path: Optional[str] = None

    try:
        # ------------------------------------------------------------------
        # 1. Download video to a named temp file
        # ------------------------------------------------------------------
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(video_url)
            response.raise_for_status()
            video_bytes = response.content

        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        print(
            f"[transcriber] Downloaded {len(video_bytes)} bytes for "
            f"candidate={candidate_id} question={question_id} → {tmp_path}"
        )

        # ------------------------------------------------------------------
        # 2. Run Whisper in a thread pool (never block the event loop)
        # ------------------------------------------------------------------
        loop = asyncio.get_event_loop()
        model = _get_whisper_model()

        result = await loop.run_in_executor(
            None,  # default ThreadPoolExecutor
            lambda: model.transcribe(tmp_path),
        )

        transcript: str = result.get("text", "").strip()
        print(
            f"[transcriber] Transcription complete for "
            f"candidate={candidate_id} question={question_id} "
            f"({len(transcript)} chars)"
        )
        return transcript

    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        print(
            f"[transcriber] ERROR transcribing candidate={candidate_id} "
            f"question={question_id}: {exc}"
        )
        return ""

    finally:
        # Always clean up the temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as cleanup_err:
                print(f"[transcriber] Failed to delete temp file {tmp_path}: {cleanup_err}")
