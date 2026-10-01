import hashlib
import hmac
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import backup_geo_recovery_drill as geo
from scripts import backup_restore as backup
from scripts.backup_aws_preflight import CloudPreflightError


@pytest.fixture(autouse=True)
def clean_backup_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("BACKUP_", "MNEME_DRILL_")):
            monkeypatch.delenv(name)


def envelope_archive(tmp_path, monkeypatch):
    source = tmp_path / "source"
    files = {
        "payload/mysql.sql": b"actual sql inventory",
        "payload/data/files/first.txt": b"first actual file",
        "payload/data/avatars/second.bin": b"second actual file",
    }
    for name, data in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    provider = Path(backup.__file__).with_name("backup_key_provider.py")
    monkeypatch.setenv("BACKUP_KMS_COMMAND", f'"{sys.executable}" "{provider}"')
    monkeypatch.setenv("MNEME_DRILL_MASTER_KEY", "test-only-envelope-master-secret")
    monkeypatch.setenv("BACKUP_SIGNING_KEY_V1", "test-only-signing-secret-at-least-32-bytes")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", os.environ["BACKUP_SIGNING_KEY_V1"])
    monkeypatch.setenv("BACKUP_KEY_VERSION", "v1")
    archive = tmp_path / "actual.tar.gz"
    backup.create_archive(source, archive)
    return archive, files


def run(tmp_path, *arguments):
    report = tmp_path / "report.json"
    status = geo.main([*map(str, arguments), "--report", str(report)])
    return status, json.loads(report.read_text(encoding="utf-8"))


def test_real_archive_recovers_all_files_and_uses_archive_version(tmp_path, monkeypatch):
    archive, files = envelope_archive(tmp_path, monkeypatch)
    original = archive.read_bytes()
    monkeypatch.setenv("BACKUP_KEY_VERSION", "v2")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "active-v2-secret-does-not-match-old-archive")
    status, report = run(tmp_path, "--archive", archive)
    assert status == 0
    assert report["data_mode"] == "actual-archive"
    assert report["key_version"] == "v1"
    assert report["restored_file_count"] == len(files)
    assert {entry["path"]: entry["sha256"] for entry in report["restored_files"]} == {
        name: hashlib.sha256(data).hexdigest() for name, data in files.items()
    }
    assert report["all_plaintext_digests_verified"]
    assert report["restored_sha256"] is None  # No synthetic marker is required.
    assert archive.read_bytes() == original


def test_real_archive_never_installs_fallback_keys(tmp_path, monkeypatch):
    archive, _ = envelope_archive(tmp_path, monkeypatch)
    monkeypatch.delenv("BACKUP_SIGNING_KEY")
    monkeypatch.delenv("BACKUP_SIGNING_KEY_V1")
    status, report = run(tmp_path, "--archive", archive)
    assert status == 1 and report["status"] == "failed"
    assert "BACKUP_SIGNING_KEY" in report["error"]
    assert "BACKUP_SIGNING_KEY" not in os.environ


def test_real_archive_requires_unwrap_provider(tmp_path, monkeypatch):
    archive, _ = envelope_archive(tmp_path, monkeypatch)
    monkeypatch.delenv("BACKUP_KMS_COMMAND")
    status, report = run(tmp_path, "--archive", archive)
    assert status == 1
    assert "BACKUP_KMS_COMMAND" in report["error"]
    assert "BACKUP_KMS_COMMAND" not in os.environ


@pytest.mark.parametrize("encrypted,signed", [(False, False), (True, True), (False, True)])
def test_real_archive_rejects_unprotected_or_non_envelope_backups(tmp_path, monkeypatch, encrypted, signed):
    source = tmp_path / "source"
    (source / "payload").mkdir(parents=True)
    (source / "payload/mysql.sql").write_bytes(b"sql")
    archive = tmp_path / "direct.tar.gz"
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "test-encryption-secret-at-least-32-bytes")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "test-signing-secret-at-least-32-bytes")
    if not encrypted:
        monkeypatch.delenv("BACKUP_ENCRYPTION_KEY")
    if not signed:
        monkeypatch.delenv("BACKUP_SIGNING_KEY")
    backup.create_archive(source, archive)
    status, report = run(tmp_path, "--archive", archive)
    assert status == 1 and not report["payload_verified"]


def test_archive_failure_on_non_marker_plaintext_digest(tmp_path, monkeypatch):
    archive, _ = envelope_archive(tmp_path, monkeypatch)
    with tarfile.open(archive, "r:gz") as bundle:
        contents = {member.name: bundle.extractfile(member).read() for member in bundle.getmembers() if member.isfile()}
    manifest = json.loads(contents["manifest.json"])
    manifest["files"][0]["plaintext_sha256"] = "0" * 64
    key = backup._secret_bytes(os.environ["BACKUP_SIGNING_KEY"], "signing key")
    manifest["security"]["signature"] = hmac.new(key, backup._signed_manifest(manifest), hashlib.sha256).hexdigest()
    contents["manifest.json"] = json.dumps(manifest).encode()
    with tarfile.open(archive, "w:gz") as bundle:
        for name, data in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    status, report = run(tmp_path, "--archive", archive)
    assert status == 1
    assert "plaintext checksum mismatch" in report["error"]


def test_local_synthetic_is_compatible_and_does_not_leave_secrets(tmp_path):
    before = os.environ.copy()
    status, report = run(tmp_path)
    assert status == 0
    assert report["data_mode"] == "controlled-synthetic"
    assert report["key_provider"] == "local-drill-provider"
    assert report["cloud_verified"] is False
    assert report["restored_file_count"] == 2
    assert dict(os.environ) == before


