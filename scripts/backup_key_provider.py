#!/usr/bin/env python3
"""Deterministic AES-GCM key provider for isolated backup drills only."""

from __future__ import annotations

import base64
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"wrap", "unwrap"}:
        print("usage: backup_key_provider.py wrap|unwrap VERSION", file=sys.stderr)
        return 2
    master = os.environ.get("MNEME_DRILL_MASTER_KEY", "").encode()
    if len(master) < 16:
        print("MNEME_DRILL_MASTER_KEY must contain at least 16 bytes", file=sys.stderr)
        return 2
    key = __import__("hashlib").sha256(master + b":" + sys.argv[2].encode()).digest()
    payload = base64.b64decode(sys.stdin.buffer.read(), validate=True)
    if sys.argv[1] == "wrap":
        nonce = os.urandom(12)
        result = nonce + AESGCM(key).encrypt(nonce, payload, sys.argv[2].encode())
    else:
        if len(payload) < 28:
            print("wrapped key is truncated", file=sys.stderr)
            return 2
        result = AESGCM(key).decrypt(payload[:12], payload[12:], sys.argv[2].encode())
    sys.stdout.write(base64.b64encode(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
