import io
import json
import os
import subprocess
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


def test_backup_archive_preserves_redis_stream_snapshot(tmp_path):
    staging = tmp_path / "staging"
    (staging / "payload/data/redis").mkdir(parents=True)
    (staging / "payload/mysql.sql").write_text("SELECT 1;", encoding="utf-8")
    snapshot = b"redis-snapshot-with-pending-reflections"
    (staging / "payload/data/redis/dump.rdb").write_bytes(snapshot)
    archive = tmp_path / "redis-backup.tar.gz"

    manifest = create_archive(staging, archive)
    assert "payload/data/redis/dump.rdb" in {entry["path"] for entry in manifest["files"]}
    extract_verified(archive, tmp_path / "restored")
    assert (tmp_path / "restored/payload/data/redis/dump.rdb").read_bytes() == snapshot


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


def test_envelope_archive_uses_external_key_provider(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    (staging / "payload/data/files").mkdir(parents=True)
    (staging / "payload/mysql.sql").write_text("sql", encoding="utf-8")
    provider = Path(__file__).parents[2] / "scripts" / "backup_key_provider.py"
    monkeypatch.setenv("BACKUP_KMS_COMMAND", f'"{sys.executable}" "{provider}"')
    monkeypatch.setenv("MNEME_DRILL_MASTER_KEY", "master-key-for-envelope-test")
    monkeypatch.setenv("BACKUP_KEY_VERSION", "test-v1")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "signing-secret-for-tests-5678")
    archive = tmp_path / "envelope.tar.gz"
    manifest = create_archive(staging, archive)
    assert manifest["security"]["envelope_encrypted"] is True
    assert manifest["security"]["key_provider"] == "external-command"
    monkeypatch.delenv("BACKUP_KMS_COMMAND")
    with pytest.raises(BackupError, match="BACKUP_KMS_COMMAND"):
        extract_verified(archive, tmp_path / "without-provider")
    monkeypatch.setenv("BACKUP_KMS_COMMAND", f'"{sys.executable}" "{provider}"')
    extract_verified(archive, tmp_path / "with-provider")


