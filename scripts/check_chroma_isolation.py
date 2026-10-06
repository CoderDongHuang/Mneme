"""Verify that Compose keeps Chroma private to the Python agents."""

import json
import subprocess
import sys


def check(filenames: tuple[str, ...], chroma_names: tuple[str, ...], agent_names: tuple[str, ...]) -> None:
    compose_files = [argument for filename in filenames for argument in ("-f", filename)]
    result = subprocess.run(
        ["docker", "compose", *compose_files, "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(result.stdout)
    services = config["services"]
    networks = config["networks"]
    private = next(name for name in networks if name.endswith("vector-backend"))
    assert networks[private]["internal"] is True

    for name in chroma_names:
        chroma = services[name]
        assert not chroma.get("ports"), f"{name} publishes a port"
        assert set(chroma["networks"]) == {private}, f"{name} joins other networks"
    for name in agent_names:
        agent_networks = set(services[name]["networks"])
        assert private in agent_networks and len(agent_networks) > 1
    for name, service in services.items():
        if name not in (*chroma_names, *agent_names):
            assert private not in service.get("networks", {}), f"{name} can reach Chroma"


def main() -> None:
    for files in (
        ("docker-compose.yml",),
        ("docker-compose.yml", "docker-compose.selfhost.yml", "docker-compose.ci.yml"),
        ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.observability.yml"),
    ):
        check(files, ("chroma",), ("python-agent",))
    check(("docker-compose.scale-ci.yml",), ("chroma-1", "chroma-2"), ("python-agent-1", "python-agent-2"))
    print("Chroma network isolation verified in primary, CI, production and scale stacks")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, subprocess.CalledProcessError, KeyError, StopIteration) as exc:
        print(f"Chroma isolation check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
