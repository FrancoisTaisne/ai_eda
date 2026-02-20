# AI EDA

Drive [EasyEDA Pro](https://pro.easyeda.com/) from an AI console.

AI EDA is a bridge that lets an AI assistant (e.g. Claude Code) read and modify electronic schematics in EasyEDA Pro through simple CLI commands. It connects a Python CLI to the EasyEDA Pro desktop app via a local WebSocket bridge.

## Architecture

```
AI Console (Claude Code, terminal…)
        │
        ▼
   cli.py  (one-shot commands, JSON stdout)
        │  HTTP
        ▼
   bridge_server.py  (aiohttp, port 8787)
        │  WebSocket
        ▼
   aieda_js plugin  (runs inside EasyEDA Pro)
        │
        ▼
   EasyEDA Pro APIs
```

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.9+ |
| Node.js | 18+ (build only) |
| EasyEDA Pro | 2.3+ |

## Quick Start

### 1. Install the Python bridge

```bash
cd aieda_python
pip install -r requirements.txt
```

### 2. Build and install the EasyEDA plugin

```bash
cd aieda_js
npm install
npm run build
```

This produces `aieda_js/build/dist/aieda-js_v<version>.eext`.
Install the `.eext` file in EasyEDA Pro via **Extension > Extension Manager > Load from file**.

### 3. Start the bridge server

```bash
python aieda_python/cli.py serve
```

The server starts on `http://127.0.0.1:8787` and generates a one-time auth token in `aieda_python/.bridge_token`.

### 4. Connect the plugin

In EasyEDA Pro, open a schematic and use the plugin menu **AI EDA > Start Bridge**. The plugin reads the auth token and connects via WebSocket.

### 5. Use CLI commands

```bash
# Check connection
python aieda_python/cli.py status

# Read the full schematic
python aieda_python/cli.py read_schema

# List components
python aieda_python/cli.py list_components
python aieda_python/cli.py list_components --selected-only --limit 50

# Search library components
python aieda_python/cli.py search_component "ESP32-C6-WROOM-1-N8"

# Export typed requirements template
python aieda_python/cli.py export_requirements_template --output needs.json

# Modify the schematic (requires --confirm)
python aieda_python/cli.py update_schema '{"operations":[...]}' --confirm

# Dry run (no actual changes)
python aieda_python/cli.py update_schema '{"operations":[...]}' --dry-run

# Build/apply from a requirements file (secure pipeline)
python aieda_python/cli.py plan_requirements --requirements-file needs.json
python aieda_python/cli.py apply_requirements --requirements-file needs.json --confirm
python aieda_python/cli.py verify_operations --payload-file ops.json

# Stop the server
python aieda_python/cli.py stop
```

All commands output JSON to stdout and return exit code 0 on success, 1 on error.

## Supported Actions

| Action | Description | Write |
|---|---|---|
| `get_runtime_status` | Adapter type, capabilities, available APIs | No |
| `check_auth` | EasyEDA user authentication state | No |
| `search_component` | Search EasyEDA library and return candidates | No |
| `read_schema` | Components, wires, polygons, selected items | No |
| `list_components` | Filtered component list with field selection | No |
| `update_schema` | Create, modify or delete components and wires | Yes |

Write actions require explicit confirmation (`--confirm` flag or `meta.confirm = true`).

## Protocol (v1.0.0)

**Command** (Python → Plugin):
```json
{
  "id": "cmd-1234567890-1",
  "type": "command",
  "action": "read_schema",
  "payload": {},
  "meta": { "confirm": false, "dry_run": false },
  "protocol_version": "1.0.0"
}
```

**Result** (Plugin → Python):
```json
{
  "id": "cmd-1234567890-1",
  "type": "result",
  "protocol_version": "1.0.0",
  "ok": true,
  "duration_ms": 42,
  "result": { "adapter": "easyeda", "counts": { "components": 264 } }
}
```

## Project Structure

```
ai_eda/
├── aieda_python/          # Python bridge server + CLI
│   ├── cli.py             # One-shot CLI (serve, status, stop, read_schema…)
│   ├── bridge_server.py   # aiohttp HTTP + WebSocket server
│   ├── client.py          # HTTP client (stdlib only)
│   ├── protocol.py        # Command protocol definitions
│   └── requirements.txt   # aiohttp>=3.9
│
├── aieda_js/              # EasyEDA Pro plugin (JavaScript)
│   ├── src/
│   │   ├── index.js       # Plugin runtime + EasyEDA UI menus
│   │   ├── protocol.js    # Command normalization + result envelopes
│   │   ├── dispatcher.js  # Validation, policy, routing
│   │   ├── handlers.js    # Business logic (5 action handlers)
│   │   ├── adapters.js    # EasyEDA adapter + mock adapter
│   │   └── bridge-client.js  # Reconnectable WebSocket client
│   ├── extension.json     # EasyEDA plugin manifest
│   └── package.json
│
├── package.json           # Root scripts (build, check)
└── LICENSE
```

## License

[MIT](LICENSE)
