#!/usr/bin/env python3
"""Reject files that should never be committed to this repository."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath


EXACT_NAMES = {
    "authorized_keys",
    "credentials",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
}
SECRET_SUFFIXES = {".db", ".jks", ".key", ".keystore", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"}


def is_sensitive(filename: str) -> bool:
    path = PurePosixPath(filename.replace("\\", "/"))
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}

    if name in {".env.example", "env.example"}:
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if "secrets" in parts or name in EXACT_NAMES:
        return True
    return Path(name).suffix.lower() in SECRET_SUFFIXES


def main(argv: list[str]) -> int:
    rejected = sorted({filename for filename in argv if is_sensitive(filename)})
    if not rejected:
        return 0

    print("ERROR: sensitive files must not be committed:", file=sys.stderr)
    for filename in rejected:
        print(f"  - {filename}", file=sys.stderr)
    print("Store secrets outside Git and commit only sanitized *.example files.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
