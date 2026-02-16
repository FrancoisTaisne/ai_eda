import {
  createCommandId,
  createEventEnvelope,
  createResultEnvelope,
  PROTOCOL_VERSION
} from "./protocol.js";

function getWebSocketClass() {
  if (typeof globalThis?.WebSocket === "function") return globalThis.WebSocket;
  try { if (typeof WebSocket === "function") return WebSocket; } catch { /* not available */ }
  return null;
}

function webSocketIsSupported() {
  return getWebSocketClass() !== null;
}

function safeJsonParse(raw) {
  try {
    return { ok: true, value: JSON.parse(raw) };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

export class WebSocketBridgeClient {
  constructor({ url, dispatcher, logger, reconnectDelayMs = 2000 }) {
    this.url = url;
    this.dispatcher = dispatcher;
    this.logger = logger;
    this.reconnectDelayMs = reconnectDelayMs;
    this.ws = null;
    this.shouldRun = false;
    this.reconnectTimer = null;
  }

  start() {
    this.shouldRun = true;
    this.connect();
  }

  stop() {
    this.shouldRun = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  connect() {
    if (!this.shouldRun) {
      return;
    }

    if (!webSocketIsSupported()) {
      this.logger.warn("WebSocket is not available in this runtime. Bridge disabled.");
      return;
    }

    const WS = getWebSocketClass();
    try {
      this.ws = new WS(this.url);
    } catch (error) {
      this.logger.error("WebSocket init failed", error);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.logger.info(`Bridge connected: ${this.url}`);
      this.send(
        createEventEnvelope("bridge_connected", {
          role: "easyeda_plugin",
          name: "aieda_js",
          protocol_version: PROTOCOL_VERSION,
          timestamp: new Date().toISOString()
        })
      );
    };

    this.ws.onmessage = async (event) => {
      const text = typeof event.data === "string" ? event.data : "";
      const parsed = safeJsonParse(text);
      if (!parsed.ok) {
        this.send(
          createResultEnvelope(createCommandId(), {
            ok: false,
            error: "Invalid JSON message",
            details: parsed.error
          })
        );
        return;
      }

      const message = parsed.value;
      if (message?.type === "ping") {
        this.send({
          id: typeof message.id === "string" ? message.id : createCommandId(),
          type: "pong",
          protocol_version: PROTOCOL_VERSION,
          timestamp: new Date().toISOString()
        });
        return;
      }

      const response = await this.dispatcher.dispatch(message);
      this.send(response);
    };

    this.ws.onerror = (error) => {
      this.logger.error("WebSocket bridge error", error);
    };

    this.ws.onclose = () => {
      this.logger.warn("Bridge disconnected");
      this.ws = null;
      this.scheduleReconnect();
    };
  }

  scheduleReconnect() {
    if (!this.shouldRun || this.reconnectTimer) {
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelayMs);
  }

  send(payload) {
    if (!this.ws || this.ws.readyState !== 1) {
      return false;
    }
    try {
      this.ws.send(JSON.stringify(payload));
      return true;
    } catch (error) {
      this.logger.error("WebSocket send failed", error);
      return false;
    }
  }
}

