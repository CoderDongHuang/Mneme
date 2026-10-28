"""Generate a hash-pinned Windows CPython 3.11 lock from the Linux lock.

The project keeps separate locks because pip hashes identify distributions, and
platform-specific wheels legitimately have different hashes. This command
downloads compatible Windows wheels (and jieba's platform-independent source
distribution, for which upstream publishes no wheel) and writes SHA-256 values.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name, parse_wheel_filename, parse_sdist_filename


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


def windows_dependencies(wheels: dict) -> list[str]:
    """Evaluate wheel metadata for the target, including Windows-only edges.

    pip download's --platform selects wheels but does not switch all dependency
    markers to the target OS. Resolve those edges explicitly instead of copying
    only the Linux closure (which can miss colorama or tzdata).
    """
    environment = default_environment()
    environment.update(os_name="nt", sys_platform="win32", platform_system="Windows",
                       platform_machine="AMD64", python_version="3.11", python_full_version="3.11.0",
                       implementation_name="cpython", implementation_version="3.11.0",
                       platform_python_implementation="CPython", extra="")
    versions = {name: version for name, version in wheels}
    missing = set()
    for path in wheels.values():
        if path.suffix != ".whl":
            continue  # jieba's fixed source archive has no runtime dependencies.
        with zipfile.ZipFile(path) as archive:
            metadata = Parser().parsestr(archive.read(next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))).decode())
        for value in metadata.get_all("Requires-Dist", []):
            requirement = Requirement(value)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            name = canonicalize_name(requirement.name)
            if name not in versions:
                requirement.marker = None
                missing.add(str(requirement))
            elif versions[name] not in requirement.specifier:
                raise SystemExit(f"Windows dependency conflict in {path.name}: {requirement}, pinned {versions[name]}")
    return sorted(missing)


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
            "--no-binary=jieba",
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
        ]
        wheels = {}
        pending = requirements
        for _ in range(12):
            subprocess.run([*command, *pending], check=True)
            for path in Path(directory).iterdir():
                if path.suffix == ".whl":
                    name, version, _build, _tags = parse_wheel_filename(path.name)
                else:
                    name, version = parse_sdist_filename(path.name)
                    if canonicalize_name(name) != "jieba":
                        raise SystemExit(f"Unexpected source distribution: {path.name}")
                wheels[(canonicalize_name(name), str(version))] = path
            pending = windows_dependencies(wheels)
            if not pending:
                break
        else:
            raise SystemExit("Windows dependency closure did not converge")
        requirements = sorted(f"{name}=={version}" for name, version in wheels)
        entries = [
            "# Generated for Windows AMD64 CPython 3.11 from requirements.lock.",
            "# uvloop is intentionally omitted because it is not supported on Windows.",
            "# Windows-only dependencies are resolved from target wheel metadata.",
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
