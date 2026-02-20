# aieda_js

JavaScript plugin bridge for EasyEDA Pro.

## Purpose
- receive commands from `aieda_python`
- validate and route commands
- execute schematic read/write actions through EasyEDA APIs
- return structured result envelopes

## Architecture
- Protocol: `src/protocol.js`
- Dispatcher: `src/dispatcher.js`
- Handlers: `src/handlers.js`
- EasyEDA adapter and mock adapter: `src/adapters.js`
- Transport bridge (WebSocket): `src/bridge-client.js`
- Runtime entry: `src/index.js`

Detailed implementation schema: `IMPLEMENTATION_SCHEMA.md`

## Actions (v1)
- `get_runtime_status`
- `check_auth`
- `search_component`
- `read_schema`
- `list_components`
- `update_schema`

## Write guard
`update_schema` is blocked unless one of these is true:
- `meta.confirm = true`
- `payload.confirm = true`

`update_schema` execution flags:
- dry run: `meta.dry_run = true` or `payload.dry_run = true`
- continue on error: `meta.continue_on_error = true` or `payload.continue_on_error = true`

## Run checks
```bash
node src/cli-dev.js --self-test
```

## Build plugin package
From repository root:

```bash
npm run build
```

Or from `aieda_js`:

```bash
npm run build
```

Output package:
- `aieda_js/build/dist/aieda-js_v<version>.eext`
- unpacked content: `aieda_js/build/dist/package`

## Dev bridge mode
```bash
node src/cli-dev.js --bridge-dev --bridge-url=ws://127.0.0.1:8787/ws
```

With authenticated bridge server:

```bash
node src/cli-dev.js --bridge-dev --bridge-url=ws://127.0.0.1:8787/ws --bridge-token <TOKEN>
```

If `--bridge-token` is not provided in Node dev mode, `aieda_js` tries to read:
- `aieda_python/.bridge_token` (from current working directory)
- `../aieda_python/.bridge_token`

In plugin runtime, token can be provided through:
- `globalThis.AIEDA_PLUGIN_CONFIG.bridgeToken`
- URL query param: `bridgeToken`, `bridge_token`, or `token`
- `localStorage` key: `aieda.bridgeToken`, `aieda_bridge_token`, or `bridgeToken`

Adapter selection notes:
- Real EasyEDA adapter is used when runtime minimum APIs are available.
- If EasyEDA is missing, fallback to mock is controlled by `mockFallbackWhenNoEda`.
- If EasyEDA exists but required APIs are missing, fallback is controlled by `mockFallbackWhenEdaUnavailable`.

## Legacy compatibility
`handleBridgeCommand({ action, payload })` is still supported for local direct calls.
