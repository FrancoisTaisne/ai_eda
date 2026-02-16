import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createPluginRuntime, DEFAULT_CONFIG, normalizeTokenValue, runSelfTest } from "./index.js";

function parseCliArgs(argv) {
  const output = {};
  for (let index = 0; index < argv.length; index += 1) {
    const rawArg = argv[index];
    if (!rawArg.startsWith("--")) {
      continue;
    }

    const normalized = rawArg.slice(2);
    const separator = normalized.indexOf("=");
    if (separator >= 0) {
      const key = normalized.slice(0, separator);
      const value = normalized.slice(separator + 1);
      output[key] = value;
      continue;
    }

    const nextArg = argv[index + 1];
    if (typeof nextArg === "string" && !nextArg.startsWith("--")) {
      output[normalized] = nextArg;
      index += 1;
      continue;
    }

    output[normalized] = true;
  }
  return output;
}

function readBridgeTokenFromFile() {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const candidates = [
    path.resolve(process.cwd(), "aieda_python", ".bridge_token"),
    path.resolve(process.cwd(), "..", "aieda_python", ".bridge_token"),
    path.resolve(scriptDir, "..", "..", "aieda_python", ".bridge_token")
  ];

  const visited = new Set();
  for (const candidate of candidates) {
    if (visited.has(candidate)) {
      continue;
    }
    visited.add(candidate);
    if (!existsSync(candidate)) {
      continue;
    }

    const token = normalizeTokenValue(readFileSync(candidate, "utf8"));
    if (token) {
      return token;
    }
  }
  return null;
}

async function runCliMode() {
  const args = parseCliArgs(process.argv.slice(2));
  if (args["self-test"]) {
    await runSelfTest();
    return;
  }

  if (args["bridge-dev"]) {
    const cliToken = normalizeTokenValue(args["bridge-token"]);
    const bridgeToken = cliToken ?? readBridgeTokenFromFile();
    const runtime = createPluginRuntime({
      useMockAdapter: true,
      bridgeUrl: typeof args["bridge-url"] === "string" ? args["bridge-url"] : DEFAULT_CONFIG.bridgeUrl,
      bridgeToken
    });
    runtime.startBridge();
    console.log(`Bridge dev mode started on ${runtime.config.bridgeUrl}`);
  }
}

runCliMode().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
