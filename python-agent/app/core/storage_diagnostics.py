"""Explicit synthetic Qdrant business probes; never touch tenant collections."""
import time
import uuid
import threading
from contextlib import nullcontext
from datetime import datetime, timezone

from app.knowledge.vector_store import vector_store
from qdrant_client import models

_probe_lock = threading.Lock()


def check_storage(clients=None):
    if not _probe_lock.acquire(blocking=False):
        return {"configuration": "present", "connection": "not_checked", "operation": "not_run",
                "cleanup": "not_required", "code": "BUSY", "latency_ms": 0,
                "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        return _check_storage(clients)
    finally:
        _probe_lock.release()


def _check_storage(clients):
    result = {"configuration": "present", "connection": "not_checked", "operation": "not_run",
              "cleanup": "not_required", "code": "NOT_RUN"}
    started = time.monotonic()
    deadline = started + 45
    clients = vector_store.clients if clients is None else clients
    connection_ok, operation_ok, cleanup_ok = True, True, True
    attempted = False
    for client in clients:
        if time.monotonic() >= deadline:
            # Unchecked shards can never contribute to an all-passed result.
            connection_ok = operation_ok = False
            break
        name = "mneme_diagnostic_" + uuid.uuid4().hex
        connected, write_attempted = False, False
        context = client.diagnostic_client() if callable(getattr(client, "diagnostic_client", None)) else nullcontext(client.raw)
        raw = None

        def call(method, *args, **kwargs):
            if time.monotonic() >= deadline:
                raise TimeoutError("Diagnostic deadline exceeded")
            return getattr(raw, method)(*args, **kwargs)

        try:
            raw = context.__enter__()
            call("get_collections")
            connected = True
            write_attempted = attempted = True
            call("create_collection", name, vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
            point = str(uuid.uuid4())
            call("upsert", name, [models.PointStruct(id=point, vector=[1.0, 0.0], payload={"synthetic": True})], wait=True)
            found = call("retrieve", name, [point], with_payload=True, with_vectors=True)
            if len(found) != 1 or found[0].payload != {"synthetic": True} or found[0].vector != [1.0, 0.0]:
                raise ValueError("Diagnostic readback mismatch")
            # Test search as well as point lookup with the same configured client.
            matches = call("query_points", name, query=[1.0, 0.0], limit=1).points
            if len(matches) != 1 or str(matches[0].id) != point:
                raise ValueError("Diagnostic search mismatch")
            call("delete", name, models.PointIdsList(points=[point]), wait=True)
            if call("retrieve", name, [point]):
                raise ValueError("Diagnostic point deletion mismatch")
        except Exception:
            connection_ok = connection_ok and connected
            operation_ok = False
        finally:
            if write_attempted:
                try:
                    raw.delete_collection(name)
                    if raw.collection_exists(name):
                        raise ValueError("Diagnostic collection deletion mismatch")
                except Exception:
                    cleanup_ok = False
            if raw is not None:
                try:
                    context.__exit__(None, None, None)
                except Exception:
                    cleanup_ok = False
    if not clients:
        result.update(configuration="missing", code="NOT_CONFIGURED")
    else:
        result.update(connection="passed" if connection_ok else "failed",
                      operation=("passed" if operation_ok else "failed") if attempted else "not_run",
                      cleanup=("passed" if cleanup_ok else "failed") if attempted else "not_required",
                      code="CLEANUP_FAILED" if not cleanup_ok else "CONNECTION_FAILED" if not connection_ok
                      else "OPERATION_FAILED" if not operation_ok else "OK")
    return {**result, "checked_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": round((time.monotonic() - started) * 1000)}
