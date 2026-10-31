"""Validate rendered deployment credentials and migration startup ordering."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def render(*files, env):
    result = subprocess.run(["docker", "compose", *[part for f in files for part in ("-f", f)],
                             "config", "--format", "json"], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Compose validation failed (configuration output withheld)")
    return json.loads(result.stdout)["services"]


def main():
    env = {**os.environ, "MYSQL_ROOT_PASSWORD": "roles-admin-check",
           "SPRING_DATASOURCE_PASSWORD": "legacy-local-check", "MYSQL_GATEWAY_PASSWORD": "roles-gw-check",
           "MYSQL_AGENT_PASSWORD": "roles-agent-check", "MYSQL_MIGRATION_PASSWORD": "roles-ddl-check",
           "REDIS_PASSWORD": "roles-redis-check", "MODEL_CONFIG_ENCRYPTION_KEY": "roles-check-independent-key-at-least-32-chars",
           "MNEME_PYTHON_IMAGE": "mneme-agent:roles-check", "MNEME_JAVA_IMAGE": "mneme-gw:roles-check",
           "MNEME_FRONTEND_IMAGE": "mneme-ui:roles-check", "DEMO_DB_PASSWORD": "roles-demo-check",
           "DEMO_SERVICE_TOKEN": "roles-demo-check-at-least-32-characters", "DEMO_JWT_SECRET": "roles-demo-jwt-at-least-32-characters"}
    for files in [("docker-compose.yml",), ("docker-compose.yml", "docker-compose.prod.yml"),
                  ("docker-compose.yml", "docker-compose.selfhost.yml"), ("docker-compose.scale-ci.yml",),
                  ("docker-compose.demo.yml",)]:
        services = render(*files, env=env)
        assert services["mysql-users"]["depends_on"]["mysql"]["condition"] == "service_healthy"
        for name, service in services.items():
            if name.startswith("java-gateway"):
                config = service["environment"]
                assert config["SPRING_DATASOURCE_USERNAME"] == "mneme_gateway"
                assert config["SPRING_FLYWAY_USER"] == "mneme_migrator"
                assert service["depends_on"]["mysql-users"]["condition"] == "service_completed_successfully"
                if "demo" not in files[0]:
                    agent = "python-agent" + name.removeprefix("java-gateway")
                    assert service["depends_on"][agent]["condition"] == "service_started"
            if name.startswith("python-agent") and "demo" not in files[0]:
                assert service["environment"]["MYSQL_USER"] == "mneme_agent"
                assert service["depends_on"]["mysql-users"]["condition"] == "service_completed_successfully"
    for variable in ("MYSQL_GATEWAY_PASSWORD", "MYSQL_AGENT_PASSWORD", "MYSQL_MIGRATION_PASSWORD"):
        try:
            render("docker-compose.yml", "docker-compose.prod.yml", env={**env, variable: ""})
        except RuntimeError:
            continue
        raise AssertionError(f"Production accepted empty {variable}")
    print("Base, production, selfhost, demo and two-node roles/startup ordering verified; production missing secrets rejected")


if __name__ == "__main__":
    main()
