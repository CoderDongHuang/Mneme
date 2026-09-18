import pytest

from app.core.telemetry import _trace_endpoint


def test_trace_endpoint_appends_otlp_http_path():
    assert _trace_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert _trace_endpoint("https://collector/v1/traces") == "https://collector/v1/traces"


def test_trace_endpoint_rejects_relative_values():
    with pytest.raises(ValueError):
        _trace_endpoint("collector:4318")
