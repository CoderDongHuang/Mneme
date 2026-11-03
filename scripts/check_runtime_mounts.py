"""Read-only check of the effective Compose data mounts against running containers."""

import argparse
import json
import subprocess


def docker_json(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def normalized_source(value):
    return value.replace("\\", "/").rstrip("/").casefold() if ":" in value else value.rstrip("/")


def mismatches(expected, actual, volumes):
    errors = []
    by_target = {mount["Destination"]: mount for mount in actual}
    for mount in expected:
        target = mount["target"]
        live = by_target.get(target)
        if not live or live["Type"] != mount["type"] or live["RW"] != (not mount.get("read_only", False)):
            errors.append(target)
            continue
        source = mount.get("source")
        if source and mount["type"] == "bind":
            if normalized_source(source) != normalized_source(live["Source"]):
                errors.append(target)
        elif source and mount["type"] == "volume":
            if live.get("Name") != volumes[source]["name"]:
                errors.append(target)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-f", "--file", action="append", help="Use exactly the Compose files used for deployment, in order")
    parser.add_argument("--service", action="append", help="Defaults to java-gateway and python-agent")
    args = parser.parse_args()
    compose = ["compose"]
    for path in args.file or ["docker-compose.yml"]:
        compose.extend(["-f", path])
    try:
        config = docker_json(*compose, "config", "--format", "json")
        for service in args.service or ["java-gateway", "python-agent"]:
            expected = config["services"][service].get("volumes", [])
            if not expected:
                raise ValueError(f"{service}: no expected data mounts")
            ids = subprocess.run(["docker", *compose, "ps", "-q", service], capture_output=True, text=True, check=True).stdout.split()
            if not ids:
                raise ValueError(f"{service}: no running container")
            for live in docker_json("inspect", *ids):
                errors = mismatches(expected, live["Mounts"], config.get("volumes", {}))
                if errors:
                    raise ValueError(f"{service}: missing or changed mounts: {', '.join(errors)}")
            print(f"PASS: {service} effective mounts verified ({len(ids)} containers)")
    except (subprocess.SubprocessError, ValueError, KeyError) as error:
        # Never echo Compose config, Docker stderr, environment variables, or credentials.
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            parser.exit(1, f"FAIL: {error}\n")
        parser.exit(1, "FAIL: cannot read deployment configuration or container mounts\n")


if __name__ == "__main__":
    main()
