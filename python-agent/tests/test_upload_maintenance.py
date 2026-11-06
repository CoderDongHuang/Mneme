import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.storage import upload_maintenance as maintenance


NOW = 1800000000


def staged(tmp_path, name="mneme-upload-1234abcd.txt", *, old=True):
    root = maintenance.staging_directory(tmp_path, create=True)
    path = root / name
    path.write_bytes(b"private source")
    os.utime(path, (NOW - (90000 if old else 0),) * 2)
    return path


def test_offline_sweep_preserves_recent_unknown_external_and_is_idempotent(tmp_path):
    old = staged(tmp_path)
    recent = staged(tmp_path, "mneme-upload-recent12.pdf", old=False)
    unknown = staged(tmp_path, "original.pdf")
    outside = tmp_path / "original.txt"
    outside.write_text("permanent")
    nested = old.parent / "directory"
    nested.mkdir()
    (nested / old.name).write_text("do not recurse")
    receipt = maintenance.collect(tmp_path, now=NOW)
    assert receipt == {"status": "planned", "files": 1, "bytes": 14, "retained": 1, "unknown": 2}
    assert old.exists()
    assert maintenance.collect(tmp_path, apply=True, now=NOW) == receipt | {"status": "completed"}
    assert not old.exists()
    assert recent.exists() and unknown.exists() and outside.read_text() == "permanent"
    assert (nested / old.name).exists()
    assert maintenance.collect(tmp_path, apply=True, now=NOW)["files"] == 0


