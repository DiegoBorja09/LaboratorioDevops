import json
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

from app.core.errors import AppError
from app.core.serialization import loads

_MAX_AMOUNT = Decimal("10000000000000000")


def parse_customer_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("customer_id es obligatorio")
    customer_id = value.strip()
    if not customer_id:
        raise ValueError("customer_id es obligatorio")
    if len(customer_id) > 255:
        raise ValueError("customer_id excede la longitud permitida")
    return customer_id


def parse_amount(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("amount debe ser un número decimal")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        if len(value) > 40:
            raise ValueError("amount debe ser un número decimal")
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount debe ser un número decimal") from exc
    else:
        raise ValueError("amount debe ser un número decimal")
    if not amount.is_finite() or amount >= _MAX_AMOUNT:
        raise ValueError("amount debe ser un número decimal")
    if amount <= 0:
        raise ValueError("amount debe ser mayor que cero")
    return amount


def parse_currency(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("currency debe tener exactamente tres caracteres")
    currency = value.strip().upper()
    if len(currency) != 3:
        raise ValueError("currency debe tener exactamente tres caracteres")
    return currency


class OrderCreate(BaseModel):
    customer_id: Annotated[str, BeforeValidator(parse_customer_id)]
    amount: Annotated[Decimal, BeforeValidator(parse_amount)]
    currency: Annotated[str, BeforeValidator(parse_currency)]

    model_config = ConfigDict(extra="ignore")


def validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = error.get("loc", ())
    field = str(location[-1]) if location else "solicitud"
    if error.get("type") == "missing":
        return f"{field} es obligatorio"
    message = str(error.get("msg", ""))
    prefix = "Value error, "
    if message.startswith(prefix):
        return message[len(prefix) :]
    return "La solicitud contiene datos inválidos"


def parse_order(raw: bytes) -> OrderCreate:
    if not raw:
        raise AppError("VALIDATION_ERROR", "El cuerpo de la solicitud no es JSON válido", 422)
    try:
        data = loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AppError(
            "VALIDATION_ERROR",
            "El cuerpo de la solicitud no es JSON válido",
            422,
        ) from exc
    if not isinstance(data, dict):
        raise AppError("VALIDATION_ERROR", "La solicitud contiene datos inválidos", 422)
    try:
        return OrderCreate.model_validate(data)
    except ValidationError as exc:
        raise AppError("VALIDATION_ERROR", validation_message(exc), 422) from exc
