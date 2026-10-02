"""Generate a hash-pinned Windows CPython 3.11 lock from the Linux lock.

The project keeps separate locks because pip hashes identify distributions, and
platform-specific wheels legitimately have different hashes. This command
downloads only compatible Windows wheels and writes their SHA-256 values.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename


REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^\s]+)")
SKIP = {"uvloop"}


def requirements_from_lock(path: Path) -> list[str]:
    requirements: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT.match(line.strip())
        if not match:
            continue
        requirement = match.group(1)
        name = canonicalize_name(requirement.split("==", 1)[0].split("[", 1)[0])
        if name not in SKIP:
            requirements.append(requirement)
    if not requirements:
        raise SystemExit(f"No pinned requirements found in {path}")
    return requirements


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("python-agent/requirements.lock"))
    parser.add_argument("--output", type=Path, default=Path("python-agent/requirements.windows.lock"))
    args = parser.parse_args()
    requirements = requirements_from_lock(args.source)
    with tempfile.TemporaryDirectory(prefix="mneme-windows-lock-") as directory:
        command = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-deps",
            "--platform",
            "win_amd64",
            "--python-version",
            "3.11",
            "--implementation",
            "cp",
            "--abi",
            "cp311",
            "--dest",
            directory,
            *requirements,
        ]
        subprocess.run(command, check=True)
        wheels = {}
        for path in Path(directory).iterdir():
            name, version, _build, _tags = parse_wheel_filename(path.name)
            wheels[(canonicalize_name(name), str(version))] = path
        if len(wheels) != len(requirements):
            raise SystemExit(f"Expected {len(requirements)} Windows wheels, found {len(wheels)}")
        entries = [
            "# Generated for Windows AMD64 CPython 3.11 from requirements.lock.",
            "# uvloop is intentionally omitted because it is not supported on Windows.",
            "# Regenerate with: python scripts/generate_windows_requirements_lock.py",
            "",
        ]
        for requirement in requirements:
            parsed = Requirement(requirement)
            key = (canonicalize_name(parsed.name), str(next(iter(parsed.specifier)).version))
            wheel = wheels.get(key)
            if wheel is None:
                raise SystemExit(f"No downloaded wheel matched {requirement}")
            entries.extend([f"{requirement} \\", f"    --hash=sha256:{sha256(wheel)}"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(entries) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(requirements)} pinned Windows distributions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
