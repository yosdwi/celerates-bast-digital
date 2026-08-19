"""Plain JSON type aliases.

These lived in infrastructure/nocodb.py until the NocoDB REST client was
removed; nothing about them was NocoDB-specific.
"""

from __future__ import annotations

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonRecordList = list[dict[str, JsonValue]]
