"""Plan/apply crash-upload retention using the deployed Agent image and mounts."""
import argparse
from contextlib import nullcontext
import json
from pathlib import PurePosixPath
import subprocess
import sys

try:
    from .maintain_sqlite import docker, stopped_writers
except ImportError:
    from maintain_sqlite import docker, stopped_writers


def config(info):
    labels = info["Config"].get("Labels") or {}
    project = labels.get("com.docker.compose.project")
    if not project or labels.get("com.docker.compose.service") != "python-agent":
        raise ValueError("target_is_not_compose_agent")
    env = dict(value.split("=", 1) for value in info["Config"]["Env"])
    root = PurePosixPath(env.get("UPLOAD_DIR", "/app/data/uploads"))
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("invalid_upload_directory")
    staging = root / ".mneme-staging"
    mounts = [mount for mount in info["Mounts"] if staging.is_relative_to(mount["Destination"])]
    if not mounts or not max(mounts, key=lambda mount: len(mount["Destination"]))["RW"]:
        raise ValueError("uploads_not_in_writable_mount")
    return project, str(root), {"uploads": str(staging)}


def execute(info, root, hours, apply):
    command = ["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
               "--volumes-from", info["Id"] + ("" if apply else ":ro"), "--entrypoint", "python",
               info["Image"], "-m", "app.storage.upload_maintenance", "--upload-dir", root,
               "--hours", str(hours)]
    if apply:
        command += ["--apply", "--offline"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    receipt = json.loads(result.stdout)
    if (result.returncode or not isinstance(receipt, dict)
            or set(receipt) != {"status", "files", "bytes", "retained", "unknown"}
            or receipt["status"] != ("completed" if apply else "planned")
            or any(type(receipt[key]) is not int or receipt[key] < 0
                   for key in ("files", "bytes", "retained", "unknown"))):
        raise ValueError("upload_maintenance_failed")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="mneme-python-agent-1")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.hours < 1:
            raise ValueError("invalid_retention_hours")
        if args.apply:
            try:
                from .backup_restore import operation_lock
            except ImportError:
                from backup_restore import operation_lock
        with operation_lock() if args.apply else nullcontext():
            info = json.loads(docker("inspect", args.container))[0]
            project, root, stores = config(info)
            if args.apply:
                ids = docker("ps", "-q").split()
                peers = json.loads(docker("inspect", *ids)) if ids else []
                stopped_writers(project, info, peers, stores)
            print(json.dumps(execute(info, root, args.hours, args.apply)))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError):
        print("FAIL: upload maintenance unavailable; verify stopped writers, image and mounts", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
