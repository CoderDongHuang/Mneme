import base64
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import backup_aws_kms as MODULE


def test_kms_adapter_uses_cross_platform_file_and_removes_it(monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_RECOVERY_REGION", "eu-west-1")
    payload = b"data-key-for-adapter-contract-test"
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "arn:aws:kms:region:account:key/test")
    monkeypatch.setattr(sys, "argv", ["backup_aws_kms.py", "wrap", "v1"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(base64.b64encode(payload))))
    seen = []

    def fake_run(command, **kwargs):
        source = next(arg.removeprefix("fileb://") for arg in command if arg.startswith("fileb://"))
        assert Path(source).read_bytes() == payload
        assert command[1:3] == ["kms", "encrypt"]
        assert command[-2:] == ["--region", "eu-west-1"]
        seen.append(Path(source))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"CiphertextBlob": base64.b64encode(b"wrapped").decode()}).encode())

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    assert MODULE.main() == 0
    assert capsys.readouterr().out == base64.b64encode(b"wrapped").decode()
    assert seen and not seen[0].exists()


def test_kms_rejects_invalid_input_without_running_aws(monkeypatch):
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "key-id")
    monkeypatch.setattr(sys, "argv", ["adapter", "unwrap", "v1"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"not-base64!")))
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: pytest.fail("AWS must not run"))
    assert MODULE.main() == 2


@pytest.mark.parametrize("plaintext", ["not-base64!", base64.b64encode(b"short").decode(), ""])
def test_kms_rejects_bad_unwrapped_data_key(monkeypatch, plaintext):
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "key-id")
    monkeypatch.setattr(sys, "argv", ["adapter", "unwrap", "v1"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(base64.b64encode(b"wrapped"))))
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps({"Plaintext": plaintext}).encode()))
    assert MODULE.main() != 0


def test_kms_adapter_removes_input_on_failure(monkeypatch):
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "key-id")
    monkeypatch.setattr(sys, "argv", ["backup_aws_kms.py", "unwrap", "v1"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(base64.b64encode(b"wrapped"))))
    seen = []

    def fake_run(command, **kwargs):
        seen.append(Path(next(arg.removeprefix("fileb://") for arg in command if arg.startswith("fileb://"))))
        raise OSError("unavailable")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    assert MODULE.main() == 1
    assert seen and not seen[0].exists()
