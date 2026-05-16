#!/usr/bin/env python3
"""Hash a password for APP_PASSWORD_HASH.

Usage:
    python scripts/hash_password.py 'mysecret'
    python scripts/hash_password.py              # interactive prompt (hidden)
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

# Allow running from anywhere without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.auth import hash_password  # noqa: E402


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: hash_password.py [password]", file=sys.stderr)
        return 2

    if len(sys.argv) == 2:
        pw = sys.argv[1]
    else:
        pw = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if pw != confirm:
            print("passwords do not match", file=sys.stderr)
            return 1

    if not pw:
        print("password must not be empty", file=sys.stderr)
        return 1

    print(hash_password(pw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
