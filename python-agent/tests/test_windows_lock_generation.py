"""Release lock generation must retain target-specific dependency edges."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("windows_lock", Path(__file__).parents[2] / "scripts" / "generate_windows_requirements_lock.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def wheel(tmp_path, name, version, dependencies=()):
    path = tmp_path / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        metadata += "".join(f"Requires-Dist: {item}\n" for item in dependencies)
        archive.writestr(f"{name}-{version}.dist-info/METADATA", metadata)
    return path


def test_target_markers_and_transitive_closure(tmp_path):
    wheels = {("app", "1.0"): wheel(tmp_path, "app", "1.0", [
        'colorama>=0.4; sys_platform == "win32"',
        'tzdata; platform_system == "Windows"',
        'uvloop; sys_platform != "win32"',
        'old-python; python_version < "3.11"',
        'optional; extra == "dev"',
    ])}
    assert MODULE.windows_dependencies(wheels) == ["colorama>=0.4", "tzdata"]
    wheels[("colorama", "0.4.6")] = wheel(tmp_path, "colorama", "0.4.6", ["helper>=1"])
    wheels[("tzdata", "2026.6")] = wheel(tmp_path, "tzdata", "2026.6")
    assert MODULE.windows_dependencies(wheels) == ["helper>=1"]
    wheels[("helper", "1.0")] = wheel(tmp_path, "helper", "1.0")
    assert MODULE.windows_dependencies(wheels) == []


def test_target_dependency_conflict_fails_generation(tmp_path):
    wheels = {("app", "1.0"): wheel(tmp_path, "app", "1.0", ['colorama>=0.4; os_name == "nt"']),
              ("colorama", "0.3"): wheel(tmp_path, "colorama", "0.3")}
    with pytest.raises(SystemExit, match="Windows dependency conflict"):
        MODULE.windows_dependencies(wheels)
