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


def test_backup_restores_published_generation_and_deletion_fence(tmp_path):
    from app.knowledge.generations import GenerationStore, StaleGeneration

    staging = tmp_path / "generation-staging"
    database = staging / "payload/python-agent/data/index-generations.sqlite3"
    store = GenerationStore(database)
    store.begin("backup-user", "kb", "doc", 7)
    with store.writing("backup-user", "kb", "doc", 7):
        pass
    store.tombstone("deleted-user")
    (staging / "payload/mysql.sql").write_text("-- matched MySQL snapshot")
    archive = tmp_path / "generations.tar.gz"
    create_archive(staging, archive)
    target = tmp_path / "restored-generations"
    extract_verified(archive, target)
    restored = GenerationStore(target / "payload/python-agent/data/index-generations.sqlite3")
    assert restored.snapshot("backup-user")["libraries"]["kb"]["documents"]["doc"]["active"] == 7
    with pytest.raises(StaleGeneration):
        restored.begin("backup-user", "kb", "doc", 7)
    with pytest.raises(StaleGeneration):
        restored.begin("deleted-user", "kb", "late-doc", 8)
    assert restored.begin("backup-user", "kb", "doc", 8) == 8


@pytest.mark.parametrize("production", [False, True])
def test_model_key_restore_preflight_requires_original_versions(monkeypatch, production):
    from scripts import backup_restore as module

    env = {"MODEL_CONFIG_ENCRYPTION_KEY": "new-independent-model-secret-12345678",
           "JWT_SECRET": "jwt-secret-completely-different-12345678",
           "MODEL_CONFIG_KEY_VERSION": "v3", "MNEME_PRODUCTION": str(production).lower(),
           "MODEL_CONFIG_PREVIOUS_KEYS": json.dumps({"v2": "original-model-secret-at-least-32-chars"})}
    calls = []

    def compose(files, *args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 0, json.dumps({"services": {"java-gateway": {"environment": env}}}).encode())

    monkeypatch.setattr(module, "run_compose", compose)
    manifest = {"metadata": {"model_config_keys": {"required_versions": ["v2", "v3"]}}}
    module.validate_restore_model_keys(manifest, [])
    env["MODEL_CONFIG_PREVIOUS_KEYS"] = "{}"
    with pytest.raises(BackupError, match="unavailable model key versions") as error:
        module.validate_restore_model_keys(manifest, [])
    assert env["MODEL_CONFIG_ENCRYPTION_KEY"] not in str(error.value)
    assert all(call == ("config", "--format", "json") for call in calls)


@pytest.mark.parametrize("spec", [None, {}, {"required_versions": "v2"}, {"required_versions": ["bad.version"]}, {"required_versions": [1]}])
def test_restore_rejects_invalid_model_key_metadata(monkeypatch, spec):
    from scripts import backup_restore as module

    def forbidden(*args, **kwargs):
        pytest.fail("invalid metadata must not access deployment or stop services")

    monkeypatch.setattr(module, "run_compose", forbidden)
    # Explicit null is treated as legacy metadata, so use schema <21 only there.
    if spec is None:
        module.validate_restore_model_keys({"metadata": {"application_schema_max": 20}}, [])
    else:
        with pytest.raises(BackupError, match="versions are invalid"):
            module.validate_restore_model_keys({"metadata": {"model_config_keys": spec}}, [])


def test_restore_missing_key_fails_before_any_service_is_stopped(tmp_path, monkeypatch):
    import argparse
    from scripts import backup_restore as module

    manifest = {"metadata": {"model_config_keys": {"required_versions": ["legacy-v1"]}}}
    monkeypatch.setattr(module, "verify_archive", lambda archive: manifest)
    monkeypatch.setattr(module, "validate_restore_schema", lambda value: None)
    env = {"MODEL_CONFIG_ENCRYPTION_KEY": "production-new-independent-secret-12345",
           "MODEL_CONFIG_PREVIOUS_KEYS": "{}", "MNEME_PRODUCTION": "true"}
    monkeypatch.setattr(module, "run_compose", lambda files, *args, **kwargs:
                        subprocess.CompletedProcess([], 0, json.dumps({"services": {"java-gateway": {"environment": env}}}).encode())
                        if args == ("config", "--format", "json") else pytest.fail("must not stop services"))
    with pytest.raises(BackupError, match="unavailable model key versions"):
        module._restore(argparse.Namespace(yes=True, archive=str(tmp_path / "archive"), compose_file=[]))


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


