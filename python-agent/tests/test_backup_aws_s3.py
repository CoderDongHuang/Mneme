import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import backup_aws_s3 as MODULE


def test_copy_preserves_s3_uri(monkeypatch):
    for name in ("BACKUP_RECOVERY_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    class Result:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(MODULE.subprocess, "run", lambda command, **kwargs: calls.append(command) or Result())
    uri = "s3://mneme-backups/region-b/backup.tar.gz"
    assert MODULE.main(["backup_aws_s3.py", "copy", "local.tar.gz", uri]) == 0
    assert calls == [["aws", "s3", "cp", "local.tar.gz", uri, "--only-show-errors"]]


def test_verify_downloads_and_checks_digest(tmp_path, monkeypatch, capsys):
    payload = b"verified backup"

    def fake_copy(source, destination):
        assert source == "s3://mneme-backups/backup.tar.gz"
        Path(destination).write_bytes(payload)

    monkeypatch.setattr(MODULE, "_aws_copy", fake_copy)
    expected = __import__("hashlib").sha256(payload).hexdigest()
    assert MODULE.main(["backup_aws_s3.py", "verify", "s3://mneme-backups/backup.tar.gz", expected]) == 0
    assert capsys.readouterr().out.strip() == expected


def test_copy_uses_explicit_recovery_region(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("BACKUP_RECOVERY_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    seen = []
    monkeypatch.setattr(MODULE.subprocess, "run", lambda command, **kwargs: seen.append(command) or SimpleNamespace(returncode=0))
    MODULE._aws_copy("local.tar.gz", "s3://backups/backup.tar.gz")
    assert seen[0][-2:] == ["--region", "eu-west-1"]


def test_verify_rejects_wrong_digest(monkeypatch, capsys):
    monkeypatch.setattr(MODULE, "_aws_copy", lambda source, destination: Path(destination).write_bytes(b"wrong"))
    assert MODULE.main(["adapter", "verify", "s3://backups/backup.tar.gz", "0" * 64]) == 1
    assert capsys.readouterr().out.strip() != "0" * 64
