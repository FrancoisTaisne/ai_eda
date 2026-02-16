"""One-shot CLI for Claude Code to interact with EasyEDA via the bridge server.

Usage examples:
  python cli.py serve                     # start bridge server (foreground)
  python cli.py status                    # check plugin connection
  python cli.py check_auth                # check EasyEDA auth state via plugin
  python cli.py get_runtime_status        # diagnostic: adapter & capabilities
  python cli.py read_schema               # read the schematic
  python cli.py list_components           # list all components
  python cli.py update_schema '<json>'    # modify the schematic
  python cli.py update_schema --payload-file operations.json --confirm
  python cli.py stop                      # shut down the bridge server
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from client import BridgeClient
from protocol import BridgeCommand, CommandMeta


def _output(data: Any) -> None:
    """Write JSON to stdout."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def _error(message: str, details: Any = None) -> int:
    _output({"ok": False, "error": message, "details": details})
    return 1


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the bridge server (blocking)."""
    from bridge_server import run_server
    run_server(host=args.host, port=args.port)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = BridgeClient(host=args.host, port=args.port)
    result = client.get_status()
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_stop(args: argparse.Namespace) -> int:
    client = BridgeClient(host=args.host, port=args.port)
    result = client.shutdown()
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_read_schema(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "include_components": True,
        "include_wires": args.include_wires,
        "include_polygons": args.include_polygons,
        "include_selected": args.include_selected,
        "include_document_source": args.include_document_source,
        "all_schematic_pages": args.all_pages,
    }
    command = BridgeCommand(action="read_schema", payload=payload)
    client = BridgeClient(host=args.host, port=args.port)
    result = client.send_command(command)
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_get_runtime_status(args: argparse.Namespace) -> int:
    command = BridgeCommand(action="get_runtime_status", payload={})
    client = BridgeClient(host=args.host, port=args.port)
    result = client.send_command(command)
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_check_auth(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {}
    if args.include_raw:
        payload["include_raw"] = True
    command = BridgeCommand(action="check_auth", payload=payload)
    client = BridgeClient(host=args.host, port=args.port)
    result = client.send_command(command)
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_list_components(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {}
    if args.selected_only:
        payload["selected_only"] = True
    if args.limit is not None:
        payload["limit"] = args.limit
    if args.fields:
        payload["fields"] = args.fields.split(",")

    command = BridgeCommand(action="list_components", payload=payload)
    client = BridgeClient(host=args.host, port=args.port)
    result = client.send_command(command)
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_update_schema(args: argparse.Namespace) -> int:
    payload_raw = args.payload
    if args.payload_file:
        if args.payload_file == "-":
            payload_raw = sys.stdin.read()
        else:
            try:
                payload_raw = Path(args.payload_file).read_text(encoding="utf-8-sig")
            except OSError as exc:
                return _error("Unable to read payload file", str(exc))

    if not payload_raw:
        return _error("Payload is required", "Pass JSON payload or --payload-file <path>")

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        return _error("Invalid JSON payload", str(exc))

    if not isinstance(payload, dict):
        return _error("Payload must be a JSON object")

    meta = CommandMeta(
        confirm=args.confirm,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
    )
    command = BridgeCommand(action="update_schema", payload=payload, meta=meta)
    client = BridgeClient(host=args.host, port=args.port)
    result = client.send_command(command)
    _output(result)
    return 0 if result.get("ok") else 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="AI EDA CLI — interact with EasyEDA via the bridge server",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bridge host")
    parser.add_argument("--port", type=int, default=8787, help="Bridge port")

    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    sub.add_parser("serve", help="Start the bridge server (foreground)")

    # status
    sub.add_parser("status", help="Check plugin connection status")

    # stop
    sub.add_parser("stop", help="Shut down the bridge server")

    # get_runtime_status
    sub.add_parser("get_runtime_status", help="Diagnostic: adapter type & capabilities")

    # check_auth
    p_auth = sub.add_parser("check_auth", help="Check EasyEDA auth status via plugin")
    p_auth.add_argument("--include-raw", action="store_true", default=False,
                        help="Include raw adapter probe details")

    # read_schema
    p_read = sub.add_parser("read_schema", help="Read the schematic")
    p_read.add_argument("--include-wires", action="store_true", default=True)
    p_read.add_argument("--include-polygons", action="store_true", default=False)
    p_read.add_argument("--include-selected", action="store_true", default=False)
    p_read.add_argument("--include-document-source", action="store_true", default=False)
    p_read.add_argument("--all-pages", action="store_true", default=False)

    # list_components
    p_list = sub.add_parser("list_components", help="List components")
    p_list.add_argument("--selected-only", action="store_true", default=False)
    p_list.add_argument("--limit", type=int, default=None)
    p_list.add_argument("--fields", type=str, default=None,
                        help="Comma-separated field names")

    # update_schema
    p_update = sub.add_parser("update_schema", help="Modify the schematic")
    p_update.add_argument("payload", nargs="?", default=None,
                          help="JSON string with operations")
    p_update.add_argument("--payload-file", type=str, default=None,
                          help="Path to JSON payload file (use '-' for stdin)")
    p_update.add_argument("--confirm", action="store_true", default=False,
                          help="Confirm write operation")
    p_update.add_argument("--dry-run", action="store_true", default=False,
                          help="Validate only, do not apply")
    p_update.add_argument("--continue-on-error", action="store_true", default=False,
                          help="Skip failed operations instead of aborting")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DISPATCH = {
    "serve": cmd_serve,
    "status": cmd_status,
    "stop": cmd_stop,
    "get_runtime_status": cmd_get_runtime_status,
    "check_auth": cmd_check_auth,
    "read_schema": cmd_read_schema,
    "list_components": cmd_list_components,
    "update_schema": cmd_update_schema,
}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler = DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
