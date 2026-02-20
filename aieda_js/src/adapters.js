import { isPlainObject } from "./protocol.js";

class EasyEdaApiError extends Error {
  constructor(message) {
    super(message);
    this.name = "EasyEdaApiError";
  }
}

function requireString(value, label) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new EasyEdaApiError(`${label} must be a non-empty string`);
  }
}

function requireArray(value, label) {
  if (!Array.isArray(value)) {
    throw new EasyEdaApiError(`${label} must be an array`);
  }
}

const RUNTIME_MINIMUM_REQUIREMENTS = [
  ["sch_PrimitiveComponent", "getAll"],
  ["sch_PrimitiveWire", "getAll"]
];

const READ_OPTIONAL_REQUIREMENTS = [
  ["sch_PrimitivePolygon", "getAll"],
  ["sch_SelectControl", "getAllSelectedPrimitives"],
  ["sys_FileManager", "getDocumentSource"],
  ["sch_PrimitiveComponent", "get"],
  ["sch_PrimitiveComponent", "getAllPrimitiveId"]
];

const UPDATE_OPERATION_REQUIREMENTS = {
  create_component: [["sch_PrimitiveComponent", "create"]],
  modify_component: [["sch_PrimitiveComponent", "modify"]],
  delete_component: [["sch_PrimitiveComponent", "delete"]],
  create_wire: [["sch_PrimitiveWire", "create"]],
  modify_wire: [["sch_PrimitiveWire", "modify"]],
  delete_wire: [["sch_PrimitiveWire", "delete"]],
  create_netflag: [["sch_PrimitiveComponent", "createNetFlag"]],
  create_netport: [["sch_PrimitiveComponent", "createNetPort"]],
  search_component: [["lib_Device", "search"]]
};

function hasMethod(eda, namespace, method) {
  return typeof eda?.[namespace]?.[method] === "function";
}

function requirementName(namespace, method) {
  return `${namespace}.${method}`;
}

function evaluateRequirements(eda, requirements) {
  const methods = requirements.map(([namespace, method]) => ({
    name: requirementName(namespace, method),
    available: hasMethod(eda, namespace, method)
  }));
  const missing = methods.filter((item) => !item.available).map((item) => item.name);

  return {
    methods,
    missing,
    available: missing.length === 0
  };
}

function listAvailableUpdateOperations(eda) {
  const available = [];
  const missing = {};
  for (const [kind, requirements] of Object.entries(UPDATE_OPERATION_REQUIREMENTS)) {
    const status = evaluateRequirements(eda, requirements);
    if (status.available) {
      available.push(kind);
    } else {
      missing[kind] = status.missing;
    }
  }
  return { available, missing };
}

function buildCapabilities(eda) {
  const environmentDetected = isPlainObject(eda);
  const runtimeMinimum = evaluateRequirements(eda, RUNTIME_MINIMUM_REQUIREMENTS);
  const readOptional = evaluateRequirements(eda, READ_OPTIONAL_REQUIREMENTS);
  const updates = listAvailableUpdateOperations(eda);

  return {
    environment_detected: environmentDetected,
    runtime_minimum: runtimeMinimum,
    read_optional: readOptional,
    update_operations: updates,
    runtime_available: environmentDetected && runtimeMinimum.available
  };
}

function cloneValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function getMethod(eda, namespace, method) {
  const group = eda?.[namespace];
  const fn = group?.[method];
  if (typeof fn !== "function") {
    throw new EasyEdaApiError(`EasyEDA API unavailable: ${namespace}.${method}`);
  }
  return fn.bind(group);
}

function getOptionalMethod(eda, namespace, method) {
  const group = eda?.[namespace];
  const fn = group?.[method];
  if (typeof fn !== "function") {
    return null;
  }
  return fn.bind(group);
}

function serializeError(error) {
  return error instanceof Error ? error.message : String(error);
}

function safePreview(value, max = 500) {
  try {
    const text = JSON.stringify(value);
    if (typeof text === "string") {
      return text.length > max ? `${text.slice(0, max)}...` : text;
    }
  } catch (_) {
    // ignore serialization preview errors
  }
  return "<non-serializable>";
}

