import json
import subprocess
import sys


def test_alertmanager_drill_generates_evidence(tmp_path):
    report = tmp_path / "alert.json"
    result = subprocess.run(
        [sys.executable, "scripts/alertmanager_drill.py", "--report", str(report)],
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
