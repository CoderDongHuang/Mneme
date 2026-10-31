"""Check release mounts and exercise the actual Python image without live data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]
IMAGE_ENV = {
    "MNEME_PYTHON_IMAGE": "mneme-python-agent:immutable-check",
    "MNEME_JAVA_IMAGE": "mneme-java-gateway:immutable-check",
    "MNEME_FRONTEND_IMAGE": "mneme-frontend:immutable-check",
}


def run(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    if result.returncode:
        # Compose output may contain interpolated credentials. Never echo it.
        raise RuntimeError(f"{args[0]} {args[1]} failed (exit {result.returncode})")
    return result.stdout.strip()


def compose(*overlays: str, env: dict[str, str] | None = None) -> dict:
    files = [arg for name in ("docker-compose.yml", *overlays) for arg in ("-f", name)]
    return json.loads(run("docker", "compose", *files, "config", "--format", "json", env=env))


def pinned(reference: str) -> bool:
    if "@" in reference:
        return re.fullmatch(r"[^\s@]+@sha256:[a-fA-F0-9]{64}", reference) is not None
    name, separator, tag = reference.rpartition(":")
    return bool(name and separator and re.fullmatch(r"[\w][\w.-]{0,127}", tag) and tag.lower() != "latest")


def check_release(config: dict, *, production: bool = False) -> None:
    for name in ("python-agent", "java-gateway", "frontend"):
        service = config["services"].get(name)
        if service is None:
            continue
        if production and not pinned(service.get("image", "")):
            raise RuntimeError(f"{name} requires a unique release tag or sha256 digest")
        allowed = {"/data", "/app/data", "/test-fixtures"} if name == "python-agent" else {"/data"}
        for mount in service.get("volumes", []):
            if mount["type"] == "bind" and mount["target"] not in allowed:
                raise RuntimeError(f"{name} contains a non-data bind mount")
    state = next(v for v in config["services"]["python-agent"]["volumes"] if v["target"] == "/app/data")
    if Path(state["source"]).resolve() != (ROOT / "python-agent" / "data").resolve():
        raise RuntimeError("Existing Python state must retain its backup-compatible data mount")


def verify_build() -> None:
    suffix = uuid.uuid4().hex
    probe = ROOT / "python-agent" / f"_mneme_image_probe_{suffix}.py"
    secret_probe = ROOT / "python-agent" / f".env.mneme-image-probe-{suffix}"
    # A unique file in the existing data directory; never touch existing data.
    data_dir = ROOT / "python-agent" / "data"
    created_data_dir = not data_dir.exists()
    data_dir.mkdir(exist_ok=True)
    data_probe = data_dir / f"mneme-image-probe-{suffix}"
    image = f"mneme-immutable-check:{suffix}"
    container = f"mneme-immutable-check-{suffix}"
    built = False
    try:
        probe.write_text("print('image-code-before-host-edit')\n", encoding="utf-8")
        secret_probe.write_text("ISOLATED_TEST_MARKER=true\n", encoding="utf-8")
        data_probe.write_text("isolated-test-data\n", encoding="utf-8")
        command = ["docker", "build", "--tag", image]
        if os.getenv("MNEME_PYTHON_BASE_IMAGE"):
            command += ["--build-arg", f"PYTHON_BASE_IMAGE={os.environ['MNEME_PYTHON_BASE_IMAGE']}"]
        if os.getenv("MNEME_PIP_INDEX_URL"):
            command += ["--build-arg", f"PIP_INDEX_URL={os.environ['MNEME_PIP_INDEX_URL']}"]
        run(*command, "--file", "python-agent/Dockerfile", "python-agent")
        built = True
        probe.write_text("print('host-code-after-image-build')\n", encoding="utf-8")
        code = (
            "import pathlib, runpy; "
            f"runpy.run_path('/app/{probe.name}'); "
            f"assert not pathlib.Path('/app/{secret_probe.name}').exists(); "
            f"assert not pathlib.Path('/app/data/{data_probe.name}').exists(); "
            "import fastapi, app.core.config; "
            "print('runtime-imports-and-context-exclusions-pass')"
        )
        # No network, project mounts, credentials or existing service dependencies.
        run("docker", "create", "--name", container, "--network", "none", "--entrypoint", "python", image, "-c", code)
        mounts = json.loads(run("docker", "inspect", container))[0]["Mounts"]
        if mounts:
            raise RuntimeError("Image check container unexpectedly has mounted code/data")
        output = run("docker", "start", "--attach", container)
        status = json.loads(run("docker", "inspect", container))[0]["State"]["ExitCode"]
        if status != 0 or output.splitlines() != ["image-code-before-host-edit", "runtime-imports-and-context-exclusions-pass"]:
            raise RuntimeError("Host edit isolation, runtime imports or build exclusions failed")
        print("Actual Python image: host source edit isolated; local secrets/data excluded; runtime imports passed")
    finally:
        # Only uniquely named resources created above are removed.
        subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)
        if built:
            subprocess.run(["docker", "image", "rm", image], capture_output=True, check=False)
        probe.unlink(missing_ok=True)
        secret_probe.unlink(missing_ok=True)
        data_probe.unlink(missing_ok=True)
        if created_data_dir:
            try:
                data_dir.rmdir()
            except OSError:
                pass  # Another process may have created real state in the meantime.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true", help="Validate actual production references/mounts only; do not build")
    args = parser.parse_args()
    if args.production:
        check_release(compose("docker-compose.prod.yml"), production=True)
        print("Production release image references and data-only mounts verified")
        return
    env = {**os.environ, **IMAGE_ENV, "REDIS_PASSWORD": "isolated-check-only",
           "MODEL_CONFIG_ENCRYPTION_KEY": "isolated-check-only-key-at-least-32-chars",
           "MYSQL_GATEWAY_PASSWORD": "isolated-gateway-password",
           "MYSQL_AGENT_PASSWORD": "isolated-agent-password",
           "MYSQL_MIGRATION_PASSWORD": "isolated-migration-password"}
    check_release(compose(env=env))
    check_release(compose("docker-compose.selfhost.yml", env=env))
    production = compose("docker-compose.prod.yml", env=env)
    check_release(production, production=True)
    for value in ("latest", "repo", "repo:latest", "registry:5000/repo", "repo@sha256:short"):
        if pinned(value):
            raise RuntimeError("Mutable or malformed reference accepted")
    for variable in IMAGE_ENV:
        try:
            compose("docker-compose.prod.yml", env={**env, variable: ""})
        except RuntimeError:
            pass
        else:
            raise RuntimeError(f"Missing {variable} was accepted")
    dev = compose("docker-compose.selfhost.yml", "docker-compose.dev.yml", env=env)
    if not any(v["target"] == "/app" for v in dev["services"]["python-agent"]["volumes"]):
        raise RuntimeError("Development overlay must explicitly opt in to source mounting")
    print("Base/selfhost/production data mounts, required release images and opt-in development mount verified", flush=True)
    verify_build()


if __name__ == "__main__":
    main()
