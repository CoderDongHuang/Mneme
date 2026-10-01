#!/usr/bin/env python3
"""AWS CLI adapter for geo backup copy, independent readback, and fetch."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__:
    from .backup_aws_preflight import region_arguments
else:
    from backup_aws_preflight import region_arguments


def _aws_copy(source: str, destination: str) -> None:
    result = subprocess.run(
        ["aws", "s3", "cp", source, destination, "--only-show-errors", *region_arguments()],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "copy":
        _aws_copy(argv[2], argv[3])
        return 0
    if len(argv) == 4 and argv[1] == "fetch":
        destination = Path(argv[3])
        destination.parent.mkdir(parents=True, exist_ok=True)
        _aws_copy(argv[2], str(destination))
        return 0
    if len(argv) == 4 and argv[1] == "verify":
        with tempfile.TemporaryDirectory(prefix="mneme-s3-readback-") as temporary:
            local = Path(temporary) / "backup.tar.gz"
            _aws_copy(argv[2], str(local))
            actual = _digest(local)
        print(actual)
        return 0 if actual == argv[3] else 1
    print("usage: backup_aws_s3.py copy|fetch SOURCE DEST | verify S3_URI SHA256", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
