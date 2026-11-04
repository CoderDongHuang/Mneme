from pathlib import Path
import subprocess
import sys


def test_generated_gateway_rest_types_are_current():
    root = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, str(root / "python-agent/scripts/export_rest_contract.py"), "--check"], check=True)
