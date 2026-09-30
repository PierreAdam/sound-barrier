import type { ClientMessage, ServerMessage } from "./protocol";

const MAX_RETRY_MS = 30_000;

interface Handlers {
  /** Connected (again): say who this connection is. */
  open(): void;
  message(message: ServerMessage): void;
  connected?(connected: boolean): void;
}

/**
 * The remote control's WebSocket (same origin, signed in by the session cookie).
 * Reconnects on its own (1 s, 2 s, 4 s... up to 30 s; at once when the page becomes
 * visible again: a phone waking up).
 */
export class RemoteSocket {
  private socket: WebSocket | null = null;
  private retries = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;

  constructor(private readonly handlers: Handlers) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    document.addEventListener("visibilitychange", this.onVisible);
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    document.removeEventListener("visibilitychange", this.onVisible);
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  send(message: ClientMessage): void {
    if (this.connected) this.socket?.send(JSON.stringify(message));
  }

  private connect(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/api/remote/ws`);
    this.socket = socket;
    socket.onopen = () => {
      this.retries = 0;
      this.handlers.connected?.(true);
      this.handlers.open();
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        this.handlers.message(JSON.parse(event.data) as ServerMessage);
      } catch {
        // not JSON: ignored
      }
    };
    socket.onclose = () => {
      if (this.socket !== socket) return; // replaced, or stopped
      this.socket = null;
      this.handlers.connected?.(false);
      if (this.stopped) return;
      const delay = Math.min(MAX_RETRY_MS, 1000 * 2 ** this.retries);
      this.retries += 1;
      this.timer = setTimeout(() => this.connect(), delay);
    };
  }

  private readonly onVisible = () => {
    if (document.visibilityState === "visible" && !this.stopped && !this.socket) this.connect();
  };
}
