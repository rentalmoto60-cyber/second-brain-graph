"""Dev launcher: `python app.py` → uvicorn on :8000."""
import uvicorn

from brain.api import app  # noqa: F401  (uvicorn picks it up by import string)


if __name__ == "__main__":
    uvicorn.run(
        "brain.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
