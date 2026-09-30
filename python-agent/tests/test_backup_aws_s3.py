import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "backup_aws_s3.py"
SPEC = importlib.util.spec_from_file_location("backup_aws_s3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_copy_preserves_s3_uri(monkeypatch):
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
