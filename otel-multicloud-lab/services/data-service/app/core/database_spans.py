from opentelemetry.attributes import BoundedAttributes
from opentelemetry.sdk.trace import SpanProcessor

_DATABASE_KEYS = ("db.system", "db.system.name", "db.statement", "db.name", "db.operation")
_DROPPED_KEYS = {"db.statement", "db.query.text", "db.user", "db.connection_string"}


def _operation_token(value: str) -> str:
    if not value:
        return ""
    token = value.split()[0].strip().upper()
    if token.isalpha():
        return token
    return ""


class DatabaseSemanticSpanProcessor(SpanProcessor):
    """Completa las convenciones actuales y retira SQL, usuarios y URLs."""

    def on_start(self, span: object, parent_context: object | None = None) -> None:
        del span, parent_context

    def on_end(self, span: object) -> None:
        current = getattr(span, "_attributes", None)
        if current is None:
            return
        attributes = dict(current)
        if not any(attributes.get(key) is not None for key in _DATABASE_KEYS):
            return
        system = attributes.get("db.system.name") or attributes.get("db.system")
        namespace = attributes.get("db.namespace") or attributes.get("db.name")
        operation = attributes.get("db.operation.name") or attributes.get("db.operation") or getattr(span, "name", "")
        address = attributes.get("server.address") or attributes.get("net.peer.name")
        port = attributes.get("server.port")
        if port is None:
            port = attributes.get("net.peer.port")
        if system:
            attributes["db.system.name"] = str(system)
        if namespace:
            attributes["db.namespace"] = str(namespace)
        token = _operation_token(str(operation))
        if token:
            attributes["db.operation.name"] = token
        if isinstance(address, str) and address and "://" not in address:
            attributes["server.address"] = address
        if port is not None:
            attributes["server.port"] = int(port)
        for key in list(attributes):
            lowered = key.lower()
            value = attributes.get(key)
            if key in _DROPPED_KEYS or "password" in lowered or "secret" in lowered:
                del attributes[key]
                continue
            if isinstance(value, str) and "://" in value:
                del attributes[key]
        span._attributes = BoundedAttributes(attributes=attributes)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True
