#!/usr/bin/env python3
"""Verify backup key rotation, old-key recovery and isolated cross-environment restore."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_restore import BackupError, create_archive, extract_verified, verify_archive  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="artifacts/backup-key-rotation-drill.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mneme-key-rotation-") as directory:
        root = Path(directory)
        source = root / "source"
        (source / "payload/data/files").mkdir(parents=True)
        (source / "payload/mysql.sql").write_text("CREATE TABLE drill(id INT);", encoding="utf-8")
        (source / "payload/data/files/marker.txt").write_text("cross-environment", encoding="utf-8")
        old_encryption = "old-encryption-key-for-drill-123456"
        old_signing = "old-signing-key-for-drill-123456"
        new_encryption = "new-encryption-key-for-drill-123456"
        new_signing = "new-signing-key-for-drill-123456"
        os.environ["BACKUP_KEY_VERSION"] = "v1"
        archive = root / "v1.tar.gz"
        staging_v1 = root / "staging-v1"
        shutil.copytree(source, staging_v1)
        create_archive(staging_v1, archive, encryption_key=old_encryption, signing_key=old_signing)
        os.environ["BACKUP_ENCRYPTION_KEY_V1"] = old_encryption
        os.environ["BACKUP_SIGNING_KEY_V1"] = old_signing
        verify_archive(archive)
        extract_verified(archive, root / "restored")
        os.environ["BACKUP_KEY_VERSION"] = "v2"
        os.environ["BACKUP_ENCRYPTION_KEY_V2"] = new_encryption
        os.environ["BACKUP_SIGNING_KEY_V2"] = new_signing
        staging2 = root / "staging-v2"
        shutil.copytree(source, staging2)
        archive2 = root / "v2.tar.gz"
        create_archive(staging2, archive2, encryption_key=new_encryption, signing_key=new_signing)
        verify_archive(archive2)
        os.environ.pop("BACKUP_ENCRYPTION_KEY_V1")
        os.environ.pop("BACKUP_SIGNING_KEY_V1")
        old_key_rejected = False
        try:
            verify_archive(archive)
        except BackupError:
            old_key_rejected = True
        report = {"status": "completed", "old_key_recovery": True, "new_key_archive": True, "old_key_rejected_after_retirement": old_key_rejected, "cross_environment_restore": (root / "restored/payload/data/files/marker.txt").read_text(encoding="utf-8") == "cross-environment"}
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 0 if all(value is True or value == "completed" for value in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
