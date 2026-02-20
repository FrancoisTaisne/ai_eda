"""Shared command protocol for the Python console side."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "1.0.0"

SUPPORTED_ACTIONS = {
    "check_auth",
    "get_runtime_status",
    "search_component",
    "read_schema",
    "update_schema",
    "list_components",
}

_counter = 0


def create_command_id() -> str:
    """Generate a unique command ID (timestamp + counter)."""
    global _counter
    _counter += 1
    return f"cmd-{int(time.time() * 1000)}-{_counter}"


@dataclass(slots=True)
class CommandMeta:
    confirm: bool = False
    dry_run: bool = False
    continue_on_error: bool = False


@dataclass(slots=True)
class BridgeCommand:
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    meta: CommandMeta = field(default_factory=CommandMeta)
    id: str = field(default_factory=create_command_id)

    def validate(self) -> None:
        if self.action not in SUPPORTED_ACTIONS:
            allowed = ", ".join(sorted(SUPPORTED_ACTIONS))
            raise ValueError(f"Unsupported action '{self.action}'. Allowed: {allowed}")

    def to_json(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "type": "command",
            "action": self.action,
            "payload": self.payload,
            "meta": {
                "confirm": self.meta.confirm,
                "dry_run": self.meta.dry_run,
                "continue_on_error": self.meta.continue_on_error,
            },
            "protocol_version": PROTOCOL_VERSION,
        }
