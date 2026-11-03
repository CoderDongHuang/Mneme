"""Deployment regression: Docker structured Mounts can exist while HostConfig.Binds is null."""

import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("runtime_mounts", Path(__file__).parents[2] / "scripts/check_runtime_mounts.py")
mounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mounts)


def test_structured_mounts_not_hostconfig_binds_are_authoritative():
    expected = [{"type": "bind", "source": "D:\\Mneme\\data", "target": "/data"}]
    live = {"HostConfig": {"Binds": None}, "Mounts": [
        {"Type": "bind", "Source": "D:/Mneme/data", "Destination": "/data", "RW": True}]}
    assert mounts.mismatches(expected, live["Mounts"], {}) == []
    assert mounts.mismatches(expected, [], {}) == ["/data"]


def test_changed_source_mode_or_named_volume_are_rejected():
    expected = [{"type": "bind", "source": "/srv/data", "target": "/data", "read_only": True}]
    for source, writable in [("/srv/data", True), ("/srv/other", False), ("/srv/DATA", False)]:
        assert mounts.mismatches(expected, [{"Type": "bind", "Source": source, "Destination": "/data", "RW": writable}], {}) == ["/data"]
    expected = [{"type": "volume", "source": "agent-data", "target": "/data"}]
    actual = [{"Type": "volume", "Name": "mneme_agent-data", "Destination": "/data", "RW": True}]
    volumes = {"agent-data": {"name": "mneme_agent-data"}}
    assert mounts.mismatches(expected, actual, volumes) == []
    actual[0]["Name"] = "wrong-project-data"
    assert mounts.mismatches(expected, actual, volumes) == ["/data"]