def test_production_restore_rejects_unprotected_archive(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    monkeypatch.setenv("BACKUP_REQUIRE_PROTECTION", "true")
    with pytest.raises(BackupError, match="protected restore"):
        verify_archive(archive)


def test_geo_protocol_requires_independent_readback_verification(tmp_path, monkeypatch):
    drill = Path(__file__).parents[2] / "scripts" / "backup_geo_recovery_drill.py"
    adapter = Path(__file__).parents[2] / "scripts" / "backup_local_geo_adapter.py"
    monkeypatch.setenv("BACKUP_GEO_COPY_COMMAND", f'"{sys.executable}" "{adapter}" copy')
    monkeypatch.setenv("BACKUP_GEO_VERIFY_COMMAND", f'"{sys.executable}" "{adapter}" verify')
    monkeypatch.setenv("BACKUP_GEO_FETCH_COMMAND", f'"{sys.executable}" "{adapter}" fetch')
    report = tmp_path / "geo.json"
    result = subprocess.run(
        [sys.executable, str(drill), "--require-remote", "--report", str(report)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["remote_copy_verified"] is True
    assert data["source_sha256"] == data["remote_sha256"]


def test_geo_protocol_requires_fetch_command(tmp_path, monkeypatch):
    drill = Path(__file__).parents[2] / "scripts" / "backup_geo_recovery_drill.py"
    adapter = Path(__file__).parents[2] / "scripts" / "backup_local_geo_adapter.py"
    monkeypatch.setenv("BACKUP_GEO_COPY_COMMAND", f'"{sys.executable}" "{adapter}" copy')
    monkeypatch.setenv("BACKUP_GEO_VERIFY_COMMAND", f'"{sys.executable}" "{adapter}" verify')
    monkeypatch.delenv("BACKUP_GEO_FETCH_COMMAND", raising=False)
    result = subprocess.run(
        [sys.executable, str(drill), "--require-remote", "--report", str(tmp_path / "geo.json")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "BACKUP_GEO_FETCH_COMMAND" in result.stderr


def test_geo_protocol_rejects_remote_digest_mismatch(tmp_path, monkeypatch):
    drill = Path(__file__).parents[2] / "scripts" / "backup_geo_recovery_drill.py"
    adapter = Path(__file__).parents[2] / "scripts" / "backup_local_geo_adapter.py"
    wrong_digest = "0" * 64
    verifier = tmp_path / "wrong_verifier.py"
    verifier.write_text(f'print("{wrong_digest}")\n', encoding="utf-8")
    monkeypatch.setenv("BACKUP_GEO_COPY_COMMAND", f'"{sys.executable}" "{adapter}" copy')
    monkeypatch.setenv("BACKUP_GEO_VERIFY_COMMAND", f'"{sys.executable}" "{verifier}"')
    monkeypatch.setenv("BACKUP_GEO_FETCH_COMMAND", f'"{sys.executable}" "{adapter}" fetch')
    result = subprocess.run(
        [sys.executable, str(drill), "--require-remote", "--report", str(tmp_path / "geo.json")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "remote backup digest mismatch" in result.stderr


def test_geo_protocol_rejects_partial_remote_configuration(tmp_path, monkeypatch):
    drill = Path(__file__).parents[2] / "scripts" / "backup_geo_recovery_drill.py"
    adapter = Path(__file__).parents[2] / "scripts" / "backup_local_geo_adapter.py"
    monkeypatch.setenv("BACKUP_GEO_COPY_COMMAND", f'"{sys.executable}" "{adapter}" copy')
    monkeypatch.delenv("BACKUP_GEO_VERIFY_COMMAND", raising=False)
    monkeypatch.setenv("BACKUP_GEO_FETCH_COMMAND", f'"{sys.executable}" "{adapter}" fetch')
    result = subprocess.run(
        [sys.executable, str(drill), "--report", str(tmp_path / "geo.json")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "must be configured together" in result.stderr


def test_geo_protocol_preserves_windows_command_paths(monkeypatch):
    from scripts import backup_geo_recovery_drill

    monkeypatch.setattr(backup_geo_recovery_drill.os, "name", "nt")
    assert backup_geo_recovery_drill._split_command(
        '"C:\\Program Files\\Python\\python.exe" scripts\\adapter.py copy'
    ) == ["C:\\Program Files\\Python\\python.exe", "scripts\\adapter.py", "copy"]


@pytest.mark.parametrize("name", [
    "C:/escape", "C:escape", "//server/share/file", "payload/data/files/file:stream",
    "payload/data/files/CON.txt", "payload/data/files/aux", "payload/data/files/LPT1.log",
    "payload/data/files/name.", "payload/data/files/name ", "payload/data/files/a\\..\\escape",
    "payload/data/files/./file", "payload//data/files/file", "payload/data/files/evil?name",
])
def test_archive_rejects_unsafe_windows_and_ambiguous_paths(tmp_path, name):
    archive = tmp_path / "unsafe.tar.gz"
    write_raw_archive(archive, {name: b"bad", "manifest.json": b"{}"})
    with pytest.raises(BackupError, match="unsafe archive path"):
        verify_archive(archive)


def test_extraction_refuses_existing_contents_without_overwriting(tmp_path):
    archive = make_archive(tmp_path)
    destination = tmp_path / "restored"
    (destination / "payload/data/files").mkdir(parents=True)
    victim = destination / "payload/data/files/note.txt"
    victim.write_bytes(b"user data")
    with pytest.raises(BackupError, match="empty isolated directory"):
        extract_verified(archive, destination)
    assert victim.read_bytes() == b"user data"
    assert not (destination / "payload/mysql.sql").exists()


def directory_link(link, target):
    if os.name == "nt":
        # Junction creation does not require the Windows symlink privilege.
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("ancestor", [False, True])
def test_extraction_rejects_destination_links_and_junction_ancestors(tmp_path, ancestor):
    archive = make_archive(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked"
    directory_link(link, outside)
    destination = link / "restore" if ancestor else link
    with pytest.raises(BackupError, match="symlink or reparse point"):
        extract_verified(archive, destination)
    assert not list(outside.iterdir())


def test_extraction_rejects_preexisting_nested_escape(tmp_path):
    archive = make_archive(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "restore"
    (destination / "payload/data").mkdir(parents=True)
    directory_link(destination / "payload/data/files", outside)
    with pytest.raises(BackupError, match="empty isolated directory"):
        extract_verified(archive, destination)
    assert not list(outside.iterdir())


def test_restore_provider_preserves_windows_command_paths(monkeypatch):
    from scripts import backup_restore

    monkeypatch.setattr(backup_restore.os, "name", "nt")
    assert backup_restore.split_command(
        '"C:\\Program Files\\Python\\python.exe" "D:\\Backup Tools\\provider.py" unwrap v1'
    ) == ["C:\\Program Files\\Python\\python.exe", "D:\\Backup Tools\\provider.py", "unwrap", "v1"]
