"""One-shot CLI to interact with EasyEDA through the bridge server.

Usage examples:
  python cli.py serve
  python cli.py status
  python cli.py check_auth
  python cli.py get_runtime_status
  python cli.py search_component "ESP32-C6-WROOM-1-N8"
  python cli.py read_schema
  python cli.py list_components
  python cli.py update_schema --payload-file operations.json --confirm
  python cli.py export_requirements_template --output needs.json
  python cli.py plan_requirements --requirements-file needs.json
  python cli.py apply_requirements --requirements-file needs.json --confirm
  python cli.py verify_operations --payload-file ops.json
  python cli.py stop
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from client import BridgeClient
from protocol import BridgeCommand, CommandMeta
from requirements_planner import (
    PlannedPayload,
    RequirementsError,
    build_payload_from_requirements,
    load_requirements_file,
)


def _output(data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def _error(message: str, details: Any = None) -> int:
    _output({"ok": False, "error": message, "details": details})
    return 1


def _write_json_file(path: str, data: Any) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_meta(args: argparse.Namespace) -> CommandMeta:
    return CommandMeta(
        confirm=getattr(args, "confirm", False),
        dry_run=getattr(args, "dry_run", False),
        continue_on_error=getattr(args, "continue_on_error", False),
    )


def _resolve_component_keyword(client: BridgeClient, keyword: str) -> Any:
    command = BridgeCommand(action="search_component", payload={"keyword": keyword})
    result = client.send_command(command)
    if not result.get("ok"):
        raise RequirementsError(
            f"search_component failed for keyword '{keyword}': "
            f"{result.get('error', 'unknown error')}"
        )
    return result.get("result")


def _build_planned_payload(
    args: argparse.Namespace, *, client: BridgeClient | None
) -> PlannedPayload:
    requirements = load_requirements_file(args.requirements_file, encoding=args.encoding)

    resolver = None
    if not args.no_auto_resolve:
        if client is None:
            raise RequirementsError(
                "auto-resolve requires a bridge client, but none is available"
            )
        resolver = lambda keyword: _resolve_component_keyword(client, keyword)

    return build_payload_from_requirements(
        requirements,
        resolve_component=resolver,
        default_stub_length=args.default_stub_length,
    )


def _normalize_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    return None


def _canonical_line(line: Any) -> tuple[tuple[int | float, int | float], ...] | None:
    if not isinstance(line, list) or len(line) < 4 or len(line) % 2 != 0:
        return None
    points: list[tuple[int | float, int | float]] = []
    for i in range(0, len(line), 2):
        x = _normalize_number(line[i])
        y = _normalize_number(line[i + 1])
        if x is None or y is None:
            return None
        points.append((x, y))
    forward = tuple(points)
    backward = tuple(reversed(points))
    return forward if forward <= backward else backward


def _extract_available_update_operations(runtime_result: dict[str, Any]) -> set[str]:
    root = runtime_result.get("result")
    if not isinstance(root, dict):
        return set()
    candidates = [root, root.get("status"), root.get("capabilities")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        update_ops = candidate.get("update_operations")
        if not isinstance(update_ops, dict):
            continue
        available = update_ops.get("available")
        if isinstance(available, list):
            return {item for item in available if isinstance(item, str)}
    return set()


def _verify_plan_against_schema(
    payload: dict[str, Any], read_schema_result: dict[str, Any]
) -> dict[str, Any]:
    expected_components: list[tuple[str, str, int | float, int | float]] = []
    expected_wires: list[tuple[tuple[tuple[int | float, int | float], ...], str]] = []
    expected_nets: set[str] = set()

    operations = payload.get("operations")
    if isinstance(operations, list):
        for op in operations:
            if not isinstance(op, dict):
                continue
            kind = op.get("kind")
            input_obj = op.get("input")
            if not isinstance(input_obj, dict):
                continue
            if kind == "create_component":
                uuid = input_obj.get("uuid")
                library_uuid = input_obj.get("libraryUuid")
                x = _normalize_number(input_obj.get("x"))
                y = _normalize_number(input_obj.get("y"))
                if (
                    isinstance(uuid, str)
                    and uuid
                    and isinstance(library_uuid, str)
                    and library_uuid
                    and x is not None
                    and y is not None
                ):
                    expected_components.append((uuid, library_uuid, x, y))
            elif kind == "create_wire":
                net = input_obj.get("net")
                canonical = _canonical_line(input_obj.get("line"))
                if isinstance(net, str) and net and canonical is not None:
                    expected_wires.append((canonical, net))
                    expected_nets.add(net)

    result_obj = read_schema_result.get("result")
    schema_obj = result_obj.get("schema") if isinstance(result_obj, dict) else None
    if not isinstance(schema_obj, dict):
        return {
            "ok": False,
            "error": "read_schema result does not contain a schema object",
        }

    actual_components_set: set[tuple[str, str, int | float, int | float]] = set()
    actual_wires_set: set[tuple[tuple[tuple[int | float, int | float], ...], str]] = set()
    actual_nets_set: set[str] = set()

    components = schema_obj.get("components")
    if isinstance(components, list):
        for item in components:
            if not isinstance(item, dict):
                continue
            comp_obj = item.get("component") if isinstance(item.get("component"), dict) else {}
            uuid = comp_obj.get("uuid") if isinstance(comp_obj, dict) else None
            library_uuid = comp_obj.get("libraryUuid") if isinstance(comp_obj, dict) else None
            x = _normalize_number(item.get("x"))
            y = _normalize_number(item.get("y"))
            if (
                isinstance(uuid, str)
                and uuid
                and isinstance(library_uuid, str)
                and library_uuid
                and x is not None
                and y is not None
            ):
                actual_components_set.add((uuid, library_uuid, x, y))

    wires = schema_obj.get("wires")
    if isinstance(wires, list):
        for item in wires:
            if not isinstance(item, dict):
                continue
            net = item.get("net")
            canonical = _canonical_line(item.get("line"))
            if isinstance(net, str) and net and canonical is not None:
                actual_wires_set.add((canonical, net))
                actual_nets_set.add(net)

    missing_components = [
        {
            "uuid": uuid,
            "libraryUuid": library_uuid,
            "x": x,
            "y": y,
        }
        for (uuid, library_uuid, x, y) in expected_components
        if (uuid, library_uuid, x, y) not in actual_components_set
    ]

    missing_wires = [
        {"line": [point for xy in canonical for point in xy], "net": net}
        for (canonical, net) in expected_wires
        if (canonical, net) not in actual_wires_set
    ]

    missing_nets = sorted(expected_nets - actual_nets_set)

    return {
        "ok": not missing_components and not missing_wires and not missing_nets,
        "expected": {
            "components": len(expected_components),
            "wires": len(expected_wires),
            "nets": sorted(expected_nets),
        },
        "actual": {
            "components": len(actual_components_set),
            "wires": len(actual_wires_set),
            "nets_count": len(actual_nets_set),
        },
        "missing_components": missing_components,
        "missing_wires": missing_wires,
        "missing_nets": missing_nets,
    }


def _default_audit_dir() -> str:
    return str(Path(".aieda_audit"))


def _write_audit_report(audit_dir: str, report: dict[str, Any]) -> str:
    folder = Path(audit_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"apply_requirements_{stamp}_{int(time.time() * 1000)}.json"
    _write_json_file(str(path), report)
    return str(path)


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
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
        "include_texts": args.include_texts,
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


def cmd_search_component(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"keyword": args.keyword}
    command = BridgeCommand(action="search_component", payload=payload)
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

    meta = _build_meta(args)
    command = BridgeCommand(action="update_schema", payload=payload, meta=meta)
    client = BridgeClient(host=args.host, port=args.port)
    result = client.send_command(command)
    _output(result)
    return 0 if result.get("ok") else 1


def cmd_plan_requirements(args: argparse.Namespace) -> int:
    client = None
    if not args.no_auto_resolve:
        client = BridgeClient(host=args.host, port=args.port)

    try:
        planned = _build_planned_payload(args, client=client)
    except RequirementsError as exc:
        return _error("Unable to build requirements payload", str(exc))

    if args.output_payload_file:
        try:
            _write_json_file(args.output_payload_file, planned.payload)
        except OSError as exc:
            return _error("Unable to write output payload file", str(exc))

    _output(
        {
            "ok": True,
            "summary": planned.summary,
            "resolved_components": planned.resolved_components,
            "payload": planned.payload,
            "output_payload_file": args.output_payload_file,
        }
    )
    return 0


def cmd_apply_requirements(args: argparse.Namespace) -> int:
    client = BridgeClient(host=args.host, port=args.port)

    if not args.dry_run and not args.confirm:
        return _error(
            "apply_requirements requires confirmation",
            "Pass --confirm to execute real changes, or --dry-run for validation only",
        )

    try:
        planned = _build_planned_payload(args, client=client)
    except RequirementsError as exc:
        return _error("Unable to build requirements payload", str(exc))

    if args.output_payload_file:
        try:
            _write_json_file(args.output_payload_file, planned.payload)
        except OSError as exc:
            return _error("Unable to write output payload file", str(exc))

    runtime_result = client.send_command(BridgeCommand(action="get_runtime_status", payload={}))
    if not runtime_result.get("ok"):
        return _error("Runtime precheck failed", runtime_result)

    available_ops = _extract_available_update_operations(runtime_result)
    missing_ops = sorted({"create_component", "create_wire"} - available_ops)
    if missing_ops:
        return _error(
            "Runtime precheck failed: required operations unavailable",
            {
                "missing_operations": missing_ops,
                "available_operations": sorted(available_ops),
                "runtime_result": runtime_result,
            },
        )

    pre_dry_run_result: dict[str, Any] | None = None
    if not args.skip_pre_dry_run:
        dry_run_command = BridgeCommand(
            action="update_schema",
            payload=planned.payload,
            meta=CommandMeta(
                confirm=True,
                dry_run=True,
                continue_on_error=args.continue_on_error,
            ),
        )
        pre_dry_run_result = client.send_command(dry_run_command)
        if not pre_dry_run_result.get("ok"):
            report = {
                "ok": False,
                "mode": "precheck_dry_run",
                "summary": planned.summary,
                "resolved_components": planned.resolved_components,
                "runtime_precheck": runtime_result,
                "pre_dry_run": pre_dry_run_result,
                "bridge_result": None,
                "verification": None,
            }
            if not args.no_audit:
                report["audit_report_file"] = _write_audit_report(args.audit_dir, report)
            _output(report)
            return 1

    apply_meta = _build_meta(args)
    apply_meta.confirm = True if args.dry_run else args.confirm
    command = BridgeCommand(
        action="update_schema",
        payload=planned.payload,
        meta=apply_meta,
    )
    result = client.send_command(command)

    verification: dict[str, Any] | None = None
    if result.get("ok") and not args.skip_verify and not args.dry_run:
        read_result = client.send_command(
            BridgeCommand(
                action="read_schema",
                payload={
                    "include_components": True,
                    "include_wires": True,
                    "include_polygons": False,
                    "include_texts": False,
                    "include_selected": False,
                    "include_document_source": False,
                    "all_schematic_pages": False,
                },
            )
        )
        if read_result.get("ok"):
            verification = _verify_plan_against_schema(planned.payload, read_result)
        else:
            verification = {
                "ok": False,
                "error": "Unable to read schema for post-apply verification",
                "read_schema_result": read_result,
            }

    final_ok = bool(result.get("ok"))
    if verification is not None and not verification.get("ok"):
        final_ok = False

    report = {
        "ok": final_ok,
        "mode": "dry_run" if args.dry_run else "apply",
        "summary": planned.summary,
        "resolved_components": planned.resolved_components,
        "output_payload_file": args.output_payload_file,
        "runtime_precheck": runtime_result,
        "pre_dry_run": pre_dry_run_result,
        "bridge_result": result,
        "verification": verification,
    }
    if not args.no_audit:
        report["audit_report_file"] = _write_audit_report(args.audit_dir, report)

    _output(report)
    return 0 if final_ok else 1


def cmd_export_requirements_template(args: argparse.Namespace) -> int:
    template = {
        "spec_version": "aieda.requirements.v1",
        "components": [
            {
                "ref": "U4",
                "keyword": "ESP32-C6-WROOM-1-N8",
                "candidate_index": 0,
                "x": 600,
                "y": 600,
                "rotation": 0,
                "mirror": False,
                "pin_stubs": [
                    {"net": "GND", "offset": [0, -100], "direction": "up", "length": 10},
                    {"net": "I2C_SCL", "offset": [-110, -10], "direction": "left", "length": 10},
                    {"net": "I2C_SDA", "offset": [-110, 0], "direction": "left", "length": 10},
                ],
            }
        ],
        "nets": [
            {
                "net": "3V3_AON",
                "connections": [
                    {"component": "U4", "offset": [-180, 70], "direction": "left", "length": 10}
                ],
            }
        ],
        "wires": [
            {"line": [100, 100, 140, 100], "net": "EXAMPLE_NET"},
        ],
    }
    try:
        _write_json_file(args.output, template)
    except OSError as exc:
        return _error("Unable to export requirements template", str(exc))

    _output({"ok": True, "output": args.output, "spec_version": "aieda.requirements.v1"})
    return 0


def cmd_verify_operations(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return _error("Unable to read payload file", str(exc))
    except json.JSONDecodeError as exc:
        return _error("Invalid JSON payload file", str(exc))

    if not isinstance(payload, dict):
        return _error("Payload file must contain a JSON object")

    client = BridgeClient(host=args.host, port=args.port)
    read_result = client.send_command(
        BridgeCommand(
            action="read_schema",
            payload={
                "include_components": True,
                "include_wires": True,
                "include_polygons": False,
                "include_texts": False,
                "include_selected": False,
                "include_document_source": False,
                "all_schematic_pages": False,
            },
        )
    )
    if not read_result.get("ok"):
        return _error("Unable to read schema for verification", read_result)

    verification = _verify_plan_against_schema(payload, read_result)
    _output({"ok": bool(verification.get("ok")), "verification": verification})
    return 0 if verification.get("ok") else 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _add_update_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confirm", action="store_true", default=False, help="Confirm write operation"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False, help="Validate only, do not apply"
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Skip failed operations instead of aborting",
    )


def _add_requirements_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--requirements-file",
        required=True,
        help="Path to requirements JSON file",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="Requirements file encoding (default: utf-8-sig)",
    )
    parser.add_argument(
        "--default-stub-length",
        type=float,
        default=10.0,
        help="Default wire stub length for direction-based connections",
    )
    parser.add_argument(
        "--no-auto-resolve",
        action="store_true",
        default=False,
        help="Disable keyword resolution through search_component",
    )
    parser.add_argument(
        "--output-payload-file",
        type=str,
        default=None,
        help="Write generated update_schema payload to a JSON file",
    )


def _add_secure_apply_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skip-pre-dry-run",
        action="store_true",
        default=False,
        help="Skip mandatory preflight dry-run before apply",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        default=False,
        help="Skip post-apply schema verification",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        default=False,
        help="Disable writing audit report file",
    )
    parser.add_argument(
        "--audit-dir",
        type=str,
        default=_default_audit_dir(),
        help="Directory where apply reports are written",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="AI EDA CLI - interact with EasyEDA via the bridge server",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bridge host")
    parser.add_argument("--port", type=int, default=8787, help="Bridge port")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Start the bridge server (foreground)")
    sub.add_parser("status", help="Check plugin connection status")
    sub.add_parser("stop", help="Shut down the bridge server")
    sub.add_parser("get_runtime_status", help="Diagnostic: adapter type & capabilities")

    p_auth = sub.add_parser("check_auth", help="Check EasyEDA auth status via plugin")
    p_auth.add_argument(
        "--include-raw",
        action="store_true",
        default=False,
        help="Include raw adapter probe details",
    )

    p_search = sub.add_parser(
        "search_component", help="Search a component in EasyEDA library"
    )
    p_search.add_argument("keyword", type=str, help="Library search keyword")

    p_read = sub.add_parser("read_schema", help="Read the schematic")
    p_read.add_argument("--include-wires", action="store_true", default=True)
    p_read.add_argument("--include-polygons", action="store_true", default=False)
    p_read.add_argument("--include-texts", action="store_true", default=False)
    p_read.add_argument("--include-selected", action="store_true", default=False)
    p_read.add_argument("--include-document-source", action="store_true", default=False)
    p_read.add_argument("--all-pages", action="store_true", default=False)

    p_list = sub.add_parser("list_components", help="List components")
    p_list.add_argument("--selected-only", action="store_true", default=False)
    p_list.add_argument("--limit", type=int, default=None)
    p_list.add_argument("--fields", type=str, default=None, help="Comma-separated field names")

    p_update = sub.add_parser("update_schema", help="Modify the schematic")
    p_update.add_argument("payload", nargs="?", default=None, help="JSON string with operations")
    p_update.add_argument(
        "--payload-file",
        type=str,
        default=None,
        help="Path to JSON payload file (use '-' for stdin)",
    )
    _add_update_flags(p_update)

    p_plan = sub.add_parser(
        "plan_requirements",
        help="Build update_schema operations from a requirements file",
    )
    _add_requirements_flags(p_plan)

    p_apply = sub.add_parser(
        "apply_requirements",
        help="Build and apply update_schema operations from a requirements file",
    )
    _add_requirements_flags(p_apply)
    _add_update_flags(p_apply)
    _add_secure_apply_flags(p_apply)

    p_template = sub.add_parser(
        "export_requirements_template",
        help="Export a template requirements file (.json)",
    )
    p_template.add_argument(
        "--output",
        required=True,
        help="Path where the template file will be written",
    )

    p_verify = sub.add_parser(
        "verify_operations",
        help="Verify an existing operations payload against current schema",
    )
    p_verify.add_argument(
        "--payload-file",
        required=True,
        help="Path to an update_schema payload JSON file",
    )

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
    "search_component": cmd_search_component,
    "read_schema": cmd_read_schema,
    "list_components": cmd_list_components,
    "update_schema": cmd_update_schema,
    "plan_requirements": cmd_plan_requirements,
    "apply_requirements": cmd_apply_requirements,
    "export_requirements_template": cmd_export_requirements_template,
    "verify_operations": cmd_verify_operations,
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
