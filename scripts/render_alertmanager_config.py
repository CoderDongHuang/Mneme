#!/usr/bin/env python3
"""Render the Alertmanager webhook configuration before starting the container."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "${ALERTMANAGER_WEBHOOK_URL}"


def render(template: Path, output: Path, webhook_url: str) -> None:
    try:
        parsed = urlsplit(webhook_url)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.port != 0
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and not any(character.isspace() for character in webhook_url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("ALERTMANAGER_WEBHOOK_URL must be a valid HTTP(S) URL")

    config = yaml.safe_load(template.read_text(encoding="utf-8"))
    replaced = 0
    for receiver in config["receivers"]:
        for webhook in receiver.get("webhook_configs", []):
            if webhook.get("url") == PLACEHOLDER:
                webhook["url"] = webhook_url
                replaced += 1
    if replaced != 3:
        raise ValueError("Alertmanager template must contain three webhook placeholders")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=".alertmanager-", delete=False
        ) as file:
            temporary = Path(file.name)
            yaml.safe_dump(config, file, sort_keys=False)
        # The container's unprivileged user needs read access to the bind-mounted file.
        temporary.chmod(0o644)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=ROOT / "observability/alertmanager.yml")
    parser.add_argument("--output", type=Path, default=ROOT / "data/alertmanager/alertmanager.yml")
    args = parser.parse_args()
    render(args.template, args.output, os.environ.get("ALERTMANAGER_WEBHOOK_URL", ""))
    print(f"Alertmanager configuration rendered at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
