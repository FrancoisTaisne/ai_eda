"""HTTP bridge client used by the CLI to talk to bridge_server."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from protocol import BridgeCommand

TOKEN_FILE = Path(__file__).parent / ".bridge_token"


def _load_token() -> str:
    """Load auth token from disk. Returns empty string if not found."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


@dataclass(slots=True)
class BridgeClient:
    host: str = "127.0.0.1"
    port: int = 8787
    timeout_seconds: float = 10.0
    token: str = field(default_factory=_load_token)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # -- public API ----------------------------------------------------------

    def send_command(self, command: BridgeCommand) -> dict[str, Any]:
        """Send a command to the bridge server and return the JSON result."""
        data = json.dumps(command.to_json()).encode("utf-8")
        return self._post("/command", data)

    def get_status(self) -> dict[str, Any]:
        """Query the bridge server status (plugin connection, etc.)."""
        return self._get("/status")

    def shutdown(self) -> dict[str, Any]:
        """Ask the bridge server to shut down gracefully."""
        return self._post("/shutdown", b"")

    # -- internals -----------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str) -> dict[str, Any]:
        req = Request(f"{self.base_url}{path}", method="GET",
                      headers=self._auth_headers())
        return self._execute(req)

    def _post(self, path: str, data: bytes) -> dict[str, Any]:
        req = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self._auth_headers(),
            method="POST",
        )
        return self._execute(req)

    def _execute(self, req: Request) -> dict[str, Any]:
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"HTTP {exc.code}", "details": body}
        except URLError as exc:
            return {"ok": False, "error": "Connection failed", "details": str(exc)}

        if not body.strip():
            return {"ok": True, "result": None}

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid JSON response", "details": body}

        return parsed if isinstance(parsed, dict) else {"ok": True, "result": parsed}
