import base64
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[2] / "scripts" / "backup_aws_kms.py"
SPEC = importlib.util.spec_from_file_location("backup_aws_kms", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_kms_adapter_uses_cross_platform_file_and_removes_it(monkeypatch, capsys):
    payload = b"data-key-for-adapter-contract-test"
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "arn:aws:kms:region:account:key/test")
    monkeypatch.setattr(sys, "argv", ["backup_aws_kms.py", "wrap", "v1"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(base64.b64encode(payload))))
    seen = []

    def fake_run(command, **kwargs):
        source = next(arg.removeprefix("fileb://") for arg in command if arg.startswith("fileb://"))
        assert Path(source).read_bytes() == payload
        assert command[1:3] == ["kms", "encrypt"]
        seen.append(Path(source))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"CiphertextBlob": "wrapped"}).encode())

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    assert MODULE.main() == 0
    assert capsys.readouterr().out == "wrapped"
    assert seen and not seen[0].exists()


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
