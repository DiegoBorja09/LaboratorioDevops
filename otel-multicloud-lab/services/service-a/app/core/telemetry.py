import os

from opentelemetry import trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

DEFAULT_OTLP_ENDPOINT = "http://otel-collector:4317"

_configured = False


def sdk_disabled() -> bool:
    return os.environ.get("OTEL_SDK_DISABLED", "false").strip().lower() == "true"


def otlp_endpoint() -> str:
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)


def _insecure_endpoint(endpoint: str) -> bool:
    return endpoint.startswith("http://") or "://" not in endpoint


def setup_telemetry() -> None:
    global _configured
    if sdk_disabled() or _configured:
        return

    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        _configured = True
        return

    resource = Resource.create(
        {
            "service.name": "service-a",
            "service.version": "1.0.0",
            "deployment.environment": "local",
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = otlp_endpoint()
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=_insecure_endpoint(endpoint))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    set_global_textmap(
        CompositePropagator(
            [
                TraceContextTextMapPropagator(),
                W3CBaggagePropagator(),
            ]
        )
    )
    _configured = True


def shutdown_telemetry() -> None:
    if sdk_disabled() or not _configured:
        return
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()
