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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("artifacts/backup-geo-recovery.json"))
    parser.add_argument("--require-remote", action="store_true")
    args = parser.parse_args()
    copy_command = os.getenv("BACKUP_GEO_COPY_COMMAND", "").strip()
    if args.require_remote and not copy_command:
        parser.error("--require-remote requires BACKUP_GEO_COPY_COMMAND")

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
            subprocess.run([*shlex.split(copy_command), str(archive), str(secondary)], check=True, timeout=300)
            location = "external-command"
        else:
            shutil.copy2(archive, secondary)
            location = "isolated-local-directory-simulation"
        verified = verify_archive(secondary)
        restored = root / "restore-environment"
        extract_verified(secondary, restored)
        restored_content = (restored / "payload/data/files/marker.txt").read_bytes()
        if restored_content != content:
            raise RuntimeError("secondary-location recovery content mismatch")
        report = {
            "status": "completed",
            "location_mode": location,
            "remote_copy_verified": bool(copy_command),
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
    return 0 if report["payload_verified"] and report["manifest_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
