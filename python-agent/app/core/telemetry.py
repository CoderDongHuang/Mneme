import os
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased


tracer = trace.get_tracer("mneme.python-agent")


def _trace_endpoint(raw_endpoint: str) -> str:
    endpoint = raw_endpoint.rstrip("/")
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must be an absolute HTTP(S) URL")
    return endpoint if endpoint.endswith("/v1/traces") else endpoint + "/v1/traces"


def configure_telemetry(app) -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    probability = min(1.0, max(0.0, float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "0.1"))))
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": os.getenv("OTEL_SERVICE_NAME", "mneme-python-agent")}
        ),
        sampler=ParentBased(TraceIdRatioBased(probability)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=_trace_endpoint(endpoint)))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    return True
