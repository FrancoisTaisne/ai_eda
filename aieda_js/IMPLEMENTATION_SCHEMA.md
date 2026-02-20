# aieda_js - Implementation Schema

## Goal
`aieda_js` is the EasyEDA-side bridge that receives commands from the console AI and applies them to the current schematic.

## Scope v1
- Report runtime capability status
- Check EasyEDA authentication state
- Search component library
- Read schematic data
- List components
- Apply controlled write operations
- Expose a stable command protocol over WebSocket

## Runtime Architecture
```text
+---------------------+        WebSocket         +----------------------+
| aieda_python        | <----------------------> | aieda_js plugin      |
| (console AI client) |                          | (EasyEDA runtime)    |
+---------------------+                          +----------+-----------+
                                                           |
                                                           v
                                                  +--------------------+
                                                  | Command Dispatcher |
                                                  | - protocol checks  |
                                                  | - write guard      |
                                                  | - handler routing  |
                                                  +----------+---------+
                                                             |
                                                             v
                                                  +--------------------+
                                                  | EasyEDA Adapter    |
                                                  | sch_* / sys_* APIs |
                                                  +--------------------+
```

## Internal Modules
```text
src/
  protocol.js       -> message normalization + envelope creation
  dispatcher.js     -> validation + policy + handler execution
  handlers.js       -> get_runtime_status / check_auth / search_component / read_schema / list_components / update_schema
  adapters.js       -> EasyEDA adapter + mock adapter
  bridge-client.js  -> reconnecting WebSocket transport
  index.js          -> runtime assembly + activate/deactivate + self-test
```

## Command Contract
Incoming command:
```json
{
  "id": "cmd-1",
  "type": "command",
  "action": "read_schema",
  "payload": {},
  "meta": {
    "confirm": false,
    "dry_run": false,
    "continue_on_error": false
  }
}
```

Result envelope:
```json
{
  "id": "cmd-1",
  "type": "result",
  "protocol_version": "1.0.0",
  "ok": true,
  "duration_ms": 12,
  "result": {}
}
```

## Write Safety Policy
- `update_schema` is a write action.
- By default, write commands require confirmation:
  - `meta.confirm = true` or `payload.confirm = true`
- Policy is configurable from runtime config.
- `continue_on_error` can be provided in `meta` or `payload`.

## Supported update_schema Operations (v1)
- `create_component`
- `modify_component`
- `delete_component`
- `create_wire`
- `modify_wire`
- `delete_wire`

Each operation is executed sequentially, with optional:
- `dry_run`
- `continue_on_error`

## Runtime Status Command
- `get_runtime_status` returns:
  - selected adapter (`easyeda` or `mock`)
  - whether runtime minimum APIs are available
  - list of missing APIs when runtime is incomplete
  - update operations currently supported by detected EasyEDA API

## Activation Model
- In EasyEDA plugin context, call `activate()` to start bridge.
- In local dev mode, run `node src/index.js --self-test` (mock adapter).
- Optional bridge simulation mode: `node src/index.js --bridge-dev`.
- Authenticated bridge mode: provide `bridgeToken` config or `--bridge-token`, URL becomes `...?token=<TOKEN>`.
- Runtime token fallbacks: URL query (`bridgeToken` / `bridge_token` / `token`) and `localStorage`.
