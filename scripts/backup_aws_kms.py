#!/usr/bin/env python3
"""AWS KMS key provider adapter for backup_restore.py (AWS CLI required)."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile

if __package__:
    from .backup_aws_preflight import kms_key_id, region_arguments, CloudPreflightError
else:
    from backup_aws_preflight import kms_key_id, region_arguments, CloudPreflightError


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"wrap", "unwrap"}:
        print("usage: backup_aws_kms.py wrap|unwrap VERSION", file=sys.stderr)
        return 2
    action, version = sys.argv[1:]
    try:
        key_id = kms_key_id(version)
        payload = base64.b64decode(sys.stdin.buffer.read(), validate=True)
    except (CloudPreflightError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    # Use a temporary file instead of /dev/stdin so the adapter works on
    # Windows as well as Unix hosts. The file is removed before returning.
    with tempfile.NamedTemporaryFile(prefix="mneme-kms-", suffix=".bin", delete=False) as handle:
        handle.write(payload)
        input_path = handle.name
    try:
        command = [
            "aws", "kms", "encrypt" if action == "wrap" else "decrypt",
            "--key-id", key_id,
            "--cli-binary-format", "raw-in-base64-out",
            "--plaintext" if action == "wrap" else "--ciphertext-blob",
            f"fileb://{input_path}",
            "--output", "json",
            *region_arguments(),
        ]
        result = subprocess.run(command, capture_output=True, check=False, timeout=30)
        if result.returncode:
            print(result.stderr.decode(errors="replace")[-500:], file=sys.stderr)
            return result.returncode
        field = "CiphertextBlob" if action == "wrap" else "Plaintext"
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            print("KMS did not return an object response", file=sys.stderr)
            return 2
        output = data.get(field)
        if not isinstance(output, str) or not output:
            print(f"KMS did not return {field}", file=sys.stderr)
            return 2
        decoded = base64.b64decode(output, validate=True)
        if not decoded or (action == "unwrap" and len(decoded) != 32):
            print(f"KMS returned invalid {field}", file=sys.stderr)
            return 2
        sys.stdout.write(output)
        return 0
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"KMS command failed: {error}", file=sys.stderr)
        return 1
    finally:
        try:
            os.unlink(input_path)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
