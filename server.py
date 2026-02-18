"""
server.py (cloud entrypoint)

Starts the existing AI EDA bridge server (aiohttp) but binds to 0.0.0.0 and
uses $PORT when provided (Render/Koyeb/etc).

Environment variables:
- PORT: listening port (default: 8787)
- HOST: listening host (default: 0.0.0.0)
- AIEDA_TOKEN: if set, use this fixed bearer token for auth (recommended for cloud).
              If not set, a random token is generated and printed on startup.

Endpoints (same as bridge_server.py):
- GET  /status
- POST /command
- GET  /ws   (WebSocket endpoint for EasyEDA plugin; remote requires token)
- POST /shutdown
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from aiohttp import web


def _add_aieda_python_to_syspath() -> None:
    repo_root = Path(__file__).resolve().parent
    aieda_python = repo_root / "aieda_python"
    sys.path.insert(0, str(aieda_python))


def main() -> None:
    _add_aieda_python_to_syspath()

    # Import after sys.path tweak (aieda_python is not necessarily a package)
    import bridge_server  # type: ignore

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8787"))

    token = os.environ.get("AIEDA_TOKEN")
    if token and token.strip():
        token = token.strip()
        # Optional: persist it so local CLI can still read it if you ever mount storage
        try:
            bridge_server.TOKEN_FILE.write_text(token, encoding="utf-8")
        except Exception:
            pass
    else:
        token = bridge_server.generate_token()

    app = bridge_server.create_app(token)

    # Print startup info (useful in cloud logs)
    print(
        json.dumps(
            {
                "event": "server_started",
                "host": host,
                "port": port,
                "token": token,
                "ws_url": f"ws://{host}:{port}/ws (use wss:// behind TLS proxy)",
            }
        ),
        flush=True,
    )

    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
