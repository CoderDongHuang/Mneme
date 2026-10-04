import json
import importlib.util
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("alertmanager_drill", ROOT / "scripts" / "alertmanager_drill.py")
assert SPEC and SPEC.loader
DRILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRILL)


def test_alertmanager_waits_for_readiness(monkeypatch):
    calls = []

    class Ready:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def open_url(url, timeout):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise URLError("starting")
        return Ready()

    monkeypatch.setattr(DRILL.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(DRILL.time, "sleep", lambda _seconds: None)
    DRILL.wait_for_alertmanager("http://localhost:9093")
    assert calls == [("http://localhost:9093/-/ready", 3)] * 2


def test_alertmanager_readiness_times_out(monkeypatch):
    ticks = iter([0, 2, 2])
    monkeypatch.setattr(DRILL.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(DRILL.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("down")))
    try:
        DRILL.wait_for_alertmanager("http://localhost:9093", timeout=1)
    except TimeoutError as error:
        assert "did not become ready" in str(error)
    else:
        raise AssertionError("readiness timeout must fail")


def test_alertmanager_drill_generates_evidence(tmp_path):
    report = tmp_path / "alert.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "alertmanager_drill.py"),
            "--report",
            str(report),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["receiver_outage_detected"] is True
    assert len(data["notifications"]) == 3
    assert "inhibition" in data["inhibition_rule"]
    assert data["receiver_failure_policy"].startswith("failure detected")
    assert "completed" in result.stdout
