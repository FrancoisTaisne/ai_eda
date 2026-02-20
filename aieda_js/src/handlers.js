import { ACTIONS } from "./protocol.js";

function asObject(value, fallback = {}) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : fallback;
}

function pickFields(input, fields) {
  if (!Array.isArray(fields) || fields.length === 0) {
    return input;
  }
  const output = {};
  for (const field of fields) {
    if (typeof field === "string" && Object.prototype.hasOwnProperty.call(input, field)) {
      output[field] = input[field];
    }
  }
  return output;
}

async function handleGetRuntimeStatus(_payload, context) {
  const status =
    typeof context.adapter.getRuntimeStatus === "function"
      ? await context.adapter.getRuntimeStatus()
      : null;
  const capabilities =
    typeof context.adapter.getCapabilities === "function" ? context.adapter.getCapabilities() : null;

  return {
    adapter: context.adapter.type,
    available: typeof context.adapter.isAvailable === "function" ? context.adapter.isAvailable() : null,
    status,
    capabilities
  };
}

async function handleCheckAuth(payload, context) {
  const params = asObject(payload);
  if (typeof context.adapter.getAuthStatus !== "function") {
    return {
      adapter: context.adapter.type,
      authenticated: null,
      status: "unsupported"
    };
  }

  const auth = await context.adapter.getAuthStatus();
  if (params.include_raw === true) {
    return {
      adapter: context.adapter.type,
      ...auth
    };
  }

  if (!auth || typeof auth !== "object" || Array.isArray(auth)) {
    return {
      adapter: context.adapter.type,
      authenticated: null,
      status: "unknown"
    };
  }

  const { raw, ...withoutRaw } = auth;
  return {
    adapter: context.adapter.type,
    ...withoutRaw
  };
}

async function handleSearchComponent(payload, context) {
  const params = asObject(payload);
  const keyword = typeof params.keyword === "string" ? params.keyword.trim() : "";
  if (!keyword) {
    throw new Error("search_component requires a non-empty keyword");
  }
  if (typeof context.adapter.searchComponent !== "function") {
    throw new Error("search_component is not supported by this adapter");
  }

  const matches = await context.adapter.searchComponent({ keyword });
  return {
    adapter: context.adapter.type,
    keyword,
    matches
  };
}

async function handleReadSchema(payload, context) {
  const params = asObject(payload);
  const includeComponents = params.include_components !== false;
  const includeWires = params.include_wires !== false;
  const includePolygons = params.include_polygons === true;
  const includeSelected = params.include_selected === true;
  const includeDocumentSource = params.include_document_source === true;
  const includeTexts = params.include_texts === true;

  const schema = {};
  if (includeComponents) {
    schema.components = await context.adapter.getAllComponents({
      cmdKey: params.cmdKey ?? null,
      allSchematicPages: params.all_schematic_pages === true
    });
  }
  if (includeWires) {
    schema.wires = await context.adapter.getAllWires({
      net: params.net ?? null
    });
  }
  if (includePolygons) {
    schema.polygons = await context.adapter.getAllPolygons();
  }
  if (includeTexts) {
    schema.texts = await context.adapter.getAllTexts();
  }
  if (includeSelected) {
    schema.selected = await context.adapter.getSelectedPrimitives();
  }
  if (includeDocumentSource) {
    schema.document_source = await context.adapter.getDocumentSource();
  }

  return {
    adapter: context.adapter.type,
    counts: {
      components: Array.isArray(schema.components) ? schema.components.length : 0,
      wires: Array.isArray(schema.wires) ? schema.wires.length : 0,
      polygons: Array.isArray(schema.polygons) ? schema.polygons.length : 0,
      texts: Array.isArray(schema.texts) ? schema.texts.length : 0,
      selected: Array.isArray(schema.selected) ? schema.selected.length : 0
    },
    schema
  };
}

