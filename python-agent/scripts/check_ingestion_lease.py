"""Exercise renewal, process death and owner isolation against configured Redis.

Uses a unique synthetic task; does not touch existing task keys. Run inside the
Agent container: python scripts/check_ingestion_lease.py.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge.cancellation import _release_lease, _renew_lease  # noqa: E402


def main():
    task = uuid.uuid4().hex
    key = f"mneme:ingestion:active:lease_probe:{task}"
    client = redis.Redis(host=settings.redis_host, port=settings.redis_port,
                         db=settings.redis_db, password=settings.redis_password or None,
                         socket_timeout=3, socket_connect_timeout=3)
    successor = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="mneme-lease-") as directory:
        ready = Path(directory) / "ready"
        code = """
import sys,time
from pathlib import Path
from app.knowledge import cancellation as c
c._LEASE_SECONDS=2
c._LEASE_RENEW_SECONDS=0.2
with c.ingestion_task('lease_probe',sys.argv[1]):
    Path(sys.argv[2]).write_text('ready')
    time.sleep(30)
"""
        process = subprocess.Popen([sys.executable, "-c", code, task, str(ready)],
                                   cwd=Path(__file__).resolve().parents[1])
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Lease probe worker exited before acquiring lease")
                time.sleep(0.05)
            assert ready.exists(), "Worker did not acquire lease"
            owner = client.get(key)
            assert owner
            time.sleep(3)  # Longer than the child's two-second TTL.
            assert client.get(key) == owner, "Heartbeat failed to keep lease alive"
            assert not client.set(key, successor, nx=True, ex=2), "Duplicate acquired active lease"
            process.kill()  # Deliberate crash: bypass context-manager cleanup.
            process.wait(timeout=3)
            deadline = time.monotonic() + 4
            while client.exists(key) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not client.exists(key), "Crashed worker lease did not expire"
            assert client.set(key, successor, nx=True, ex=10)
            assert not _renew_lease(client, key, owner), "Old owner renewed successor lease"
            assert not _release_lease(client, key, owner), "Old owner deleted successor lease"
            assert client.get(key) == successor.encode()
            assert _release_lease(client, key, successor)
            print(json.dumps({"renewal_beyond_ttl": True, "duplicate_rejected": True,
                              "crash_recovered": True, "successor_owner_isolated": True}))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            _release_lease(client, key, successor)
            client.close()


if __name__ == "__main__":
    main()
