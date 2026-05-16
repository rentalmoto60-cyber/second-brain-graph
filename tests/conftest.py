"""Shared pytest fixtures — keep the suite hermetic w.r.t. env vars."""
import pytest


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Strip ambient credentials so dev env vars never leak into tests.

    Tests that need auth enable it explicitly via monkeypatch.setenv inside
    the test (and recreate the app after setting the vars).
    """
    for var in (
        "APP_USERNAME",
        "APP_PASSWORD_HASH",
        "ALLOWED_HOSTS",
        "STORAGE_PATH",
        "BRAIN_DB",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Suppress the first-run demo seed so the existing test suite keeps
    # observing the empty graph it was written against.
    monkeypatch.setenv("SEED_DEMO_NODES", "0")
