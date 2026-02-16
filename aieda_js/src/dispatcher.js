import {
  createResultEnvelope,
  isWriteAction,
  normalizeIncomingCommand
} from "./protocol.js";

function serializeError(error) {
  if (error instanceof Error) {
    return {
      error: error.message,
      details: {
        name: error.name,
        stack: error.stack ?? null
      }
    };
  }
  return {
    error: String(error),
    details: null
  };
}

function writeIsConfirmed(command) {
  if (command?.meta?.confirm === true) {
    return true;
  }
  if (command?.payload?.confirm === true) {
    return true;
  }
  return false;
}

export function createCommandDispatcher({ handlers, adapter, policy, logger }) {
  return {
    async dispatch(rawCommand) {
      const normalized = normalizeIncomingCommand(rawCommand);
      if (!normalized.ok) {
        return createResultEnvelope(normalized.id, {
          ok: false,
          error: normalized.error
        });
      }

      const { command } = normalized;
      const handler = handlers[command.action];
      if (typeof handler !== "function") {
        return createResultEnvelope(command.id, {
          ok: false,
          error: `No handler registered for action: ${command.action}`
        });
      }

      if (isWriteAction(command.action)) {
        if (policy.allowWriteActions !== true) {
          return createResultEnvelope(command.id, {
            ok: false,
            error: "Write actions are disabled by plugin policy"
          });
        }

        if (policy.requireWriteConfirmation === true && !writeIsConfirmed(command)) {
          return createResultEnvelope(command.id, {
            ok: false,
            error: "Write confirmation required",
            details: {
              hint: "Set payload.confirm=true or meta.confirm=true"
            }
          });
        }
      }

      const startedAt = Date.now();
      try {
        const result = await handler(command.payload, {
          command,
          adapter
        });
        return createResultEnvelope(command.id, {
          ok: true,
          duration_ms: Date.now() - startedAt,
          result
        });
      } catch (error) {
        const serialized = serializeError(error);
        logger.error(`Command failed (${command.action})`, serialized.error);
        return createResultEnvelope(command.id, {
          ok: false,
          duration_ms: Date.now() - startedAt,
          error: serialized.error,
          details: serialized.details
        });
      }
    }
  };
}

