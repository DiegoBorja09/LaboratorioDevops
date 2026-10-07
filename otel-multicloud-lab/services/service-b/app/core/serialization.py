import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def loads(raw: bytes | str) -> Any:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return json.loads(text, parse_float=Decimal)


def dumps(payload: Any) -> str:
    tokens: list[str] = []

    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            token = f"__DECIMAL_{len(tokens)}__"
            tokens.append(format(value, "f"))
            return token
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    rendered = json.dumps(convert(payload), ensure_ascii=False, separators=(",", ":"))
    for index, number in enumerate(tokens):
        rendered = rendered.replace(f'"__DECIMAL_{index}__"', number)
    return rendered
