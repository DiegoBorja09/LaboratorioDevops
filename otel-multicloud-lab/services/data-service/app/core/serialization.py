import json
from datetime import datetime
from typing import Any
from uuid import UUID


def loads(raw: bytes | str) -> Any:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return json.loads(text)


def dumps(payload: Any) -> str:
    def convert(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return json.dumps(convert(payload), ensure_ascii=False, separators=(",", ":"))
