# aieda_python

Python bridge server and CLI to drive EasyEDA Pro through the `aieda_js` plugin.

## Architecture

```text
Claude Code (Bash)  -->  cli.py  -->  bridge_server.py (port 8787)  <--WS-->  aieda_js plugin
```

- `bridge_server.py`: HTTP + WebSocket server on port 8787
- `cli.py`: one-shot CLI commands (stdout JSON)
- `client.py`: HTTP client to talk to bridge_server
- `protocol.py`: command protocol (versioned, with meta fields)
- `requirements_planner.py`: requirements file to `update_schema` operations builder
- `requirements_template_v1.json`: starter file for AI-generated schematic plans
- `REQUIREMENTS_FILE_SPEC.md`: formal file spec for `aieda.requirements.v1`

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Start the bridge server (run in foreground)
python cli.py serve

# Check plugin connection
python cli.py status

# Check EasyEDA authentication state (through plugin)
python cli.py check_auth
python cli.py check_auth --include-raw

# Search parts in EasyEDA library
python cli.py search_component "ESP32-C6-WROOM-1-N8"

# Export a typed requirements template
python cli.py export_requirements_template --output needs.json

# Read the schematic
python cli.py read_schema
python cli.py read_schema --include-selected --all-pages

# List components
python cli.py list_components
python cli.py list_components --selected-only --limit 50

# Modify the schematic directly
python cli.py update_schema '{"operations":[...]}' --confirm
python cli.py update_schema '{"operations":[...]}' --dry-run
python cli.py update_schema --payload-file operations.json --confirm
cat operations.json | python cli.py update_schema --payload-file - --confirm

# Build operations from requirements (preview only)
python cli.py plan_requirements --requirements-file needs.json
python cli.py plan_requirements --requirements-file needs.json --output-payload-file ops.json

# Build + apply requirements (secure pipeline: precheck + dry-run + verify + audit)
python cli.py apply_requirements --requirements-file needs.json --confirm
python cli.py apply_requirements --requirements-file needs.json --confirm --output-payload-file ops.json
python cli.py apply_requirements --requirements-file needs.json --confirm --audit-dir .aieda_audit

# Verify an existing operations payload against current schema
python cli.py verify_operations --payload-file ops.json

# Stop the bridge server
python cli.py stop
```

## Requirements File Format

`plan_requirements` and `apply_requirements` expect a JSON object:

```json
{
  "spec_version": "aieda.requirements.v1",
  "components": [
    {
      "ref": "U4",
      "keyword": "ESP32-C6-WROOM-1-N8",
      "x": 600,
      "y": 600,
      "pin_stubs": [
        { "net": "GND", "offset": [0, -100], "direction": "up", "length": 10 },
        { "net": "I2C_SCL", "offset": [-110, -10], "direction": "left", "length": 10 }
      ]
    }
  ],
  "nets": [
    {
      "net": "3V3_AON",
      "connections": [
        { "component": "U4", "offset": [-180, 70], "direction": "left", "length": 10 }
      ]
    }
  ],
  "wires": [
    { "line": [100, 100, 150, 100], "net": "NET_LABEL" }
  ]
}
```

Notes:
- `spec_version` is versioned and checked when provided (`aieda.requirements.v1`).
- Per component, either provide `uuid` + `libraryUuid`, or provide `keyword` for auto-resolution via `search_component`.
- Net persistence uses `create_wire` with `net` labels (wire stubs), not `create_netflag`.
- Connection anchors can be absolute (`from`, `to`, `line`) or relative to a component (`component` + `offset` or `pin_offset`).
- `direction` values: `left`, `right`, `up`, `down`.
- You can disable auto-resolution with `--no-auto-resolve`.

## Secure Apply Process

`apply_requirements` now runs with defense-in-depth:
1. Runtime precheck (`get_runtime_status`) to ensure `create_component` and `create_wire` exist.
2. Preflight dry-run (`update_schema` with `dry_run=true`) unless `--skip-pre-dry-run`.
3. Real apply (`update_schema` with `--confirm`) or dry-run mode only (`--dry-run`).
4. Post-apply verification by re-reading schema and matching planned components/wires/nets unless `--skip-verify`.
5. Audit report JSON written in `.aieda_audit/` unless `--no-audit`.

## Endpoints (bridge_server.py)

| Method | Path | Description |
|--------|------|-------------|
| POST | /command | Forward a command to the plugin |
| GET | /status | Plugin connection state |
| POST | /shutdown | Graceful server shutdown |
| GET | /ws | WebSocket endpoint for aieda_js |
