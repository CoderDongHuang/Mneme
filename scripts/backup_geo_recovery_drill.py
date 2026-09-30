#!/usr/bin/env python3
"""Create an encrypted backup and verify isolated recovery in a secondary location."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_restore import create_archive, extract_verified, verify_archive  # noqa: E402


def _split_command(command: str) -> list[str]:
    """Split an operator command without corrupting Windows executable paths."""
    if os.name == "nt":
        return [part.strip('"') for part in shlex.split(command, posix=False)]
    return shlex.split(command)


def _run_remote_verifier(command: str, archive: str, expected_sha256: str) -> str:
    """Ask the remote adapter to read back the copied object and return its digest.

    The adapter receives the destination object path and expected digest. It must
    print the actual SHA-256 as its final output line; this keeps the copy and
    verification responsibilities separate for S3, GCS, or an operator-owned
    replication command.
    """
    try:
        result = subprocess.run(
            [*_split_command(command), archive, expected_sha256],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"remote backup verification failed: {error}") from error
    if result.returncode != 0:
        raise RuntimeError(
            f"remote backup verification failed: {result.stderr[-500:]}"
        )
    digest = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if digest != expected_sha256:
        raise RuntimeError(
            f"remote backup digest mismatch: expected {expected_sha256}, got {digest or '<empty>'}"
        )
    return digest


def _run_command(command: str, *arguments: str) -> None:
    try:
        result = subprocess.run(
            [*_split_command(command), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"remote backup command failed: {error}") from error
    if result.returncode != 0:
        raise RuntimeError(f"remote backup command failed: {result.stderr[-500:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("artifacts/backup-geo-recovery.json"))
    parser.add_argument("--require-remote", action="store_true")
    args = parser.parse_args()
    copy_command = os.getenv("BACKUP_GEO_COPY_COMMAND", "").strip()
    verify_command = os.getenv("BACKUP_GEO_VERIFY_COMMAND", "").strip()
    fetch_command = os.getenv("BACKUP_GEO_FETCH_COMMAND", "").strip()
    remote_destination = os.getenv("BACKUP_GEO_DESTINATION", "").strip()
    if args.require_remote and not copy_command:
        parser.error("--require-remote requires BACKUP_GEO_COPY_COMMAND")
    if args.require_remote and not verify_command:
        parser.error("--require-remote requires BACKUP_GEO_VERIFY_COMMAND")
    if args.require_remote and not fetch_command:
        parser.error("--require-remote requires BACKUP_GEO_FETCH_COMMAND")

    with tempfile.TemporaryDirectory(prefix="mneme-geo-recovery-") as temporary:
        root = Path(temporary)
        source = root / "source"
        (source / "payload/data/files").mkdir(parents=True)
        content = b"mneme secondary-region recovery marker\n"
        (source / "payload/mysql.sql").write_bytes(b"CREATE TABLE recovery_marker(id INT);\n")
        (source / "payload/data/files/marker.txt").write_bytes(content)
        os.environ.setdefault("BACKUP_KEY_VERSION", "drill-v1")
        os.environ.setdefault("BACKUP_KEY_PROVIDER", "configured-command")
        os.environ.setdefault("BACKUP_SIGNING_KEY", "drill-signing-key-at-least-32-bytes")
        os.environ.setdefault("MNEME_DRILL_MASTER_KEY", "drill-master-key-at-least-32-bytes")
        provider = Path(__file__).with_name("backup_key_provider.py").as_posix()
        os.environ.setdefault("BACKUP_KMS_COMMAND", f'"{Path(sys.executable).as_posix()}" "{provider}"')
        archive = root / "primary" / "backup.tar.gz"
        manifest = create_archive(source, archive)
        secondary = root / "secondary" / archive.name
        secondary.parent.mkdir(parents=True)
        if copy_command:
            destination = remote_destination or str(root / "remote-object" / archive.name)
            _run_command(copy_command, str(archive), destination)
            location = "external-command"
        else:
            shutil.copy2(archive, secondary)
            destination = str(secondary)
            location = "isolated-local-directory-simulation"
        source_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        remote_digest = None
        if copy_command and verify_command:
            remote_digest = _run_remote_verifier(verify_command, destination, source_sha256)
        if copy_command and fetch_command:
            _run_command(fetch_command, destination, str(secondary))
        verified = verify_archive(secondary)
        restored = root / "restore-environment"
        extract_verified(secondary, restored)
        restored_content = (restored / "payload/data/files/marker.txt").read_bytes()
        if restored_content != content:
            raise RuntimeError("secondary-location recovery content mismatch")
        report = {
            "status": "completed",
            "location_mode": location,
            "remote_copy_verified": bool(remote_digest == source_sha256),
            "remote_verification_configured": bool(copy_command and verify_command and fetch_command),
            "remote_destination": destination,
            "source_sha256": source_sha256,
            "remote_sha256": remote_digest,
            "envelope_encrypted": bool(manifest["security"].get("envelope_encrypted")),
            "key_provider": manifest["security"].get("key_provider"),
            "key_version": manifest["security"].get("key_version"),
            "manifest_verified": verified["created_at"] == manifest["created_at"],
            "restored_sha256": hashlib.sha256(restored_content).hexdigest(),
            "payload_verified": True,
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["payload_verified"] and report["manifest_verified"] and (not args.require_remote or report["remote_copy_verified"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