def test_real_upload_process_crash_leaves_identifiable_collectable_file(tmp_path):
    # Exit at the actual upload-to-executor handoff: no finally/atexit handler runs.
    code = """
import asyncio, os
from io import BytesIO
from fastapi import UploadFile
from app.api import knowledge
knowledge._submit_ingestion = lambda *args: os._exit(23)
asyncio.run(knowledge.upload_file(UploadFile(BytesIO(b'private crash source'), filename='source.txt'), 'qa', 'kb'))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            env=os.environ | {"UPLOAD_DIR": str(tmp_path), "QDRANT_PATH": str(tmp_path / "qdrant")},
                            capture_output=True, timeout=90)
    assert result.returncode == 23
    root = maintenance.staging_directory(tmp_path)
    paths = list(root.iterdir())
    assert len(paths) == 1 and maintenance.MANAGED_NAME.fullmatch(paths[0].name)
    assert paths[0].read_bytes() == b"private crash source"
    assert maintenance.collect(tmp_path, apply=True)["files"] == 0
    os.utime(paths[0], (NOW - 90000,) * 2)
    assert maintenance.collect(tmp_path, apply=True, now=NOW)["files"] == 1
    assert not list(root.iterdir())


@pytest.mark.parametrize("hours", [0, -1, True, 1.5])
def test_invalid_policy_does_not_create_or_remove_directory(tmp_path, hours):
    with pytest.raises(ValueError):
        maintenance.collect(tmp_path, hours=hours, apply=True)
    assert not maintenance.staging_directory(tmp_path).exists()


def test_missing_namespace_is_a_read_only_empty_plan(tmp_path):
    assert maintenance.collect(tmp_path)["files"] == 0
    assert not maintenance.staging_directory(tmp_path).exists()


@pytest.mark.parametrize("kind", ["file_link", "parent_link", "hard_link"])
def test_links_fail_before_any_deletion(tmp_path, kind):
    uploads = tmp_path / "uploads"
    old = staged(uploads)
    external = tmp_path / "external"
    external.write_text("preserve private content")
    root = old.parent
    try:
        if kind == "file_link":
            (root / "mneme-upload-linked12.txt").symlink_to(external)
        elif kind == "hard_link":
            os.link(external, root / "mneme-upload-linked12.txt")
        else:
            alias = tmp_path / "alias"
            alias.symlink_to(uploads, target_is_directory=True)
            uploads = alias
    except OSError:
        pytest.skip("host does not permit link creation")
    with pytest.raises(ValueError, match="unsafe_staging"):
        maintenance.collect(uploads, apply=True, now=NOW)
    assert old.exists() and external.read_text() == "preserve private content"


def test_changed_inventory_fails_before_deleting_first_candidate(tmp_path, monkeypatch):
    old = staged(tmp_path)
    other = staged(tmp_path, "mneme-upload-8765dcba.pdf")
    original = Path.lstat
    calls = [0]

    def changed(path, *args, **kwargs):
        if path == other:
            calls[0] += 1
            if calls[0] == 2:
                path.write_bytes(b"changed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", changed)
    with pytest.raises(ValueError, match="staging_changed"):
        maintenance.collect(tmp_path, apply=True, now=NOW)
    assert old.exists() and other.exists()


def test_cli_requires_offline_and_sanitizes_errors(tmp_path, monkeypatch, capsys):
    path = staged(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker", "--upload-dir", str(tmp_path), "--apply"])
    assert maintenance.main() == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "upload_maintenance_failed"}
    assert path.exists()
    monkeypatch.setattr(maintenance, "collect", lambda *a, **k: (_ for _ in ()).throw(OSError("private filename")))
    monkeypatch.setattr(sys, "argv", ["worker", "--upload-dir", str(tmp_path)])
    assert maintenance.main() == 1
    assert "private" not in capsys.readouterr().out


def host_script():
    source = Path(__file__).resolve().parents[2] / "scripts/maintain_uploads.py"
    spec = importlib.util.spec_from_file_location("maintain_uploads_host", source)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(source.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def target():
    return {"Id": "deployed", "Image": "sha256:actual-image", "State": {"Running": False},
            "Config": {"Env": [], "Labels": {"com.docker.compose.project": "mneme",
                                                "com.docker.compose.service": "python-agent"}},
            "Mounts": [{"Source": "D:/Mneme/data", "Destination": "/app/data", "RW": True}]}


def test_host_uses_actual_image_and_stopped_writer_guard(monkeypatch):
    host = host_script()
    info = target()
    project, root, stores = host.config(info)
    assert root == "/app/data/uploads"
    for service in ("python-agent", "java-gateway"):
        peer = target()
        peer["Config"]["Labels"]["com.docker.compose.service"] = service
        peer["State"]["Running"] = True
        with pytest.raises(ValueError, match="stop_all"):
            host.stopped_writers(project, info, [peer], stores)
    peer["Config"]["Labels"] = {}
    with pytest.raises(ValueError, match="another_container"):
        host.stopped_writers(project, info, [peer], stores)
    calls = []
    receipt = {"status": "planned", "files": 1, "bytes": 14, "retained": 0, "unknown": 0}

    def run(command, **options):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt))

    monkeypatch.setattr(host.subprocess, "run", run)
    assert host.execute(info, root, 24, False) == receipt
    assert "deployed:ro" in calls[-1] and "sha256:actual-image" in calls[-1]
    assert calls[-1][calls[-1].index("--network") + 1] == "none"
    receipt["status"] = "completed"
    host.execute(info, root, 24, True)
    assert "deployed" in calls[-1] and calls[-1][-2:] == ["--apply", "--offline"]
    receipt["private"] = "filename"
    with pytest.raises(ValueError):
        host.execute(info, root, 24, True)


@pytest.mark.parametrize("path", ["relative", "/outside", "/app/data/../data/uploads"])
def test_host_rejects_unmounted_and_ambiguous_paths(path):
    host = host_script()
    info = target()
    info["Config"]["Env"] = ["UPLOAD_DIR=" + path]
    with pytest.raises(ValueError):
        host.config(info)
    info = target()
    info["Mounts"].append({"Source": "/readonly", "Destination": "/app/data/uploads", "RW": False})
    with pytest.raises(ValueError):
        host.config(info)
