"""Production / dev entrypoint.

Reads HOST and PORT from environment (defaults: 0.0.0.0:8000).
`proxy_headers=True` so X-Forwarded-Proto from nginx is respected — that's
how request.url.scheme becomes "https" behind the reverse proxy, which in
turn enables Secure cookies.
"""
from __future__ import annotations

import os

import uvicorn

from brain.api import app  # noqa: F401  — re-exported for `uvicorn app:app`


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "brain.api:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