def mock_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_KEY_VERSION", "v1")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "configured-test-signing-secret-at-least-32-bytes")
    arn = "arn:aws:kms:eu-west-1:123456789012:key/mrk-observed"
    monkeypatch.setattr(geo, "preflight", lambda *args: {
        "status": "passed", "recovery_region": args[1], "key_version": args[3], "kms_key": {"Arn": arn},
    })

    def key_provider(action, version, value):
        assert os.environ[f"BACKUP_KMS_KEY_ID_{version.upper()}"] == arn
        return value

    monkeypatch.setattr(backup, "_key_provider", key_provider)

    def local(path):
        return tmp_path / "object.tar.gz" if str(path).startswith("s3://") else Path(path)

    def command(command, source, destination):
        assert "backup_aws_s3.py" in command
        destination = local(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local(source), destination)

    monkeypatch.setattr(geo, "_run_command", command)
    monkeypatch.setattr(geo, "_run_remote_verifier", lambda command, destination, digest: backup.sha256_file(local(destination)))


def cloud_args(tmp_path):
    # The S3 adapter boundary is mocked; all cryptography and digest checks are real.
    return ["--require-cloud", "--primary-region", "us-east-1", "--recovery-region", "eu-west-1", "--destination", "s3://mneme-recovery/drills/backup.tar.gz"]


def test_cloud_recovery_labels_synthetic_and_records_preflight(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)
    status, report = run(tmp_path, *cloud_args(tmp_path))
    assert status == 0
    assert report["data_mode"] == "controlled-synthetic" and report["cloud_verified"]
    assert report["key_provider"] == "aws-kms"
    assert report["remote_sha256"] == report["source_sha256"] == report["fetched_sha256"]
    assert "BACKUP_KMS_COMMAND" not in os.environ


def test_cloud_pins_observed_key_instead_of_using_configured_alias(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "alias/recovery")
    original_provider = backup._key_provider
    calls = []

    def provider(action, version, value):
        calls.append((action, os.environ["BACKUP_KMS_KEY_ID_V1"]))
        return original_provider(action, version, value)

    monkeypatch.setattr(backup, "_key_provider", provider)
    status, report = run(tmp_path, *cloud_args(tmp_path))
    assert status == 0
    arn = report["cloud_preflight"]["kms_key"]["Arn"]
    assert calls == [("wrap", arn), ("unwrap", arn)]
    assert os.environ["BACKUP_KMS_KEY_ID_V1"] == "alias/recovery"


def test_cloud_recovery_does_not_generate_a_signing_secret(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)
    monkeypatch.delenv("BACKUP_SIGNING_KEY")
    status, report = run(tmp_path, *cloud_args(tmp_path))
    assert status == 1
    assert "BACKUP_SIGNING_KEY" in report["error"]
    assert "BACKUP_SIGNING_KEY" not in os.environ


def test_failed_cloud_preflight_stops_before_copy(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)

    def reject(*args):
        raise CloudPreflightError("observed bucket is in primary region")

    monkeypatch.setattr(geo, "preflight", reject)
    monkeypatch.setattr(geo, "_run_command", lambda *args: pytest.fail("Must not copy"))
    status, report = run(tmp_path, *cloud_args(tmp_path))
    assert status == 1 and not report["cloud_verified"]
    assert "primary region" in report["error"]


def test_fetch_must_match_independently_verified_object(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)
    original = geo._run_command

    def command(command, source, destination):
        original(command, source, destination)
        if command.endswith(" fetch"):
            Path(destination).write_bytes(b"different fetched archive")

    monkeypatch.setattr(geo, "_run_command", command)
    status, report = run(tmp_path, *cloud_args(tmp_path))
    assert status == 1
    assert "fetched backup digest" in report["error"]


def test_cloud_rejects_custom_adapters_instead_of_claiming_aws_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_GEO_COPY_COMMAND", "local-simulation copy")
    with pytest.raises(SystemExit) as error:
        run(tmp_path, *cloud_args(tmp_path))
    assert error.value.code == 2


def test_cloud_uses_version_specific_signing_secret(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)
    monkeypatch.setenv("BACKUP_SIGNING_KEY_V1", "version-one-signing-secret-at-least-32-bytes")
    monkeypatch.delenv("BACKUP_SIGNING_KEY")
    status, report = run(tmp_path, *cloud_args(tmp_path))
    assert status == 0 and report["manifest_verified"]


def test_cloud_recovers_actual_archive_using_signed_key_version(tmp_path, monkeypatch):
    mock_cloud(tmp_path, monkeypatch)
    source = tmp_path / "real-source"
    (source / "payload/data/files").mkdir(parents=True)
    (source / "payload/mysql.sql").write_bytes(b"actual SQL")
    (source / "payload/data/files/user-file.txt").write_bytes(b"actual user data")
    # Fake AWS only at the key/transport boundary, preserving real archive crypto.
    monkeypatch.setenv("BACKUP_KMS_COMMAND", "configured-aws-provider")
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "arn:aws:kms:eu-west-1:123456789012:key/mrk-observed")
    archive = tmp_path / "actual-cloud.tar.gz"
    backup.create_archive(source, archive)
    monkeypatch.setenv("BACKUP_KEY_VERSION", "v2")
    status, report = run(tmp_path, *cloud_args(tmp_path), "--archive", archive)
    assert status == 0
    assert report["data_mode"] == "actual-archive"
    assert report["cloud_preflight"]["key_version"] == report["key_version"] == "v1"
    assert {entry["path"] for entry in report["restored_files"]} == {
        "payload/mysql.sql", "payload/data/files/user-file.txt",
    }
