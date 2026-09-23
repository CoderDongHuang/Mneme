import io
import json
import sys
import tarfile
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.backup_restore import (  # noqa: E402
    BackupError,
    create_archive,
    extract_verified,
    verify_archive,
)


def make_archive(tmp_path: Path) -> Path:
    staging = tmp_path / "staging"
    (staging / "payload/data/files").mkdir(parents=True)
    (staging / "payload/mysql.sql").write_text("CREATE TABLE marker(id INT);", encoding="utf-8")
    (staging / "payload/data/files/note.txt").write_text("QZ-7294", encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"
    create_archive(staging, archive)
    return archive


def write_raw_archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))


def test_archive_round_trip_verification(tmp_path):
    manifest = verify_archive(make_archive(tmp_path))
    assert manifest["format"] == "mneme-backup"
    assert {entry["path"] for entry in manifest["files"]} == {
        "payload/mysql.sql", "payload/data/files/note.txt"
    }


def test_archive_rejects_tampered_content(tmp_path):
    valid = make_archive(tmp_path)
    with tarfile.open(valid, "r:gz") as source:
        manifest = source.extractfile("manifest.json").read()
    tampered = tmp_path / "tampered.tar.gz"
    write_raw_archive(tampered, {
        "manifest.json": manifest,
        "payload/mysql.sql": b"tampered",
        "payload/data/files/note.txt": b"QZ-7294",
    })
    with pytest.raises(BackupError, match="checksum or size mismatch"):
        verify_archive(tampered)


def test_archive_rejects_path_traversal(tmp_path):
    archive = tmp_path / "traversal.tar.gz"
    write_raw_archive(archive, {"../escape": b"bad", "manifest.json": b"{}"})
    with pytest.raises(BackupError, match="unsafe archive path"):
        verify_archive(archive)


def test_archive_rejects_unknown_or_missing_files(tmp_path):
    valid = make_archive(tmp_path)
    with tarfile.open(valid, "r:gz") as source:
        manifest = json.loads(source.extractfile("manifest.json").read())
        sql = source.extractfile("payload/mysql.sql").read()
    archive = tmp_path / "missing.tar.gz"
    write_raw_archive(archive, {
        "manifest.json": json.dumps(manifest).encode(),
        "payload/mysql.sql": sql,
        "payload/data/files/unknown.txt": b"unknown",
    })
    with pytest.raises(BackupError, match="inventory mismatch"):
        verify_archive(archive)


def test_encrypted_signed_archive_round_trip(tmp_path, monkeypatch):
    encryption_key = "encryption-secret-for-tests-1234"
    signing_key = "signing-secret-for-tests-5678"
    staging = tmp_path / "staging"
    (staging / "payload/data/files").mkdir(parents=True)
    (staging / "payload/mysql.sql").write_text("CREATE TABLE marker(id INT);", encoding="utf-8")
    (staging / "payload/data/files/note.txt").write_text("private", encoding="utf-8")
    archive = tmp_path / "protected.tar.gz"
    create_archive(staging, archive, encryption_key=encryption_key, signing_key=signing_key)
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("BACKUP_SIGNING_KEY", signing_key)
    manifest = verify_archive(archive)
    assert manifest["security"]["encrypted"] is True
    assert manifest["security"]["signed"] is True
    destination = tmp_path / "restored"
    extract_verified(archive, destination)
    assert (destination / "payload/data/files/note.txt").read_text(encoding="utf-8") == "private"


def test_signed_archive_rejects_wrong_key(tmp_path, monkeypatch):
    archive = tmp_path / "protected.tar.gz"
    staging = tmp_path / "staging"
    (staging / "payload").mkdir(parents=True)
    (staging / "payload/mysql.sql").write_text("sql", encoding="utf-8")
    create_archive(staging, archive, signing_key="signing-secret-for-tests-5678")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "wrong-key-that-is-long-enough")
    with pytest.raises(BackupError, match="signature mismatch"):
        verify_archive(archive)


def test_encrypted_archive_rejects_wrong_encryption_key(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    (staging / "payload").mkdir(parents=True)
    (staging / "payload/mysql.sql").write_text("sql", encoding="utf-8")
    archive = tmp_path / "encrypted.tar.gz"
    create_archive(staging, archive, encryption_key="encryption-secret-for-tests-1234")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "different-encryption-key-123456")
    destination = tmp_path / "restored"
    with pytest.raises(BackupError, match="decryption authentication failed"):
        extract_verified(archive, destination)
