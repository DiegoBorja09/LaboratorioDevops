import logging
import os
import warnings

from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider, set_logger_provider
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

DEFAULT_OTLP_ENDPOINT = "http://otel-collector:4317"
DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS = 5000

_PROCESS_METRIC_CONFIG = {
    "process.cpu.utilization": None,
    "process.memory.usage": None,
}

_configured = False
_process_metrics_enabled = False
_log_handler: logging.Handler | None = None
_resource: Resource | None = None


class _EventLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        event_name = getattr(record, "event.name", None)
        return isinstance(event_name, str) and bool(event_name)


def sdk_disabled() -> bool:
    """Única decisión del SDK. true omite providers, exportadores e instrumentación."""
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
                "service.name": "service-b",
                "service.version": "1.0.0",
                "deployment.environment": "local",
                "service.namespace": "otel-multicloud-lab",
            }
        )
    return _resource


def _setup_traces(resource: Resource) -> None:
    if sdk_disabled():
        return
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
    if sdk_disabled():
        return
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


def attach_log_handler() -> None:
    if sdk_disabled() or _log_handler is None:
        return
    root = logging.getLogger()
    if _log_handler not in root.handlers:
        root.addHandler(_log_handler)


def _setup_logs(resource: Resource) -> None:
    global _log_handler
    if sdk_disabled():
        return
    current = get_logger_provider()
    if isinstance(current, LoggerProvider):
        attach_log_handler()
        return
    endpoint = otlp_endpoint()
    exporter = OTLPLogExporter(endpoint=endpoint, insecure=_insecure_endpoint(endpoint))
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(
        BatchLogRecordProcessor(exporter, schedule_delay_millis=1000)
    )
    set_logger_provider(provider)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            message=".*LoggingHandler.*",
        )
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    handler.addFilter(_EventLogFilter())
    _log_handler = handler
    attach_log_handler()


def _setup_process_metrics() -> None:
    global _process_metrics_enabled
    if sdk_disabled() or _process_metrics_enabled:
        return
    from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor

    SystemMetricsInstrumentor(config=_PROCESS_METRIC_CONFIG).instrument()
    _process_metrics_enabled = True


def setup_telemetry() -> None:
    global _configured
    if sdk_disabled() or _configured:
        return
    resource = _shared_resource()
    _setup_traces(resource)
    _setup_metrics(resource)
    _setup_logs(resource)
    _setup_process_metrics()
    _configured = True


def shutdown_telemetry() -> None:
    global _log_handler
    if sdk_disabled() or not _configured:
        return
    if _log_handler is not None:
        logging.getLogger().removeHandler(_log_handler)
        _log_handler.flush = lambda: None
        _log_handler = None
    for provider in (
        trace.get_tracer_provider(),
        metrics.get_meter_provider(),
        get_logger_provider(),
    ):
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
