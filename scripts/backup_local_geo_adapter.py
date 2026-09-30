#!/usr/bin/env python3
"""Deterministic copy/read-back adapter for the geo-recovery protocol tests."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "copy":
        source, destination = Path(argv[2]), Path(argv[3])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return 0
    if len(argv) == 4 and argv[1] == "verify":
        destination, expected = Path(argv[2]), argv[3]
        actual = digest(destination)
        print(actual)
        return 0 if actual == expected else 1
    if len(argv) == 4 and argv[1] == "fetch":
        source, destination = Path(argv[2]), Path(argv[3])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return 0
    print(
        "usage: backup_local_geo_adapter.py copy SOURCE DEST | verify DEST SHA256 | fetch SOURCE DEST",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
