"""Portable isolated demo lifecycle. Requires Python 3.10+ and Docker Compose v2."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".env.demo.local"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "logs", "stop", "clean"])
    parser.add_argument("--confirm-delete-demo-data", action="store_true")
    args = parser.parse_args()
    if args.action == "clean" and not args.confirm_delete_demo_data:
        parser.error("clean deletes ONLY mneme-demo volumes; pass --confirm-delete-demo-data")
    if not CONFIG.exists():
        if args.action != "start":
            parser.error("Demo has not been configured; run start first")
        content = "\n".join(f"{key}={secrets.token_hex(32)}" for key in (
            "DEMO_DB_PASSWORD", "DEMO_JWT_SECRET", "DEMO_SERVICE_TOKEN")) + "\n"
        fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
    command = ["docker", "compose", "--project-name", "mneme-demo", "--env-file", str(CONFIG),
               "-f", str(ROOT / "docker-compose.demo.yml")]
    operations = {"start": ["up", "-d", "--build", "--wait", "--wait-timeout", "300"],
                  "status": ["ps"], "logs": ["logs", "--tail", "100"],
                  "stop": ["down"], "clean": ["down", "--volumes"]}
    subprocess.run(command + operations[args.action], cwd=ROOT, check=True)
    if args.action == "start":
        print(f"Demo: http://localhost:{os.getenv('DEMO_PORT', '3000')} | local mail: http://localhost:{os.getenv('DEMO_MAIL_PORT', '8025')}")
        print("Register a local account, upload test-fixtures/rag-fixture.md, select the library and ask a question.")


if __name__ == "__main__":
    main()
