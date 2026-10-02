"""Run the reproducible local full-stack browser acceptance test."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.selfhost.yml", "docker-compose.ci.yml")


def compose_command() -> list[str]:
    command = ["docker", "compose"]
    for filename in COMPOSE_FILES:
        command.extend(["-f", filename])
    return command


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, text=True, check=check)


def wait_for(url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, URLError):
            pass
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-only", action="store_true", help="Validate the merged Compose configuration only")
    parser.add_argument("--keep", action="store_true", help="Keep containers running after the test")
    parser.add_argument("--timeout", type=int, default=180, help="Health-check timeout in seconds")
    args = parser.parse_args()
    compose = compose_command()
    run([*compose, "config", "--quiet"])
    if args.config_only:
        return 0

    try:
        run([*compose, "up", "-d", "--build"])
        wait_for("http://127.0.0.1:8080/actuator/health", args.timeout)
        wait_for("http://127.0.0.1:3000", args.timeout)
        env = os.environ.copy()
        env.update({"MNEME_REAL_E2E": "true", "MNEME_E2E_BASE_URL": "http://127.0.0.1:3000"})
        command = ["npm", "run", "test:e2e:real"]
        print("$", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT / "frontend", env=env, check=True)
        return 0
    except (subprocess.CalledProcessError, RuntimeError):
        run([*compose, "ps"], check=False)
        run([*compose, "logs", "--no-color"], check=False)
        raise
    finally:
        if not args.keep:
            run([*compose, "down", "--volumes", "--remove-orphans"], check=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Real-stack E2E failed: {error}", file=sys.stderr)
        raise SystemExit(1)