@pytest.mark.parametrize("rollback_fails", [False, True])
@pytest.mark.parametrize("report_fails", [False, True])
def test_failed_restore_recovers_previous_stores_or_keeps_services_stopped(tmp_path, monkeypatch, rollback_fails, report_fails):
    from types import SimpleNamespace
    from scripts import backup_restore as module

    archive = make_archive(tmp_path)
    live = tmp_path / "live"
    live.mkdir()
    (live / "note.txt").write_text("previous-data")
    monkeypatch.setattr(module, "DATA_SOURCES", {"payload/data/files": live})
    monkeypatch.setattr(module, "stop_application_services", lambda _: None)
    restarts = []
    monkeypatch.setattr(module, "start_application_services", lambda _: restarts.append(True))
    monkeypatch.setattr(module, "wait_for_mysql", lambda _: None)
    import zlib
    migration = module.PROJECT_ROOT / "java-gateway/src/main/resources/db/migration/V1__initial_schema.sql"
    migration = next(migration.parent.glob("V1__*.sql"))
    checksum = 0
    for line in migration.read_text(encoding="utf-8-sig").splitlines():
        checksum = zlib.crc32(line.encode("utf-8"), checksum)
    if checksum >= 2**31:
        checksum -= 2**32
    def compose(*args, **kwargs):
        content = (f"1\t{checksum}\t1\t{migration.name}\n".encode()
                   if "flyway_schema_history" in str(args) else b"previous-sql")
        return SimpleNamespace(stdout=content)
    monkeypatch.setattr(module, "run_compose", compose)
    calls = []

    def apply(_, extracted):
        calls.append((extracted / "payload/mysql.sql").read_bytes())
        if len(calls) == 1:
            (live / "note.txt").write_text("half-restored")
            raise OSError("injected import failure")
        if rollback_fails:
            raise OSError("injected rollback failure")
        module.replace_data_directories(extracted)

    monkeypatch.setattr(module, "apply_restore_payload", apply)
    report = tmp_path / "report.json"
    original_write = Path.write_text

    def write(path, content, *args, **kwargs):
        if report_fails and path == report.with_suffix(".tmp") and calls:
            raise OSError("injected report disk failure")
        return original_write(path, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    args = SimpleNamespace(yes=True, archive=str(archive), compose_file=[], report=str(report))
    with pytest.raises(BackupError, match="services remain stopped" if rollback_fails else "previous data restored"):
        module.restore(args)
    assert len(calls) == 2 and calls[-1] == b"previous-sql"
    result = json.loads(report.read_text())
    assert Path(result["recovery_archive"]).is_file()
    if not report_fails:
        assert result["status"] == ("rollback_failed_services_stopped" if rollback_fails else "rolled_back")
    assert restarts == ([] if rollback_fails else [True])
    if not rollback_fails:
        assert (live / "note.txt").read_text() == "previous-data"


def test_restore_rejects_future_application_schema_before_stopping_services(monkeypatch):
    from scripts import backup_restore as module
    with pytest.raises(BackupError, match="newer"):
        module.validate_restore_schema({"metadata": {"application_schema_max": module.supported_schema_version() + 1}})


def test_restore_checks_actual_database_migration_checksums(tmp_path, monkeypatch):
    import zlib
    from scripts import backup_restore as module
    directory = tmp_path / "java-gateway/src/main/resources/db/migration"
    directory.mkdir(parents=True)
    script = directory / "V1__initial.sql"
    script.write_bytes(b"\xef\xbb\xbfCREATE TABLE sample(id INT);\r\nSELECT 1;\r\n")
    checksum = zlib.crc32(b"CREATE TABLE sample(id INT);SELECT 1;")
    if checksum >= 2**31:
        checksum -= 2**32
    metadata = {"application_schema_max": 1, "schema_history_format": 1,
                "flyway_schema_history": [{"version": 1, "checksum": checksum, "script": script.name}]}
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    module.validate_restore_schema({"metadata": metadata})
    script.write_text("CREATE TABLE changed(id TEXT);", encoding="utf-8")
    with pytest.raises(BackupError, match="checksum differs"):
        module.validate_restore_schema({"metadata": metadata})
    metadata["flyway_schema_history"].append(metadata["flyway_schema_history"][0])
    with pytest.raises(BackupError):
        module.validate_restore_schema({"metadata": metadata})


def test_backup_restore_operations_cannot_overlap(tmp_path, monkeypatch):
    from scripts import backup_restore as module
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    with module.operation_lock():
        with pytest.raises(BackupError, match="another backup/restore"):
            with module.operation_lock():
                pytest.fail("overlapping operation entered")
    assert not (tmp_path / ".backup-restore.lock").exists()


def test_archive_creation_never_overwrites_existing_backup(tmp_path):
    archive = make_archive(tmp_path)
    original = archive.read_bytes()
    with pytest.raises(FileExistsError):
        create_archive(tmp_path / "staging", archive)
    assert archive.read_bytes() == original
