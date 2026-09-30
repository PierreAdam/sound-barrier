import { useEffect, useSyncExternalStore } from "react";

import type { RemoteCommand, RemoteQueue, RemoteTargetInfo } from "./protocol";
import { RemoteSocket } from "./socket";

/** A target, with when its last state arrived (its position advances from then). */
export interface LinkTarget extends RemoteTargetInfo {
  at: number;
}

export interface LinkView {
  connected: boolean;
  targets: LinkTarget[] | null; // null: not listed yet (connecting)
  /** The watched target's queue (see `watch`), once it came. */
  queue: RemoteQueue | null;
  error: string | null;
}

/**
 * This tab as a remote: one WebSocket, open while something needs it (the Remote menu
 * listing the players, or remote mode mirroring one of them). Lists the user's targets
 * with their states, and gets the queue of the one watched.
 */
export class RemoteLink {
  private socket: RemoteSocket | null = null;
  private users = 0;
  private watching: string | null = null;
  private listeners = new Set<() => void>();
  private view: LinkView = { connected: false, targets: null, queue: null, error: null };

  /** Keeps the connection open until the returned function is called. */
  acquire(): () => void {
    this.users += 1;
    if (!this.socket) this.open();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.users -= 1;
      if (this.users === 0) this.close();
    };
  }

  /** Gets this target's queue (and its changes); null: none. */
  watch(target: string | null): void {
    if (target === this.watching) return;
    this.watching = target;
    this.set({ queue: null });
    this.socket?.send({ type: "watch", target });
  }

  send(target: string, command: RemoteCommand): void {
    this.set({ error: null });
    this.socket?.send({ type: "command", target, command });
  }

  getView = (): LinkView => this.view;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(changes: Partial<LinkView>): void {
    this.view = { ...this.view, ...changes };
    this.listeners.forEach((listener) => listener());
  }

  private open(): void {
    const socket = new RemoteSocket({
      open: () => {
        socket.send({ type: "remote" });
        if (this.watching) socket.send({ type: "watch", target: this.watching });
      },
      message: (message) => {
        const now = Date.now();
        switch (message.type) {
          case "targets":
            this.set({ targets: message.targets.map((target) => ({ ...target, at: now })) });
            break;
          case "state":
            this.set({
              targets:
                this.view.targets?.map((target) =>
                  target.id === message.target ? { ...target, state: message.state, at: now } : target,
                ) ?? null,
            });
            break;
          case "queue":
            if (message.target === this.watching) this.set({ queue: message.queue });
            break;
          case "error":
            this.set({ error: message.message });
            break;
        }
      },
      connected: (connected) => this.set({ connected }),
    });
    this.socket = socket;
    socket.start();
  }

  private close(): void {
    this.socket?.stop();
    this.socket = null;
    this.set({ connected: false, targets: null, queue: null });
  }
}

export const remoteLink = new RemoteLink();

/** The user's targets (the connection stays open while a component uses this). */
export function useRemoteLink(): LinkView {
  useEffect(() => remoteLink.acquire(), []);
  return useSyncExternalStore(remoteLink.subscribe, remoteLink.getView);
}
