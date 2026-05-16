import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from brain.voice import VoiceUnavailableError, transcribe


def test_rejects_empty_audio():
    with pytest.raises(ValueError):
        transcribe(b"", filename="x.webm")


def test_uses_openai_when_key_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = SimpleNamespace(text=" привет ")
    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module)

    out = transcribe(b"\x00\x01\x02", filename="x.webm")
    assert out == "привет"
    args = fake_client.audio.transcriptions.create.call_args.kwargs
    assert args["language"] == "ru"
    assert args["model"].startswith("whisper")


def test_local_fallback_raises_when_no_key_and_no_local(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Ensure the import fails — pretend faster-whisper isn't installed.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(VoiceUnavailableError):
        transcribe(b"\x00\x01\x02", filename="x.webm")


def test_local_fallback_invoked_when_available(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    fake_segment = SimpleNamespace(text=" локально ")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], SimpleNamespace())
    fake_module = MagicMock()
    fake_module.WhisperModel = MagicMock(return_value=fake_model)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    out = transcribe(b"\x00\x01", filename="x.webm")
    assert out == "локально"
