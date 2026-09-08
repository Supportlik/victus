"""Row ↔ JSON encoding for the JSONL files.

Dates and times become ISO strings, binary columns base64; everything else is
JSON as-is. Decoding uses the column types of the current schema, so the JSONL
stays dialect-neutral and readable with ``jq``.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Table


def encode_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Decimal):
        return float(value)
    return value  # JSON columns: dict / list


def encode_row(row: Mapping[str, Any]) -> str:
    return json.dumps({k: encode_value(v) for k, v in row.items()}, ensure_ascii=False)


def _python_type(table: Table, column: str) -> type[Any] | None:
    """Python type of a column; unwraps ``TypeDecorator`` (e.g. ``UTCDateTime``)."""
    type_ = table.c[column].type
    for candidate in (type_, getattr(type_, "impl", None)):
        if candidate is None:
            continue
        try:
            return candidate.python_type
        except (NotImplementedError, AttributeError):
            continue
    return None


def decode_row(table: Table, line: str) -> tuple[dict[str, Any], list[str]]:
    """Return ``(row, unknown_columns)``; unknown columns are dropped, not inserted."""
    raw = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError(f"{table.name}: JSONL row is not an object")
    row: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in raw.items():
        if key not in table.c:
            unknown.append(key)
            continue
        row[key] = _decode_value(table, key, value)
    return row, unknown


def _decode_value(table: Table, column: str, value: Any) -> Any:
    if value is None:
        return None
    ptype = _python_type(table, column)
    if ptype is datetime and isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    if ptype is date and isinstance(value, str):
        return date.fromisoformat(value)
    if ptype is time and isinstance(value, str):
        return time.fromisoformat(value)
    if ptype is bytes and isinstance(value, str):
        return base64.b64decode(value)
    if ptype is bool and isinstance(value, int) and not isinstance(value, bool):
        return bool(value)
    return value