function asStringOrNull(value) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumberOrFallback(value, fallback) {
  return typeof value === "number" ? value : fallback;
}

function asBooleanOrFallback(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeCreateComponentResult(result, input) {
  const fallback = {
    primitiveId: null,
    designator: null,
    uuid: input.uuid,
    libraryUuid: input.libraryUuid,
    x: input.x,
    y: input.y,
    subPartName: input.subPartName,
    rotation: input.rotation,
    mirror: input.mirror
  };

  if (!isPlainObject(result)) {
    return fallback;
  }

  return {
    primitiveId: asStringOrNull(result.primitiveId),
    designator: asStringOrNull(result.designator),
    uuid: asStringOrNull(result?.component?.uuid) ?? input.uuid,
    libraryUuid: asStringOrNull(result?.component?.libraryUuid) ?? input.libraryUuid,
    x: asNumberOrFallback(result.x, input.x),
    y: asNumberOrFallback(result.y, input.y),
    subPartName: asStringOrNull(result.subPartName) ?? input.subPartName,
    rotation: asNumberOrFallback(result.rotation, input.rotation),
    mirror: asBooleanOrFallback(result.mirror, input.mirror)
  };
}

async function tryOptionalCalls(eda, candidates) {
  let firstError = null;

  for (const [namespace, method] of candidates) {
    const fn = getOptionalMethod(eda, namespace, method);
    if (!fn) {
      continue;
    }

    try {
      return {
        source: `${namespace}.${method}`,
        value: await fn()
      };
    } catch (error) {
      if (!firstError) {
        firstError = {
          source: `${namespace}.${method}`,
          error: serializeError(error)
        };
      }
    }
  }

  return firstError;
}

export function createEasyEdaAdapter(eda) {
  const capabilities = buildCapabilities(eda);

  function ensureRuntimeAvailable(action) {
    if (capabilities.runtime_available) {
      return;
    }
    const detail = capabilities.runtime_minimum.missing.join(", ");
    throw new EasyEdaApiError(
      `EasyEDA runtime unavailable for ${action}: missing required APIs (${detail || "unknown"})`
    );
  }

  function assertUpdateOperationSupported(kind) {
    const requirements = UPDATE_OPERATION_REQUIREMENTS[kind];
    if (!requirements) {
      return;
    }

    const status = evaluateRequirements(eda, requirements);
    if (!status.available) {
      throw new EasyEdaApiError(
        `EasyEDA API unavailable for ${kind}: ${status.missing.join(", ")}`
      );
    }
  }

  return {
    type: "easyeda",
    isAvailable() {
      return capabilities.runtime_available;
    },

    getCapabilities() {
      return cloneValue(capabilities);
    },

    async getRuntimeStatus() {
      return {
        adapter: "easyeda",
        ...cloneValue(capabilities)
      };
    },

    async getAllComponents({ cmdKey = null, allSchematicPages = false } = {}) {
      ensureRuntimeAvailable("getAllComponents");
      const fn = getMethod(eda, "sch_PrimitiveComponent", "getAll");
      const components = await fn(cmdKey, allSchematicPages);

      // getAll returns primitiveId in "$1I<n>" format but modify/delete/get
      // expect the "<prefix><n>" format returned by getAllPrimitiveId.
      // Build a mapping from the numeric suffix to the canonical ID.
      const idsFn = getOptionalMethod(eda, "sch_PrimitiveComponent", "getAllPrimitiveId");
      if (idsFn && Array.isArray(components)) {
        try {
          const canonicalIds = await idsFn(cmdKey, allSchematicPages);
          if (Array.isArray(canonicalIds)) {
            const canonicalByNum = {};
            for (const cid of canonicalIds) {
              const m = typeof cid === "string" ? cid.match(/(\d+)$/) : null;
              if (m) canonicalByNum[m[1]] = cid;
            }
            for (const comp of components) {
              if (typeof comp.primitiveId === "string") {
                const cm = comp.primitiveId.match(/(\d+)$/);
                if (cm && canonicalByNum[cm[1]]) {
                  comp.primitiveId = canonicalByNum[cm[1]];
                }
              }
            }

            // Resolve canonical IDs for components that have no primitiveId in getAll()
            // (e.g. netflags). After the suffix-matching pass above, any canonical ID
            // not yet assigned to a component is a candidate for an unmapped component.
            const usedIds = new Set(
              components
                .map((c) => c.primitiveId)
                .filter((id) => typeof id === "string" && /^e\d+$/.test(id))
            );
            const unusedIds = canonicalIds.filter(
              (cid) => typeof cid === "string" && !usedIds.has(cid)
            );
            const unmapped = components.filter(
              (c) => !/^e\d+$/.test(String(c.primitiveId ?? ""))
            );
            if (unusedIds.length > 0 && unmapped.length > 0) {
              const getFn = getOptionalMethod(eda, "sch_PrimitiveComponent", "get");
              if (getFn) {
                for (const cid of unusedIds) {
                  try {
                    const info = await getFn(cid);
                    if (!info || typeof info !== "object") continue;
                    const match = unmapped.find(
                      (c) =>
                        !/^e\d+$/.test(String(c.primitiveId ?? "")) &&
                        c.x === info.x &&
                        c.y === info.y
                    );
                    if (match) {
                      match.primitiveId = cid;
                    }
                  } catch (_) { /* ignore */ }
                }
              }
            }
          }
        } catch (_) {
          // If getAllPrimitiveId fails, keep original IDs
        }
      }

      return components;
    },

    async getAllWires({ net = null } = {}) {
      ensureRuntimeAvailable("getAllWires");
      const fn = getMethod(eda, "sch_PrimitiveWire", "getAll");
      return fn(net);
    },

    async getAllPolygons() {
      ensureRuntimeAvailable("getAllPolygons");
      const fn = getMethod(eda, "sch_PrimitivePolygon", "getAll");
      return fn();
    },

    async getSelectedPrimitives() {
      ensureRuntimeAvailable("getSelectedPrimitives");
      const fn = getMethod(eda, "sch_SelectControl", "getAllSelectedPrimitives");
      return fn();
    },

    async getAllTexts() {
      ensureRuntimeAvailable("getAllTexts");
      const fn = getOptionalMethod(eda, "sch_PrimitiveText", "getAll");
      if (!fn) return [];
      const texts = await fn();
      // Normalize primitiveId like components
      const idsFn = getOptionalMethod(eda, "sch_PrimitiveText", "getAllPrimitiveId");
      if (idsFn && Array.isArray(texts)) {
        try {
          const canonicalIds = await idsFn();
          if (Array.isArray(canonicalIds)) {
            const canonicalByNum = {};
            for (const cid of canonicalIds) {
              const m = typeof cid === "string" ? cid.match(/(\d+)$/) : null;
              if (m) canonicalByNum[m[1]] = cid;
            }
            for (const text of texts) {
              if (typeof text.primitiveId === "string") {
                const cm = text.primitiveId.match(/(\d+)$/);
                if (cm && canonicalByNum[cm[1]]) {
                  text.primitiveId = canonicalByNum[cm[1]];
                }
              }
            }
          }
        } catch (_) {}
      }
      return texts;
    },

    async modifyText(input) {
      ensureRuntimeAvailable("modifyText");
      requireString(input.primitiveId, "primitiveId");
      if (!isPlainObject(input.property)) {
        throw new EasyEdaApiError("property must be an object");
      }
      const fn = getMethod(eda, "sch_PrimitiveText", "modify");
      return fn(input.primitiveId, input.property);
    },

    async getDocumentSource() {
      ensureRuntimeAvailable("getDocumentSource");
      const fn = getMethod(eda, "sys_FileManager", "getDocumentSource");
      return fn();
    },

    async getAuthStatus() {
      const userProbe = await tryOptionalCalls(eda, [
        ["sys_User", "getUserInfo"],
        ["sys_User", "getCurrentUser"],
        ["sys_User", "getLoginUser"],
        ["sys_Account", "getUserInfo"],
        ["sys_Account", "getCurrentUser"]
      ]);

      const loginProbe = await tryOptionalCalls(eda, [
        ["sys_User", "isLogin"],
        ["sys_User", "isLoggedIn"],
        ["sys_Account", "isLogin"],
        ["sys_Account", "isLoggedIn"]
      ]);

      const rawUser = userProbe && Object.prototype.hasOwnProperty.call(userProbe, "value") ? userProbe.value : null;
      const rawLogin =
        loginProbe && Object.prototype.hasOwnProperty.call(loginProbe, "value") ? loginProbe.value : null;

      let authenticated = null;
      if (typeof rawLogin === "boolean") {
        authenticated = rawLogin;
      } else if (isPlainObject(rawUser) && Object.keys(rawUser).length > 0) {
        authenticated = true;
      }

      return {
        authenticated,
        status:
          authenticated === true ? "authenticated" : authenticated === false ? "anonymous" : "unknown",
        source: loginProbe?.source ?? userProbe?.source ?? null,
        user: rawUser,
        raw: {
          user_probe: userProbe ?? null,
          login_probe: loginProbe ?? null
        }
      };
    },

    async createComponent(input) {
      ensureRuntimeAvailable("createComponent");
      assertUpdateOperationSupported("create_component");
      const { uuid, libraryUuid, x, y } = input;
      requireString(uuid, "uuid");
      requireString(libraryUuid, "libraryUuid");
      if (typeof x !== "number" || typeof y !== "number") {
        throw new EasyEdaApiError("x and y must be numbers");
      }

      const subPartName = typeof input.subPartName === "string" ? input.subPartName : "";
      const rotation = typeof input.rotation === "number" ? input.rotation : 0;
      const mirror = typeof input.mirror === "boolean" ? input.mirror : false;
      const createFn = getMethod(eda, "sch_PrimitiveComponent", "create");
      const attempts = [
        {
          name: "create(component,x,y,subPart,rotation,mirror,addIntoBom,addIntoPcb)",
          call: () => createFn({ uuid, libraryUuid }, x, y, subPartName, rotation, mirror, true, true)
        },
        {
          name: "create(component,x,y,subPart,rotation,mirror)",
          call: () => createFn({ uuid, libraryUuid }, x, y, subPartName, rotation, mirror)
        },
        {
          name: "create({component,x,y,subPartName,rotation,mirror,addIntoBom,addIntoPcb})",
          call: () =>
            createFn({
              component: { uuid, libraryUuid },
              x,
              y,
              subPartName,
              rotation,
              mirror,
              addIntoBom: true,
              addIntoPcb: true
            })
        },
        {
          name: "create(uuid,libraryUuid,x,y,subPart,rotation,mirror,addIntoBom,addIntoPcb)",
          call: () => createFn(uuid, libraryUuid, x, y, subPartName, rotation, mirror, true, true)
        }
      ];

      console.log("[aieda] createComponent attempting eda.sch_PrimitiveComponent.create");
      console.log("[aieda] component:", JSON.stringify({ uuid, libraryUuid }));
      console.log("[aieda] position:", x, y, "subPartName:", subPartName, "rotation:", rotation, "mirror:", mirror);

      const errors = [];
      for (const attempt of attempts) {
        try {
          const result = await attempt.call();
          const normalized = normalizeCreateComponentResult(result, {
            uuid,
            libraryUuid,
            x,
            y,
            subPartName,
            rotation,
            mirror
          });
          console.log("[aieda] createComponent OK via", attempt.name, safePreview(normalized));
          return normalized;
        } catch (err) {
          const message = serializeError(err);
          errors.push(`${attempt.name}: ${message}`);
          console.warn("[aieda] createComponent attempt failed:", attempt.name, message);
        }
      }

      throw new EasyEdaApiError(
        `createComponent failed. Ensure uuid/libraryUuid come from search_component. Attempts: ${errors.join(
          " | "
        )}`
      );
    },

    async modifyComponent(input) {
      ensureRuntimeAvailable("modifyComponent");
      assertUpdateOperationSupported("modify_component");
      requireString(input.primitiveId, "primitiveId");
      if (!isPlainObject(input.property)) {
        throw new EasyEdaApiError("property must be an object");
      }
      const fn = getMethod(eda, "sch_PrimitiveComponent", "modify");
      return fn(input.primitiveId, input.property);
    },

    async deleteComponent(input) {
      ensureRuntimeAvailable("deleteComponent");
      assertUpdateOperationSupported("delete_component");
      if (!input?.primitiveIds) {
        throw new EasyEdaApiError("primitiveIds is required");
      }
      const fn = getMethod(eda, "sch_PrimitiveComponent", "delete");
      return fn(input.primitiveIds);
    },

    async createWire(input) {
      ensureRuntimeAvailable("createWire");
      assertUpdateOperationSupported("create_wire");
      requireArray(input.line, "line");
      if (input.line.length < 4 || input.line.length % 2 !== 0) {
        throw new EasyEdaApiError("line must contain at least 4 coordinates and have even length");
      }
      const fn = getMethod(eda, "sch_PrimitiveWire", "create");
      return fn(
        input.line,
        input.net ?? null,
        input.color ?? "#000000",
        typeof input.lineWidth === "number" ? input.lineWidth : 1,
        typeof input.lineType === "number" ? input.lineType : 0
      );
    },

    async modifyWire(input) {
      ensureRuntimeAvailable("modifyWire");
      assertUpdateOperationSupported("modify_wire");
      requireString(input.primitiveId, "primitiveId");
      if (!isPlainObject(input.property)) {
        throw new EasyEdaApiError("property must be an object");
      }
      const fn = getMethod(eda, "sch_PrimitiveWire", "modify");
      return fn(input.primitiveId, input.property);
    },

    async deleteWire(input) {
      ensureRuntimeAvailable("deleteWire");
      assertUpdateOperationSupported("delete_wire");
      if (!input?.primitiveIds) {
        throw new EasyEdaApiError("primitiveIds is required");
      }
      const fn = getMethod(eda, "sch_PrimitiveWire", "delete");
      return fn(input.primitiveIds);
    },

    async createNetFlag(input) {
      ensureRuntimeAvailable("createNetFlag");
      assertUpdateOperationSupported("create_netflag");
      requireString(input.identification, "identification");
      requireString(input.net, "net");
      if (typeof input.x !== "number" || typeof input.y !== "number") {
        throw new EasyEdaApiError("x and y must be numbers");
      }
      const rotation = typeof input.rotation === "number" ? input.rotation : 0;
      const mirror = typeof input.mirror === "boolean" ? input.mirror : false;

      console.log("[aieda] createNetFlag:", JSON.stringify({ identification: input.identification, net: input.net, x: input.x, y: input.y }));
      const fn = getMethod(eda, "sch_PrimitiveComponent", "createNetFlag");
      return fn(input.identification, input.net, input.x, input.y, rotation, mirror);
    },

    async createNetPort(input) {
      ensureRuntimeAvailable("createNetPort");
      assertUpdateOperationSupported("create_netport");
      requireString(input.direction, "direction");
      requireString(input.net, "net");
      if (typeof input.x !== "number" || typeof input.y !== "number") {
        throw new EasyEdaApiError("x and y must be numbers");
      }
      const rotation = typeof input.rotation === "number" ? input.rotation : 0;
      const mirror = typeof input.mirror === "boolean" ? input.mirror : false;

      console.log("[aieda] createNetPort:", JSON.stringify({ direction: input.direction, net: input.net, x: input.x, y: input.y }));
      const fn = getMethod(eda, "sch_PrimitiveComponent", "createNetPort");
      return fn(input.direction, input.net, input.x, input.y, rotation, mirror);
    },

    async searchComponent(input) {
      ensureRuntimeAvailable("searchComponent");
      requireString(input.keyword, "keyword");
      console.log("[aieda] searchComponent:", input.keyword);
      const fn = getMethod(eda, "lib_Device", "search");
      return fn(input.keyword);
    }
  };
}

function createIdGenerator(prefix) {
  let cursor = 0;
  return () => {
    cursor += 1;
    return `${prefix}-${cursor}`;
  };
}

export function createMockAdapter() {
  const nextComponentId = createIdGenerator("cmp");
  const nextWireId = createIdGenerator("wire");

  const components = [
    { primitiveId: nextComponentId(), designator: "R1", x: 100, y: 100, uuid: "mock-r" },
    { primitiveId: nextComponentId(), designator: "C1", x: 180, y: 100, uuid: "mock-c" }
  ];
  const wires = [
    { primitiveId: nextWireId(), line: [100, 100, 180, 100], net: "NET1", color: "#000000", lineWidth: 1, lineType: 0 }
  ];
  const polygons = [];

  function getById(collection, primitiveId) {
    return collection.find((item) => item.primitiveId === primitiveId);
  }

  return {
    type: "mock",
    isAvailable() {
      return true;
    },

    getCapabilities() {
      return {
        environment_detected: false,
        runtime_minimum: {
          methods: [],
          missing: [],
          available: true
        },
        read_optional: {
          methods: [],
          missing: [],
          available: true
        },
        update_operations: {
          available: [
            "search_component",
            "create_component",
            "modify_component",
            "delete_component",
            "create_wire",
            "modify_wire",
            "delete_wire"
          ],
          missing: {}
        },
        runtime_available: true
      };
    },

    async getRuntimeStatus() {
      return {
        adapter: "mock",
        ...this.getCapabilities()
      };
    },

    async getAllComponents() {
      return [...components];
    },

    async getAllWires() {
      return [...wires];
    },

    async getAllPolygons() {
      return [...polygons];
    },

    async getSelectedPrimitives() {
      return [];
    },

    async getDocumentSource() {
      return "MOCK_DOCUMENT_SOURCE";
    },

    async getAuthStatus() {
      return {
        authenticated: true,
        status: "authenticated",
        source: "mock",
        user: {
          id: "mock-user",
          name: "Mock User"
        },
        raw: null
      };
    },

    async searchComponent(input) {
      requireString(input.keyword, "keyword");
      const keyword = input.keyword.toLowerCase();
      if (keyword.includes("esp32")) {
        return [
          {
            uuid: "193bb41f53b74e4b8632181a7f3b059e",
            libraryUuid: "0819f05c4eef4c71ace90d822a990e87",
            subPartName: "ESP32-C6-WROOM-1-N8.1",
            name: "ESP32-C6-WROOM-1-N8"
          }
        ];
      }
      return [
        {
          uuid: "mock-component-uuid",
          libraryUuid: "mock-library-uuid",
          subPartName: "MOCK_PART.1",
          name: input.keyword
        }
      ];
    },

    async createComponent(input) {
      const created = {
        primitiveId: nextComponentId(),
        designator: input.designator ?? null,
        x: input.x,
        y: input.y,
        uuid: input.uuid,
        libraryUuid: input.libraryUuid
      };
      components.push(created);
      return created;
    },

    async modifyComponent(input) {
      const existing = getById(components, input.primitiveId);
      if (!existing) {
        throw new EasyEdaApiError(`Component not found: ${input.primitiveId}`);
      }
      Object.assign(existing, input.property);
      return existing;
    },

    async deleteComponent(input) {
      const ids = Array.isArray(input.primitiveIds) ? input.primitiveIds : [input.primitiveIds];
      const before = components.length;
      for (const id of ids) {
        const index = components.findIndex((item) => item.primitiveId === id);
        if (index >= 0) {
          components.splice(index, 1);
        }
      }
      return { deleted: before - components.length };
    },

    async createWire(input) {
      const created = {
        primitiveId: nextWireId(),
        line: [...input.line],
        net: input.net ?? null,
        color: input.color ?? "#000000",
        lineWidth: typeof input.lineWidth === "number" ? input.lineWidth : 1,
        lineType: typeof input.lineType === "number" ? input.lineType : 0
      };
      wires.push(created);
      return created;
    },

    async modifyWire(input) {
      const existing = getById(wires, input.primitiveId);
      if (!existing) {
        throw new EasyEdaApiError(`Wire not found: ${input.primitiveId}`);
      }
      Object.assign(existing, input.property);
      return existing;
    },

    async deleteWire(input) {
      const ids = Array.isArray(input.primitiveIds) ? input.primitiveIds : [input.primitiveIds];
      const before = wires.length;
      for (const id of ids) {
        const index = wires.findIndex((item) => item.primitiveId === id);
        if (index >= 0) {
          wires.splice(index, 1);
        }
      }
      return { deleted: before - wires.length };
    }
  };
}

export { EasyEdaApiError };
