"""Shared types for AI providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BrainError(Exception):
    """A user-facing error. `kind` is a short machine-readable category."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class ToolCall:
    name: str
    args: Any


def strip_key(schema: Any, key: str) -> Any:
    """Return a copy of a JSON schema without `key` anywhere (some APIs reject some keywords)."""
    if isinstance(schema, dict):
        return {k: strip_key(v, key) for k, v in schema.items() if k != key}
    if isinstance(schema, list):
        return [strip_key(v, key) for v in schema]
    return schema
