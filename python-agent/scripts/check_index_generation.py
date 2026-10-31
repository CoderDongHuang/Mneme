"""Verify durable generation fencing with real MySQL transactions.

Run in an upgraded Agent container with AUXILIARY_STORE_BACKEND=mysql.
Only a unique synthetic user row is changed and removed.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.knowledge.generations import GenerationStore, StaleGeneration  # noqa: E402
from app.storage.mysql import connection  # noqa: E402


def main():
    if settings.auxiliary_store_backend != "mysql":
        raise RuntimeError("This verification requires the shared MySQL backend")
    user = "generation_probe_" + uuid.uuid4().hex
    first, second = GenerationStore(), GenerationStore()
    try:
        first.begin(user, "kb", "doc", 1)
        paused, resume = Event(), Event()

        def stale_worker():
            paused.set()  # Lease checkpoint completed, storage write not begun.
            assert resume.wait(15)
            try:
                with first.writing(user, "kb", "doc", 1):
                    raise AssertionError("Old generation entered storage mutation")
            except StaleGeneration:
                return True

        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(stale_worker)
            try:
                assert paused.wait(5)
                second.begin(user, "kb", "doc", 2)
                with second.writing(user, "kb", "doc", 2):
                    pass
            finally:
                resume.set()
            assert old.result(10)
        assert GenerationStore().snapshot(user)["libraries"]["kb"]["documents"]["doc"]["active"] == 2

        # A holder has no TTL. Even a successor begin must wait until the DB
        # transaction ends; process death rolls back and releases the row lock.
        with tempfile.TemporaryDirectory(prefix="generation-probe-") as directory:
            ready = Path(directory) / "ready"
            code = """
import sys,time
from pathlib import Path
from app.knowledge.generations import GenerationStore
with GenerationStore().writing(sys.argv[1], 'kb', 'doc', 2, repair=True):
    Path(sys.argv[2]).write_text('locked')
    time.sleep(30)
"""
            child = subprocess.Popen([sys.executable, "-c", code, user, str(ready)], cwd=Path(__file__).resolve().parents[1])
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    assert child.poll() is None, "Lock holder exited early"
                    time.sleep(0.05)
                assert ready.exists(), "Lock holder failed to start"
                entered = Event()

                def successor():
                    entered.set()
                    return second.begin(user, "kb", "doc", 3)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    waiting = pool.submit(successor)
                    try:
                        assert entered.wait(5)
                        time.sleep(0.5)
                        assert not waiting.done(), "MySQL row lock did not serialize writers"
                    finally:
                        child.kill()
                        child.wait(timeout=5)
                    assert waiting.result(10) == 3
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        with second.writing(user, "kb", "doc", 3):
            pass
        first.tombstone(user)
        try:
            second.begin(user, "kb", "late-document", 4)
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Deleted user resurrected")
        print("PASS: MySQL stale writer fenced; publication durable; row lock serializes writers; process death releases lock; deletion prevents resurrection")
    finally:
        with connection() as opened:
            cursor = opened.cursor()
            try:
                cursor.execute("DELETE FROM knowledge_index_state WHERE user_id=%s", (user,))
            finally:
                cursor.close()


if __name__ == "__main__":
    main()
