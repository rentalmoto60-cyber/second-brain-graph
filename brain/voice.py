"""Speech-to-text: OpenAI Whisper API with optional local faster-whisper fallback.

The backend tries, in order:
  1. OpenAI Whisper API if OPENAI_API_KEY is set.
  2. Local faster-whisper if the package is installed.
  3. Raises VoiceUnavailableError otherwise.
"""
from __future__ import annotations

import io
import os
from typing import BinaryIO


class VoiceUnavailableError(RuntimeError):
    """No speech-to-text backend is configured or installed."""


def _transcribe_openai(audio: bytes, filename: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    buf = io.BytesIO(audio)
    buf.name = filename or "audio.webm"
    result = client.audio.transcriptions.create(
        model=os.environ.get("WHISPER_MODEL", "whisper-1"),
        file=buf,
        language="ru",
    )
    return (result.text or "").strip()


def _transcribe_local(audio: bytes, filename: str) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoiceUnavailableError(
            "faster-whisper not installed and OPENAI_API_KEY is not set. "
            "Install with `pip install faster-whisper`, or set OPENAI_API_KEY."
        ) from e

    import tempfile

    model_size = os.environ.get("LOCAL_WHISPER_MODEL", "small")
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1] or ".webm", delete=True) as f:
        f.write(audio)
        f.flush()
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(f.name, language="ru")
        return " ".join(s.text.strip() for s in segments).strip()


def transcribe(audio: bytes, filename: str = "audio.webm") -> str:
    """Transcribe Russian speech to text. Returns empty string if audio yields no speech."""
    if not audio:
        raise ValueError("audio bytes are empty")
    if os.environ.get("OPENAI_API_KEY"):
        return _transcribe_openai(audio, filename)
    return _transcribe_local(audio, filename)
