"""Exercise current host backup keys without stopping services or reading data."""
import hashlib
import hmac
import os
import time
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

try:
    from . import backup_restore
except ImportError:
    import backup_restore


def check_keys():
    started = time.monotonic()
    result = {"configuration": "missing", "connection": "not_applicable", "operation": "not_run",
              "cleanup": "not_required", "code": "NOT_CONFIGURED"}
    configured = bool(os.getenv("BACKUP_SIGNING_KEY")) and bool(
        os.getenv("BACKUP_ENCRYPTION_KEY") or os.getenv("BACKUP_KMS_COMMAND"))
    if configured:
        result["configuration"] = "present"
        try:
            encryption, signing = backup_restore._security_keys()
            if signing is None:
                raise ValueError("Signing key unavailable")
            if os.getenv("BACKUP_KMS_COMMAND"):
                version = os.getenv("BACKUP_KEY_VERSION", "v1")
                data_key = os.urandom(32)
                wrapped = backup_restore._key_provider("wrap", version, data_key)
                recovered = backup_restore._key_provider("unwrap", version, wrapped)
                if not hmac.compare_digest(data_key, recovered):
                    raise ValueError("KMS roundtrip mismatch")
                encryption = recovered
                result["connection"] = "passed"
            nonce = os.urandom(12)
            message, aad = b"Mneme synthetic backup key diagnostic", b"mneme-key-diagnostic-v1"
            cipher = AESGCM(encryption)
            ciphertext = cipher.encrypt(nonce, message, aad)
            signature = hmac.new(signing, ciphertext, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, hmac.new(signing, ciphertext, hashlib.sha256).digest()):
                raise ValueError("Signing roundtrip mismatch")
            if cipher.decrypt(nonce, ciphertext, aad) != message:
                raise ValueError("Encryption roundtrip mismatch")
            corrupted = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
            if hmac.compare_digest(signature, hmac.new(signing, corrupted, hashlib.sha256).digest()):
                raise ValueError("Signature accepted tampered ciphertext")
            try:
                cipher.decrypt(nonce, corrupted, aad)
            except InvalidTag:
                pass
            else:
                raise ValueError("Encryption accepted tampered ciphertext")
            result.update(operation="passed", code="OK")
        except Exception:
            # Provider stderr, command lines, wrapped keys and exception chains
            # never leave the executor or enter ordinary diagnostics logs.
            result.update(operation="failed", code="KEY_CHECK_FAILED")
    return {**result, "checked_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": round((time.monotonic() - started) * 1000)}
