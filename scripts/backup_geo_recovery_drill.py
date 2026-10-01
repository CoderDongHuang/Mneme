#!/usr/bin/env python3
"""Create an encrypted backup and verify isolated recovery in a secondary location."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import contextmanager

if __package__:
    from .backup_restore import BackupError, create_archive, extract_verified, verify_archive, sha256_file, split_command, _versioned_secret
    from .backup_aws_preflight import preflight
else:
    from backup_restore import BackupError, create_archive, extract_verified, verify_archive, sha256_file, split_command, _versioned_secret
    from backup_aws_preflight import preflight


def _split_command(command: str) -> list[str]:
    """Split an operator command without corrupting Windows executable paths."""
    return split_command(command)


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


@contextmanager
def _environment():
    original = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _protected_manifest(archive: Path) -> dict:
    manifest = verify_archive(archive)
    security = manifest.get("security", {})
    if any(security.get(field) is not True for field in ("encrypted", "signed", "envelope_encrypted")):
        raise BackupError("recovery requires a signed, envelope-encrypted archive")
    return manifest


def _recover(args, copy_command, verify_command, fetch_command, remote_destination) -> dict:
    with _environment(), tempfile.TemporaryDirectory(prefix="mneme-geo-recovery-") as temporary:
        root = Path(temporary)
        os.environ["BACKUP_REQUIRE_PROTECTION"] = "true"
        cloud_evidence = None
        if args.require_cloud:
            os.environ["BACKUP_RECOVERY_REGION"] = args.recovery_region
            provider = Path(__file__).with_name("backup_aws_kms.py").as_posix()
            os.environ["BACKUP_KMS_COMMAND"] = f'"{Path(sys.executable).as_posix()}" "{provider}"'
            os.environ["BACKUP_KEY_PROVIDER"] = "aws-kms"
            adapter = Path(__file__).with_name("backup_aws_s3.py").as_posix()
            command = f'"{Path(sys.executable).as_posix()}" "{adapter}"'
            copy_command, verify_command, fetch_command = (f"{command} {action}" for action in ("copy", "verify", "fetch"))
        elif args.archive is None:
            # Local protocol drills use fresh, ephemeral secrets, never fixed defaults.
            os.environ.setdefault("BACKUP_SIGNING_KEY", base64.b64encode(os.urandom(32)).decode())
            os.environ.setdefault("BACKUP_KEY_VERSION", "drill-v1")
            if not os.getenv("BACKUP_KMS_COMMAND", "").strip():
                os.environ["MNEME_DRILL_MASTER_KEY"] = base64.b64encode(os.urandom(32)).decode()
                provider = Path(__file__).with_name("backup_key_provider.py").as_posix()
                os.environ["BACKUP_KMS_COMMAND"] = f'"{Path(sys.executable).as_posix()}" "{provider}"'
                os.environ["BACKUP_KEY_PROVIDER"] = "local-drill-provider"

        if args.archive:
            # Snapshot the supplied archive without changing the operator's file.
            archive = root / "primary" / "backup.tar.gz"
            archive.parent.mkdir()
            shutil.copyfile(args.archive, archive)
            manifest = _protected_manifest(archive)
            version = manifest["security"]["key_version"]
        else:
            version = os.getenv("BACKUP_KEY_VERSION", "").strip()
            if not version:
                raise BackupError("cloud synthetic recovery requires BACKUP_KEY_VERSION")
            if not _versioned_secret("BACKUP_SIGNING_KEY", version):
                raise BackupError("synthetic recovery requires a configured BACKUP_SIGNING_KEY")
        if args.require_cloud:
            cloud_evidence = preflight(args.primary_region, args.recovery_region, remote_destination, version)
            # Pin the observed key ARN so alias changes cannot select a different key.
            key_name = f"BACKUP_KMS_KEY_ID_{version.upper().replace('-', '_')}"
            os.environ[key_name] = cloud_evidence["kms_key"]["Arn"]
        if args.archive is None:
            source = root / "source"
            (source / "payload/data/files").mkdir(parents=True)
            (source / "payload/mysql.sql").write_bytes(b"CREATE TABLE recovery_marker(id INT);\n")
            (source / "payload/data/files/marker.txt").write_bytes(b"mneme secondary-region recovery marker\n")
            archive = root / "primary" / "backup.tar.gz"
            create_archive(
                source, archive, metadata={"data_mode": "controlled-synthetic"},
                signing_key=_versioned_secret("BACKUP_SIGNING_KEY", version),
            )
            manifest = _protected_manifest(archive)

        secondary = root / "secondary" / archive.name
        secondary.parent.mkdir(parents=True)
        source_sha256 = sha256_file(archive)
        remote_digest = None
        if copy_command:
            destination = remote_destination or str(root / "remote-object" / archive.name)
            _run_command(copy_command, str(archive), destination)
            remote_digest = _run_remote_verifier(verify_command, destination, source_sha256)
            _run_command(fetch_command, destination, str(secondary))
            location = "aws-s3-secondary-region" if args.require_cloud else "external-command"
        else:
            shutil.copy2(archive, secondary)
            destination = str(secondary)
            location = "isolated-local-directory-simulation"
        fetched_digest = sha256_file(secondary)
        if fetched_digest != source_sha256:
            raise BackupError("fetched backup digest differs from source archive")
        verified = _protected_manifest(secondary)
        if verified != manifest:
            raise BackupError("recovered manifest differs from source manifest")
        restored = root / "restore-environment"
        extract_verified(secondary, restored)
        restored_files = [
            {"path": entry["path"], "sha256": sha256_file(restored / entry["path"])}
            for entry in manifest["files"]
        ]
        if any(actual["sha256"] != entry.get("plaintext_sha256") for actual, entry in zip(restored_files, manifest["files"])):
            raise BackupError("restored plaintext inventory digest mismatch")
        security = manifest["security"]
        return {
            "status": "completed", "data_mode": "actual-archive" if args.archive else "controlled-synthetic",
            "recovery_scope": "isolated-plaintext-extraction", "location_mode": location,
            "cloud_preflight": cloud_evidence, "cloud_verified": bool(cloud_evidence),
            "remote_copy_verified": remote_digest == source_sha256,
            "remote_verification_configured": bool(copy_command and verify_command and fetch_command),
            "remote_destination": destination, "source_sha256": source_sha256,
            "remote_sha256": remote_digest, "fetched_sha256": fetched_digest,
            "envelope_encrypted": True, "key_provider": security.get("key_provider"),
            "key_version": security["key_version"], "manifest_verified": True,
            "restored_file_count": len(restored_files), "restored_files": restored_files,
            "restored_sha256": next((entry["sha256"] for entry in restored_files if entry["path"] == "payload/data/files/marker.txt"), None),
            "all_plaintext_digests_verified": True, "payload_verified": True,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("artifacts/backup-geo-recovery.json"))
    parser.add_argument("--require-remote", action="store_true")
    parser.add_argument("--archive", type=Path, help="recover a supplied protected envelope archive instead of synthetic data")
    parser.add_argument("--require-cloud", action="store_true", help="require observed AWS preflight and built-in KMS/S3 adapters")
    parser.add_argument("--primary-region", default=os.getenv("BACKUP_PRIMARY_REGION", ""))
    parser.add_argument("--recovery-region", default=os.getenv("BACKUP_RECOVERY_REGION", ""))
    parser.add_argument("--destination", default=os.getenv("BACKUP_GEO_DESTINATION", ""))
    args = parser.parse_args(argv)
    copy_command = os.getenv("BACKUP_GEO_COPY_COMMAND", "").strip()
    verify_command = os.getenv("BACKUP_GEO_VERIFY_COMMAND", "").strip()
    fetch_command = os.getenv("BACKUP_GEO_FETCH_COMMAND", "").strip()
    remote_destination = args.destination.strip()
    if args.require_cloud:
        if not args.primary_region or not args.recovery_region or args.primary_region == args.recovery_region:
            parser.error("--require-cloud requires distinct explicit primary and recovery regions")
        if not remote_destination:
            parser.error("--require-cloud requires an explicit S3 destination")
        if any((copy_command, verify_command, fetch_command)):
            parser.error("--require-cloud uses built-in AWS adapters; remove BACKUP_GEO_*_COMMAND overrides")
    if args.require_remote and not args.require_cloud and not copy_command:
        parser.error("--require-remote requires BACKUP_GEO_COPY_COMMAND")
    if args.require_remote and not args.require_cloud and not verify_command:
        parser.error("--require-remote requires BACKUP_GEO_VERIFY_COMMAND")
    if args.require_remote and not args.require_cloud and not fetch_command:
        parser.error("--require-remote requires BACKUP_GEO_FETCH_COMMAND")
    configured_remote = [copy_command, verify_command, fetch_command]
    if any(configured_remote) and not all(configured_remote):
        parser.error(
            "BACKUP_GEO_COPY_COMMAND, BACKUP_GEO_VERIFY_COMMAND, and "
            "BACKUP_GEO_FETCH_COMMAND must be configured together"
        )

    try:
        report = _recover(args, copy_command, verify_command, fetch_command, remote_destination)
    except (RuntimeError, OSError, ValueError) as error:
        report = {
            "status": "failed", "data_mode": "actual-archive" if args.archive else "controlled-synthetic",
            "cloud_verified": False, "payload_verified": False, "error": str(error),
        }
        print(f"ERROR: {error}", file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
