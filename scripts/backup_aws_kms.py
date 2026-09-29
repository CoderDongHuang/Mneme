#!/usr/bin/env python3
"""AWS KMS key provider adapter for backup_restore.py (AWS CLI required)."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"wrap", "unwrap"}:
        print("usage: backup_aws_kms.py wrap|unwrap VERSION", file=sys.stderr)
        return 2
    action, version = sys.argv[1:]
    key_id = os.getenv(f"BACKUP_KMS_KEY_ID_{version.upper().replace('-', '_')}", "")
    if not key_id:
        print(f"BACKUP_KMS_KEY_ID_{version.upper().replace('-', '_')} is required", file=sys.stderr)
        return 2
    payload = base64.b64decode(sys.stdin.buffer.read(), validate=True)
    command = [
        "aws", "kms", "encrypt" if action == "wrap" else "decrypt",
        "--key-id", key_id,
        "--cli-binary-format", "raw-in-base64-out",
        "--plaintext" if action == "wrap" else "--ciphertext-blob",
        "fileb:///dev/stdin",
        "--output", "json",
    ]
    result = subprocess.run(
        command, input=payload, capture_output=True, check=False, timeout=30
    )
    if result.returncode:
        print(result.stderr.decode(errors="replace")[-500:], file=sys.stderr)
        return result.returncode
    field = "CiphertextBlob" if action == "wrap" else "Plaintext"
    data = json.loads(result.stdout)
    output = data.get(field)
    if not isinstance(output, str):
        print(f"KMS did not return {field}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
