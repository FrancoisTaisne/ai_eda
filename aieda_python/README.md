# aieda_python

Python bridge server and CLI to drive EasyEDA Pro through the aieda_js plugin.

## Architecture

```
Claude Code (Bash)  -->  cli.py  -->  bridge_server.py (port 8787)  <--WS-->  aieda_js plugin
```

- `bridge_server.py` : HTTP + WebSocket server on port 8787
- `cli.py` : one-shot CLI commands (stdout JSON)
- `client.py` : HTTP client to talk to bridge_server
- `protocol.py` : command protocol (versioned, with meta fields)

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Start the bridge server (run in background)
python cli.py serve

# Check if the plugin is connected
python cli.py status

# Check EasyEDA authentication state (through plugin)
python cli.py check_auth
python cli.py check_auth --include-raw

# Read the schematic
python cli.py read_schema
python cli.py read_schema --include-selected --all-pages

# List components
python cli.py list_components
python cli.py list_components --selected-only --limit 50

# Modify the schematic
python cli.py update_schema '{"operations":[...]}' --confirm
python cli.py update_schema '{"operations":[...]}' --dry-run
python cli.py update_schema --payload-file operations.json --confirm
cat operations.json | python cli.py update_schema --payload-file - --confirm

# Stop the bridge server
python cli.py stop
```

## Endpoints (bridge_server.py)

| Method | Path | Description |
|--------|------|-------------|
| POST | /command | Forward a command to the plugin |
| GET | /status | Plugin connection state |
| POST | /shutdown | Graceful server shutdown |
| GET | /ws | WebSocket endpoint for aieda_js |
