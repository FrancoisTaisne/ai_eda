import { createMockAdapter, createEasyEdaAdapter } from "./adapters.js";
import { WebSocketBridgeClient } from "./bridge-client.js";
import { createCommandDispatcher } from "./dispatcher.js";
import { createCommandHandlers } from "./handlers.js";

const DEFAULT_CONFIG = {
  bridgeUrl: "ws://127.0.0.1:8787/ws",
  bridgeToken: null,
  reconnectDelayMs: 2000,
  requireWriteConfirmation: true,
  allowWriteActions: true,
  useMockAdapter: false,
  mockFallbackWhenNoEda: true,
  mockFallbackWhenEdaUnavailable: false
};

let singletonRuntime = null;

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function createLogger() {
  return {
    info: (...args) => console.log("[aieda_js]", ...args),
    warn: (...args) => console.warn("[aieda_js]", ...args),
    error: (...args) => console.error("[aieda_js]", ...args)
  };
}

function getEda() {
  try {
    if (typeof eda !== "undefined") return eda;
  } catch {
    // not available
  }
  return null;
}

function showInformationMessage(message, title = "AI EDA Bridge") {
  const edaRef = getEda();
  const dialog = edaRef?.sys_Dialog;
  if (dialog && typeof dialog.showInformationMessage === "function") {
    dialog.showInformationMessage(String(message), title);
    return;
  }
  console.log(`[aieda_js][${title}] ${message}`);
}

function readGlobalConfig() {
  const cfg = globalThis.AIEDA_PLUGIN_CONFIG;
  return isPlainObject(cfg) ? cfg : {};
}

function normalizeTokenValue(value) {
  if (typeof value !== "string") {
    return null;
  }
  const token = value.trim();
  return token.length > 0 ? token : null;
}

function readBridgeTokenFromLocation() {
  try {
    const search = globalThis?.location?.search;
    if (typeof search !== "string" || search.length === 0) {
      return null;
    }
    const params = new URLSearchParams(search);
    return (
      normalizeTokenValue(params.get("bridgeToken")) ??
      normalizeTokenValue(params.get("bridge_token")) ??
      normalizeTokenValue(params.get("token"))
    );
  } catch {
    return null;
  }
}

function readBridgeTokenFromStorage() {
  try {
    const storage = globalThis?.localStorage;
    if (!storage || typeof storage.getItem !== "function") {
      return null;
    }
    return (
      normalizeTokenValue(storage.getItem("aieda.bridgeToken")) ??
      normalizeTokenValue(storage.getItem("aieda_bridge_token")) ??
      normalizeTokenValue(storage.getItem("bridgeToken"))
    );
  } catch {
    return null;
  }
}

function resolveBridgeToken(config) {
  return (
    normalizeTokenValue(config?.bridgeToken) ??
    readBridgeTokenFromLocation() ??
    readBridgeTokenFromStorage()
  );
}

function buildBridgeUrl(baseUrl, bridgeToken) {
  const token = normalizeTokenValue(bridgeToken);
  if (!token) {
    return baseUrl;
  }

  try {
    const parsed = new URL(baseUrl);
    parsed.searchParams.set("token", token);
    return parsed.toString();
  } catch {
    const separator = baseUrl.includes("?") ? "&" : "?";
    return `${baseUrl}${separator}token=${encodeURIComponent(token)}`;
  }
}

function mergeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    ...readGlobalConfig(),
    ...(isPlainObject(overrides) ? overrides : {})
  };
}

function createAdapter(config, logger) {
  if (config.useMockAdapter) {
    logger.warn("Using mock adapter (forced by config)");
    return createMockAdapter();
  }

  const edaAdapter = createEasyEdaAdapter(getEda());
  const capabilities =
    typeof edaAdapter.getCapabilities === "function" ? edaAdapter.getCapabilities() : null;

  if (edaAdapter.isAvailable()) {
    logger.info("Using EasyEDA adapter");
    return edaAdapter;
  }

  const environmentDetected = capabilities?.environment_detected === true;
  if (environmentDetected) {
    logger.warn(
      "EasyEDA runtime detected but required APIs are missing",
      capabilities?.runtime_minimum?.missing ?? []
    );
    if (config.mockFallbackWhenEdaUnavailable === true) {
      logger.warn("Using mock adapter fallback because mockFallbackWhenEdaUnavailable=true");
      return createMockAdapter();
    }
    return edaAdapter;
  }

  if (config.mockFallbackWhenNoEda === true) {
    logger.warn("EasyEDA runtime not detected, using mock adapter fallback");
    return createMockAdapter();
  }

  return edaAdapter;
}

