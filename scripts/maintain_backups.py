"""Plan/apply local backup retention under the shared backup/restore lock."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import stat
import sys

try:
    from . import backup_restore as backup
except ImportError:
    import backup_restore as backup


MANAGED = re.compile(r"mneme-\d{8}-\d{6}\.tar\.gz\Z")


def identity(info):
    # Reading archives may update atime on Linux; only mutation/identity fields
    # participate in the change fence. Digests separately protect content.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, getattr(info, 'st_file_attributes', 0))


def directory(path):
    for ancestor in (*reversed(path.parents), path):
        info = ancestor.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise backup.BackupError("unsafe backup directory")
    return (info.st_dev, info.st_ino)


def inventory(root):
    directory(root)
    files = {}
    unknown = 0
    for path in root.iterdir():
        if not MANAGED.fullmatch(path.name):
            unknown += 1
            continue
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise backup.BackupError("unsafe managed backup")
        files[path.name] = info
    return files, unknown


def collect(root, *, protect, keep=3, days=30, apply=False, now=None, compose_files=()):
    """Caller must hold operation_lock, including during inventory and validation."""
    root = Path(root).absolute()
    if type(keep) is not int or keep < 2 or type(days) is not int or days < 1:
        raise backup.BackupError("keep must be at least two and days must be positive")
    if not protect or any(not isinstance(name, str) or not MANAGED.fullmatch(name) for name in protect):
        raise backup.BackupError("name at least one managed rollback backup with --protect")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise backup.BackupError("retention clock requires timezone")
    files, unknown = inventory(root)
    root = root.resolve(strict=True)
    root_identity = directory(root)
    if not set(protect) <= files.keys():
        raise backup.BackupError("protected rollback backup is missing")
    records = []
    for name, info in files.items():
        path = root / name
        manifest = backup.verify_archive(path)
        try:
            created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None or created > now:
                raise ValueError("invalid time")
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise backup.BackupError("backup creation time is invalid") from error
        records.append((created, name, backup.sha256_file(path), info))
    records.sort(reverse=True)
    protected = set(protect) | {record[1] for record in records[:keep]}
    cutoff = now - timedelta(days=days)
    candidates = {name for created, name, _, info in records
                  if name not in protected and created < cutoff and info.st_mtime < cutoff.timestamp()}
    # Hashes alone cannot prove that a remaining encrypted backup can be restored.
    # Check every survivor's decryption and migration compatibility before deleting.
    for _, name, _, _ in records:
        if name not in candidates:
            manifest = backup.verify_archive(root / name, decrypt=True)
            backup.validate_restore_schema(manifest)
            backup.validate_restore_model_keys(manifest, list(compose_files))
    if apply:
        if directory(root) != root_identity:
            raise backup.BackupError("backup directory changed; plan again")
        current, _ = inventory(root)
        if ({name: identity(info) for name, info in current.items()}
                != {name: identity(info) for name, info in files.items()}):
            raise backup.BackupError("backup inventory changed; plan again")
        for _, name, digest, _ in records:
            if backup.sha256_file(root / name) != digest:
                raise backup.BackupError("backup content changed; plan again")
        for _, name, digest, info in records:
            if name in candidates:
                if directory(root) != root_identity:
                    raise backup.BackupError("backup directory changed before deletion")
                path = root / name
                if identity(path.lstat()) != identity(info) or backup.sha256_file(path) != digest:
                    raise backup.BackupError("backup changed before deletion")
                path.unlink()
    return {"status": "completed" if apply else "planned", "files": len(candidates),
            "bytes": sum(info.st_size for _, name, _, info in records if name in candidates),
            "retained": len(records) - len(candidates), "unknown": unknown}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="backups")
    parser.add_argument("--compose-file", action="append", default=[], help="Deployment Compose file; repeatable")
    parser.add_argument("--protect", action="append", required=True, help="Rollback filename to always preserve; repeatable")
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        with backup.operation_lock():
            print(json.dumps(collect(args.directory, protect=args.protect, keep=args.keep,
                                     days=args.days, apply=args.apply, compose_files=args.compose_file)))
        return 0
    except (OSError, ValueError, TypeError, KeyError, backup.BackupError):
        print("FAIL: backup retention blocked; check directory, rollback protection, archives and keys", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
