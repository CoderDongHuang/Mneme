"""Verify that Compose keeps Qdrant private to the Python agents."""

import json
import os
import subprocess
import sys


def check(filenames: tuple[str, ...], qdrant_names: tuple[str, ...], agent_names: tuple[str, ...]) -> None:
    compose_files = [argument for filename in filenames for argument in ("-f", filename)]
    result = subprocess.run(
        ["docker", "compose", *compose_files, "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        # Static rendering only; these values are never used to start services.
        env={**os.environ, "REDIS_PASSWORD": "isolated-compose-validation-not-a-deployment-key",
             "MYSQL_GATEWAY_PASSWORD": "isolated-gateway-compose-check",
             "MYSQL_AGENT_PASSWORD": "isolated-agent-compose-check",
             "MYSQL_MIGRATION_PASSWORD": "isolated-migrator-compose-check",
             "MODEL_CONFIG_ENCRYPTION_KEY": "isolated-model-config-validation-at-least-32-chars",
             "MNEME_PYTHON_IMAGE": "mneme-python-agent:compose-check",
             "MNEME_JAVA_IMAGE": "mneme-java-gateway:compose-check",
             "MNEME_FRONTEND_IMAGE": "mneme-frontend:compose-check"},
    )
    config = json.loads(result.stdout)
    services = config["services"]
    networks = config["networks"]
    private = next(name for name in networks if name.endswith("vector-backend"))
    assert networks[private]["internal"] is True

    for name in qdrant_names:
        qdrant = services[name]
        assert not qdrant.get("ports"), f"{name} publishes a port"
        assert set(qdrant["networks"]) == {private}, f"{name} joins other networks"
    for name in agent_names:
        agent_networks = set(services[name]["networks"])
        assert private in agent_networks and len(agent_networks) > 1
    for name, service in services.items():
        if name not in (*qdrant_names, *agent_names):
            assert private not in service.get("networks", {}), f"{name} can reach Qdrant"


def main() -> None:
    for files in (
        ("docker-compose.yml",),
        ("docker-compose.yml", "docker-compose.selfhost.yml", "docker-compose.ci.yml"),
        ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.observability.yml"),
    ):
        check(files, ("qdrant",), ("python-agent",))
    check(("docker-compose.scale-ci.yml",), ("qdrant-1", "qdrant-2"), ("python-agent-1", "python-agent-2"))
    print("Qdrant network isolation verified in primary, CI, production and scale stacks")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, subprocess.CalledProcessError, KeyError, StopIteration) as exc:
        print(f"Qdrant isolation check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
