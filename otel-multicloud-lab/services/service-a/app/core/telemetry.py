import os

from opentelemetry import metrics, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

DEFAULT_OTLP_ENDPOINT = "http://otel-collector:4317"
DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS = 5000

_configured = False
_resource: Resource | None = None


def sdk_disabled() -> bool:
    return os.environ.get("OTEL_SDK_DISABLED", "false").strip().lower() == "true"


def otlp_endpoint() -> str:
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)


def metric_export_interval_millis() -> int:
    raw = os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", str(DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS))
    try:
        interval = int(raw)
    except ValueError:
        return DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS
    if interval <= 0:
        return DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS
    return interval


def _insecure_endpoint(endpoint: str) -> bool:
    return endpoint.startswith("http://") or "://" not in endpoint


def _shared_resource() -> Resource:
    global _resource
    if _resource is None:
        _resource = Resource.create(
            {
                "service.name": "service-a",
                "service.version": "1.0.0",
                "deployment.environment": "local",
                "service.namespace": "otel-multicloud-lab",
            }
        )
    return _resource


def _setup_traces(resource: Resource) -> None:
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return
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


def _setup_metrics(resource: Resource) -> None:
    current = metrics.get_meter_provider()
    if isinstance(current, MeterProvider):
        return
    endpoint = otlp_endpoint()
    exporter = OTLPMetricExporter(endpoint=endpoint, insecure=_insecure_endpoint(endpoint))
    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=metric_export_interval_millis(),
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)


def setup_telemetry() -> None:
    global _configured
    if sdk_disabled() or _configured:
        return
    resource = _shared_resource()
    _setup_traces(resource)
    _setup_metrics(resource)
    _configured = True


def shutdown_telemetry() -> None:
    if sdk_disabled() or not _configured:
        return
    for provider in (trace.get_tracer_provider(), metrics.get_meter_provider()):
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
