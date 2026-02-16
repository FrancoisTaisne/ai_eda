export const PROTOCOL_VERSION = "1.0.0";
export const COMMAND_TYPE = "command";
export const RESULT_TYPE = "result";
export const EVENT_TYPE = "event";

export const ACTIONS = {
  GET_RUNTIME_STATUS: "get_runtime_status",
  READ_SCHEMA: "read_schema",
  LIST_COMPONENTS: "list_components",
  UPDATE_SCHEMA: "update_schema",
  CHECK_AUTH: "check_auth"
};

export const SUPPORTED_ACTIONS = new Set(Object.values(ACTIONS));
export const WRITE_ACTIONS = new Set([ACTIONS.UPDATE_SCHEMA]);

let commandCounter = 0;

function nextCounter() {
  commandCounter = (commandCounter + 1) % 1_000_000;
  return commandCounter;
}

export function createCommandId() {
  return `cmd-${Date.now()}-${nextCounter()}`;
}

export function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizeMeta(raw) {
  const meta = isPlainObject(raw?.meta) ? { ...raw.meta } : {};
  if (typeof raw?.confirm === "boolean" && typeof meta.confirm !== "boolean") {
    meta.confirm = raw.confirm;
  }
  if (typeof raw?.dry_run === "boolean" && typeof meta.dry_run !== "boolean") {
    meta.dry_run = raw.dry_run;
  }
  if (
    typeof raw?.continue_on_error === "boolean" &&
    typeof meta.continue_on_error !== "boolean"
  ) {
    meta.continue_on_error = raw.continue_on_error;
  }
  return meta;
}

export function normalizeIncomingCommand(raw) {
  if (!isPlainObject(raw)) {
    return {
      ok: false,
      error: "Command payload must be an object",
      id: createCommandId()
    };
  }

  const action = raw.action;
  if (typeof action !== "string" || action.length === 0) {
    return {
      ok: false,
      error: "Missing command action",
      id: typeof raw.id === "string" ? raw.id : createCommandId()
    };
  }

  if (!SUPPORTED_ACTIONS.has(action)) {
    return {
      ok: false,
      error: `Unsupported action: ${action}`,
      id: typeof raw.id === "string" ? raw.id : createCommandId()
    };
  }

  const payload = raw.payload === undefined ? {} : raw.payload;
  if (!isPlainObject(payload)) {
    return {
      ok: false,
      error: "Command payload field must be an object",
      id: typeof raw.id === "string" ? raw.id : createCommandId()
    };
  }

  const type = typeof raw.type === "string" ? raw.type : COMMAND_TYPE;
  if (type !== COMMAND_TYPE) {
    return {
      ok: false,
      error: `Unsupported message type: ${type}`,
      id: typeof raw.id === "string" ? raw.id : createCommandId()
    };
  }

  return {
    ok: true,
    command: {
      id: typeof raw.id === "string" ? raw.id : createCommandId(),
      type: COMMAND_TYPE,
      action,
      payload,
      meta: normalizeMeta(raw),
      protocol_version: typeof raw.protocol_version === "string" ? raw.protocol_version : PROTOCOL_VERSION
    }
  };
}

export function isWriteAction(action) {
  return WRITE_ACTIONS.has(action);
}

export function createResultEnvelope(commandId, body) {
  return {
    id: commandId,
    type: RESULT_TYPE,
    protocol_version: PROTOCOL_VERSION,
    ...body
  };
}

export function createEventEnvelope(name, payload = {}) {
  return {
    id: createCommandId(),
    type: EVENT_TYPE,
    protocol_version: PROTOCOL_VERSION,
    event: name,
    payload
  };
}
