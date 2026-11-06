"""Offline collection of crash leftovers in the exclusively owned upload namespace."""
import argparse
import json
import math
from pathlib import Path
import re
import stat
import sys
import time


STAGING_NAME = ".mneme-staging"
MANAGED_NAME = re.compile(r"mneme-upload-[a-z0-9_]{8}\.[a-z0-9]{1,10}\Z")


def _linked(attributes):
    return (stat.S_ISLNK(attributes.st_mode)
            or getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _directory(path):
    for parent in (*reversed(path.parents), path):
        attributes = parent.lstat()
        if _linked(attributes) or not stat.S_ISDIR(attributes.st_mode):
            raise ValueError("unsafe_staging_directory")


def staging_directory(upload_dir: Path, *, create=False):
    root = upload_dir.absolute() / STAGING_NAME
    # Check existing ancestors before mkdir, including Windows junctions.
    for parent in (*reversed(root.parents), root):
        if parent.exists() or parent.is_symlink():
            attributes = parent.lstat()
            if _linked(attributes) or not stat.S_ISDIR(attributes.st_mode):
                raise ValueError("unsafe_staging_directory")
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _directory(root)
    return root


def collect(upload_dir: Path, *, hours=24, apply=False, now=None):
    if type(hours) is not int or hours < 1:
        raise ValueError("invalid_retention_hours")
    clock = time.time() if now is None else now
    if not math.isfinite(clock):
        raise ValueError("invalid_clock")
    root = staging_directory(upload_dir)
    candidates, retained, unknown = [], 0, 0
    if root.exists():
        _directory(root)
        for path in root.iterdir():
            attributes = path.lstat()
            if _linked(attributes):
                raise ValueError("unsafe_staging_entry")
            if not MANAGED_NAME.fullmatch(path.name) or not stat.S_ISREG(attributes.st_mode):
                unknown += 1
            elif attributes.st_nlink != 1:
                raise ValueError("unsafe_staging_entry")
            elif attributes.st_mtime < clock - hours * 3600:
                candidates.append((path, attributes))
            else:
                retained += 1
    if apply:
        # Validate the entire snapshot before unlinking anything. Writers must be
        # stopped by the host launcher; age alone never proves a file is unused.
        for path, attributes in candidates:
            if path.lstat() != attributes:
                raise ValueError("staging_changed_stop_writers")
        for path, attributes in candidates:
            _directory(root)
            if path.lstat() != attributes:
                raise ValueError("staging_changed_stop_writers")
            path.unlink()
    return {"status": "completed" if apply else "planned", "files": len(candidates),
            "bytes": sum(attributes.st_size for _, attributes in candidates),
            "retained": retained, "unknown": unknown}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload-dir", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply and not args.offline:
            raise ValueError("offline_required")
        print(json.dumps(collect(Path(args.upload_dir), hours=args.hours, apply=args.apply)))
        return 0
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "code": "upload_maintenance_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
