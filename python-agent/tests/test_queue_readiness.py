import asyncio
from fastapi import Response
from app.api import health


def test_reflection_queue_outage_is_explicit_degradation(monkeypatch):
    monkeypatch.setattr(health.vector_store, "heartbeat", lambda: True)
    monkeypatch.setattr(health.reflection_scheduler, "queue_available", lambda: False)
    response = Response()
    result = asyncio.run(health.readiness(response))
    assert response.status_code == 503
    assert result["status"] == "degraded"
    assert result["components"]["reflection_queue"] == "unavailable_no_memory_fallback"
