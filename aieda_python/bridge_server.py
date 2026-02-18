"""Bridge server: HTTP + WebSocket gateway between CLI and EasyEDA plugin.

Exposes:
  - POST /command   : receive a JSON command, forward to plugin via WS, return result
  - GET  /status    : plugin connection state
  - GET  /ws        : WebSocket endpoint for aieda_js plugin
  - POST /shutdown  : graceful server shutdown
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from aiohttp import web, WSMsgType

logger = logging.getLogger("bridge_server")

# ---------------------------------------------------------------------------
# Auth token
# ---------------------------------------------------------------------------

TOKEN_FILE = Path(__file__).parent / ".bridge_token"


def generate_token() -> str:
    """Generate a random token and persist it to disk for the CLI."""
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def load_token() -> str | None:
    """Load the token from disk (used by client)."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return None


_server_token: str = ""

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_plugin_ws: web.WebSocketResponse | None = None
_pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
_plugin_meta: dict[str, Any] = {}

COMMAND_TIMEOUT_S = 30.0

# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


def _check_token(request: web.Request) -> bool:
    """Verify the Bearer token from Authorization header or ?token= query."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _server_token:
        return True
    if request.query.get("token") == _server_token:
        return True
    return False


@web.middleware
async def auth_middleware(request: web.Request, handler):
    # WebSocket and status endpoints check token themselves or are open
    if request.path == "/ws":
        # WS token checked inside ws_handler via query param
        return await handler(request)
    if not _check_token(request):
        return _json_response({"ok": False, "error": "Unauthorized"}, status=401)
    return await handler(request)


# ---------------------------------------------------------------------------
# WebSocket handler (plugin side)
# ---------------------------------------------------------------------------


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    global _plugin_ws, _plugin_meta

    # Plugin authenticates via ?token= query param.
    # Allow unauthenticated local WebSocket connections (plugin in EasyEDA Pro
    # cannot read the token file from disk).
    if not _check_token(request):
        peername = request.transport.get_extra_info("peername")
        remote_ip = peername[0] if peername else None
        if remote_ip not in ("127.0.0.1", "::1"):
            return web.Response(text="Unauthorized", status=401)
        logger.info("WebSocket connection from localhost accepted without token")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    if _plugin_ws is not None and not _plugin_ws.closed:
        logger.warning("A plugin is already connected — replacing old connection")
        await _plugin_ws.close()

    _plugin_ws = ws
    _plugin_meta = {}
    logger.info("Plugin WebSocket connected")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await _handle_plugin_message(msg.data)
            elif msg.type == WSMsgType.ERROR:
                logger.error("WebSocket error: %s", ws.exception())
    finally:
        _plugin_ws = None
        _plugin_meta = {}
        # Cancel any pending futures
        for fut in _pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Plugin disconnected"))
        _pending.clear()
        logger.info("Plugin WebSocket disconnected")

    return ws


async def _handle_plugin_message(raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Non-JSON message from plugin: %s", raw[:200])
        return

    msg_type = data.get("type")

    # Handle bridge_connected event
    if msg_type == "event" and data.get("event") == "bridge_connected":
        _plugin_meta.update(data.get("payload", {}))
        logger.info("Plugin identified: %s", _plugin_meta)
        return

    # Handle pong
    if msg_type == "pong":
        return

    # Handle command result — resolve pending future
    if msg_type == "result":
        cmd_id = data.get("id")
        if cmd_id and cmd_id in _pending:
            fut = _pending.pop(cmd_id)
            if not fut.done():
                fut.set_result(data)
        return

    logger.debug("Unhandled plugin message type=%s", msg_type)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


async def handle_command(request: web.Request) -> web.Response:
    """POST /command — forward a command to the plugin and wait for its result."""
    if _plugin_ws is None or _plugin_ws.closed:
        return _json_response(
            {"ok": False, "error": "Plugin not connected"}, status=503
        )

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _json_response(
            {"ok": False, "error": "Invalid JSON body"}, status=400
        )

    cmd_id = body.get("id")
    if not cmd_id:
        return _json_response(
            {"ok": False, "error": "Command must include an 'id' field"}, status=400
        )

    # Create a future for the response
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[dict[str, Any]] = loop.create_future()
    _pending[cmd_id] = fut

    # Forward command to plugin via WebSocket
    try:
        await _plugin_ws.send_str(json.dumps(body))
    except Exception as exc:
        _pending.pop(cmd_id, None)
        return _json_response(
            {"ok": False, "error": f"Failed to send to plugin: {exc}"}, status=502
        )

    # Wait for the response
    try:
        result = await asyncio.wait_for(fut, timeout=COMMAND_TIMEOUT_S)
        return _json_response(result)
    except asyncio.TimeoutError:
        _pending.pop(cmd_id, None)
        return _json_response(
            {"ok": False, "error": "Command timed out waiting for plugin response"},
            status=504,
        )
    except ConnectionError as exc:
        return _json_response(
            {"ok": False, "error": str(exc)}, status=502
        )


async def handle_status(request: web.Request) -> web.Response:
    """GET /status — plugin connection state."""
    connected = _plugin_ws is not None and not _plugin_ws.closed
    return _json_response({
        "ok": True,
        "plugin_connected": connected,
        "plugin_meta": _plugin_meta if connected else None,
        "pending_commands": len(_pending),
        "timestamp": time.time(),
    })


async def handle_shutdown(request: web.Request) -> web.Response:
    """POST /shutdown — graceful server shutdown."""
    logger.info("Shutdown requested")
    # Schedule shutdown after sending the response
    asyncio.get_running_loop().call_later(0.1, _shutdown_app, request.app)
    return _json_response({"ok": True, "message": "Shutting down"})


def _shutdown_app(app: web.Application) -> None:
    raise web.GracefulExit()


# ---------------------------------------------------------------------------
# Ping loop
# ---------------------------------------------------------------------------


async def _ping_loop(app: web.Application) -> None:
    """Send periodic pings to the connected plugin."""
    while True:
        await asyncio.sleep(15)
        if _plugin_ws and not _plugin_ws.closed:
            try:
                ping_msg = json.dumps({
                    "type": "ping",
                    "id": f"ping-{int(time.time() * 1000)}",
                    "timestamp": time.time(),
                })
                await _plugin_ws.send_str(ping_msg)
            except Exception:
                pass


async def start_background_tasks(app: web.Application) -> None:
    app["ping_task"] = asyncio.create_task(_ping_loop(app))


async def cleanup_background_tasks(app: web.Application) -> None:
    app["ping_task"].cancel()
    try:
        await app["ping_task"]
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(token: str) -> web.Application:
    global _server_token
    _server_token = token

    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/command", handle_command)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/shutdown", handle_shutdown)

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    return app


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    token = generate_token()
    app = create_app(token)
    logger.info("Starting bridge server on %s:%d", host, port)
    logger.info("Auth token written to %s", TOKEN_FILE)
    # Print token to stdout so the launching process can capture it
    print(json.dumps({"event": "server_started", "token": token, "host": host, "port": port}))
    sys.stdout.flush()
    web.run_app(app, host=host, port=port, print=lambda msg: logger.info(msg))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_response(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        status=status,
    )


if __name__ == "__main__":
    run_server()
