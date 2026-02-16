"""Minimal console to drive EasyEDA commands through the local plugin bridge."""

from __future__ import annotations

import argparse
import json

from client import BridgeClient
from protocol import BridgeCommand


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIEDA Python console")
    parser.add_argument("--host", default="127.0.0.1", help="Bridge host")
    parser.add_argument("--port", type=int, default=8787, help="Bridge port")
    return parser


def print_help() -> None:
    print("Commands:")
    print("  help")
    print("  check_auth")
    print("  read_schema")
    print("  list_components")
    print("  update_schema <json_payload>")
    print("  quit")


def main() -> int:
    args = build_parser().parse_args()
    client = BridgeClient(host=args.host, port=args.port)

    print(f"AIEDA console connected to {client.base_url}")
    print_help()

    while True:
        try:
            raw = input("aieda> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return 0

        if not raw:
            continue
        if raw in {"quit", "exit"}:
            return 0
        if raw == "help":
            print_help()
            continue

        if raw == "check_auth":
            command = BridgeCommand(action="check_auth")
        elif raw == "read_schema":
            command = BridgeCommand(action="read_schema")
        elif raw == "list_components":
            command = BridgeCommand(action="list_components")
        elif raw.startswith("update_schema"):
            _, _, payload_raw = raw.partition(" ")
            if not payload_raw.strip():
                print("Payload is required, example: update_schema {\"changes\":[]}")
                continue
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError as exc:
                print(f"Invalid JSON payload: {exc}")
                continue
            if not isinstance(payload, dict):
                print("Payload must be a JSON object.")
                continue
            command = BridgeCommand(action="update_schema", payload=payload)
        else:
            print("Unknown command. Type 'help'.")
            continue

        result = client.send_command(command)
        print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
