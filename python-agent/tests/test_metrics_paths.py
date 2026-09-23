from types import SimpleNamespace

from fastapi.testclient import TestClient

from main import metric_path
from main import app


def test_metrics_use_route_template():
    request = SimpleNamespace(scope={"route": SimpleNamespace(path="/sessions/{session_id}")})
    assert metric_path(request) == "/sessions/{session_id}"


def test_metrics_bound_unmatched_paths():
    request = SimpleNamespace(scope={})
    assert metric_path(request) == "unmatched"


def test_http_metrics_use_template_for_dynamic_session_path():
    with TestClient(app) as client:
        assert client.get("/api/v1/session/dynamic-session-id").status_code == 200
        metrics = client.get("/metrics").text
    assert 'path="/api/v1/session/{session_id}"' in metrics
    assert "dynamic-session-id" not in metrics