export function createPluginRuntime(overrides = {}) {
  const logger = createLogger();
  const mergedConfig = mergeConfig(overrides);
  const bridgeToken = resolveBridgeToken(mergedConfig);
  const config = {
    ...mergedConfig,
    bridgeToken,
    bridgeUrl: buildBridgeUrl(mergedConfig.bridgeUrl, bridgeToken)
  };
  const adapter = createAdapter(config, logger);
  const handlers = createCommandHandlers();

  const dispatcher = createCommandDispatcher({
    handlers,
    adapter,
    policy: {
      allowWriteActions: config.allowWriteActions === true,
      requireWriteConfirmation: config.requireWriteConfirmation !== false
    },
    logger
  });

  let bridge = null;

  return {
    config,
    adapterType: adapter.type,
    async dispatchCommand(rawCommand) {
      return dispatcher.dispatch(rawCommand);
    },
    startBridge() {
      if (bridge) {
        return;
      }
      bridge = new WebSocketBridgeClient({
        url: config.bridgeUrl,
        dispatcher,
        logger,
        reconnectDelayMs: config.reconnectDelayMs
      });
      bridge.start();
    },
    stopBridge() {
      if (!bridge) {
        return;
      }
      bridge.stop();
      bridge = null;
    }
  };
}

function getSingletonRuntime() {
  if (!singletonRuntime) {
    singletonRuntime = createPluginRuntime();
  }
  return singletonRuntime;
}

export function activate() {
  const runtime = getSingletonRuntime();
  runtime.startBridge();
}

export function deactivate() {
  if (!singletonRuntime) {
    return;
  }
  singletonRuntime.stopBridge();
}

export function about() {
  showInformationMessage(
    "AI EDA bridge plugin. Connects EasyEDA Pro to aieda_python over WebSocket.",
    "About"
  );
}

export function startBridge() {
  activate();
  const runtime = getSingletonRuntime();
  showInformationMessage(`Bridge started: ${runtime.config.bridgeUrl}`);
}

export function stopBridge() {
  deactivate();
  showInformationMessage("Bridge stopped");
}

export async function showBridgeStatus() {
  const runtime = getSingletonRuntime();
  const status = await runtime.dispatchCommand({
    action: "get_runtime_status",
    payload: {}
  });

  showInformationMessage(
    JSON.stringify(
      {
        bridge_url: runtime.config.bridgeUrl,
        adapter: runtime.adapterType,
        ok: status.ok,
        runtime: status.result?.status ?? null
      },
      null,
      2
    ),
    "Bridge status"
  );
  return status;
}

export async function handleBridgeCommand(command) {
  const runtime = getSingletonRuntime();
  const response = await runtime.dispatchCommand(command);

  const legacyMode =
    command &&
    typeof command === "object" &&
    !Array.isArray(command) &&
    typeof command.action === "string" &&
    (command.type === undefined || command.type === null);

  if (!legacyMode) {
    return response;
  }

  if (response.ok) {
    return { ok: true, result: response.result };
  }
  return {
    ok: false,
    error: response.error,
    details: response.details ?? null
  };
}

async function runSelfTest() {
  const runtime = createPluginRuntime({
    useMockAdapter: true,
    requireWriteConfirmation: false
  });

  const statusResp = await runtime.dispatchCommand({
    action: "get_runtime_status",
    payload: {}
  });
  console.log("SELF_TEST get_runtime_status");
  console.log(JSON.stringify(statusResp, null, 2));

  const authResp = await runtime.dispatchCommand({
    action: "check_auth",
    payload: {}
  });
  console.log("SELF_TEST check_auth");
  console.log(JSON.stringify(authResp, null, 2));

  const searchResp = await runtime.dispatchCommand({
    action: "search_component",
    payload: { keyword: "esp32" }
  });
  console.log("SELF_TEST search_component");
  console.log(JSON.stringify(searchResp, null, 2));

  const readResp = await runtime.dispatchCommand({
    action: "read_schema",
    payload: { include_document_source: true }
  });
  console.log("SELF_TEST read_schema");
  console.log(JSON.stringify(readResp, null, 2));

  const writeResp = await runtime.dispatchCommand({
    action: "update_schema",
    payload: {
      operations: [
        {
          kind: "create_component",
          input: {
            uuid: "mock-u1",
            libraryUuid: "mock-lib",
            x: 220,
            y: 120
          }
        }
      ]
    },
    meta: { confirm: true }
  });
  console.log("SELF_TEST update_schema");
  console.log(JSON.stringify(writeResp, null, 2));

  const listResp = await runtime.dispatchCommand({
    action: "list_components",
    payload: { limit: 20 }
  });
  console.log("SELF_TEST list_components");
  console.log(JSON.stringify(listResp, null, 2));
}
export { runSelfTest, normalizeTokenValue, DEFAULT_CONFIG };
