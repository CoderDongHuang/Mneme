import json
import subprocess
import sys


def test_backup_key_rotation_drill(tmp_path):
    report = tmp_path / "rotation.json"
    subprocess.run(
        [sys.executable, "scripts/backup_key_rotation_drill.py", "--report", str(report)],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data == {
        "status": "completed",
        "old_key_recovery": True,
        "new_key_archive": True,
        "old_key_rejected_after_retirement": True,
        "cross_environment_restore": True,
    }