async function handleListComponents(payload, context) {
  const params = asObject(payload);
  const allComponents = await context.adapter.getAllComponents({
    cmdKey: params.cmdKey ?? null,
    allSchematicPages: params.all_schematic_pages === true
  });

  let filtered = allComponents;
  if (params.selected_only === true) {
    const selected = await context.adapter.getSelectedPrimitives();
    const selectedIds = new Set(
      selected
        .map((item) => item?.primitiveId ?? item?.id ?? null)
        .filter((item) => typeof item === "string" && item.length > 0)
    );
    filtered = allComponents.filter((component) => selectedIds.has(component?.primitiveId ?? component?.id ?? ""));
  }

  const limit = typeof params.limit === "number" && params.limit > 0 ? Math.floor(params.limit) : 200;
  const fields = Array.isArray(params.fields) ? params.fields : null;
  const truncated = filtered.slice(0, limit).map((component) => pickFields(component, fields));

  return {
    adapter: context.adapter.type,
    count: filtered.length,
    returned: truncated.length,
    limited: filtered.length > truncated.length,
    components: truncated
  };
}

function getOperationKind(operation) {
  if (!operation || typeof operation !== "object") {
    return "";
  }
  if (typeof operation.kind === "string" && operation.kind.length > 0) {
    return operation.kind;
  }
  if (typeof operation.type === "string" && operation.type.length > 0) {
    return operation.type;
  }
  if (typeof operation.action === "string" && operation.action.length > 0) {
    return operation.action;
  }
  return "";
}

async function executeSchemaOperation(operation, context) {
  const kind = getOperationKind(operation);

  switch (kind) {
    case "create_component":
      return context.adapter.createComponent(asObject(operation.input));
    case "modify_component":
      return context.adapter.modifyComponent(asObject(operation.input));
    case "delete_component":
      return context.adapter.deleteComponent(asObject(operation.input));
    case "create_wire":
      return context.adapter.createWire(asObject(operation.input));
    case "modify_wire":
      return context.adapter.modifyWire(asObject(operation.input));
    case "delete_wire":
      return context.adapter.deleteWire(asObject(operation.input));
    case "modify_text":
      return context.adapter.modifyText(asObject(operation.input));
    case "create_netflag":
      return context.adapter.createNetFlag(asObject(operation.input));
    case "create_netport":
      return context.adapter.createNetPort(asObject(operation.input));
    case "search_component":
      return context.adapter.searchComponent(asObject(operation.input));
    default:
      throw new Error(`Unsupported schema operation: ${kind || "<empty>"}`);
  }
}

async function handleUpdateSchema(payload, context) {
  const params = asObject(payload);
  if (!Array.isArray(params.operations) || params.operations.length === 0) {
    throw new Error("update_schema requires a non-empty operations array");
  }

  const dryRun = params.dry_run === true || context.command.meta?.dry_run === true;
  const continueOnError =
    params.continue_on_error === true || context.command.meta?.continue_on_error === true;

  const results = [];
  for (let index = 0; index < params.operations.length; index += 1) {
    const operation = params.operations[index];
    const kind = getOperationKind(operation);
    const item = { index, kind };

    if (dryRun) {
      item.ok = true;
      item.result = "dry_run";
      results.push(item);
      continue;
    }

    try {
      item.result = await executeSchemaOperation(operation, context);
      item.ok = true;
      results.push(item);
    } catch (error) {
      item.ok = false;
      item.error = error instanceof Error ? error.message : String(error);
      results.push(item);
      if (!continueOnError) {
        throw new Error(`operations[${index}] failed: ${item.error}`);
      }
    }
  }

  const applied = results.filter((item) => item.ok).length;
  const failed = results.filter((item) => !item.ok).length;
  return {
    adapter: context.adapter.type,
    dry_run: dryRun,
    requested: params.operations.length,
    applied,
    failed,
    results
  };
}

export function createCommandHandlers() {
  return {
    [ACTIONS.GET_RUNTIME_STATUS]: handleGetRuntimeStatus,
    [ACTIONS.CHECK_AUTH]: handleCheckAuth,
    [ACTIONS.SEARCH_COMPONENT]: handleSearchComponent,
    [ACTIONS.READ_SCHEMA]: handleReadSchema,
    [ACTIONS.LIST_COMPONENTS]: handleListComponents,
    [ACTIONS.UPDATE_SCHEMA]: handleUpdateSchema
  };
}
