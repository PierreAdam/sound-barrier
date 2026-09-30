import { useSyncExternalStore } from "react";

// Whether this tab can be remote controlled (turned on in the queue panel's Remote menu).
// Kept in memory only: off again when the page reloads (a reloaded page may not start
// audio before a click in it, it should not be listed as controllable).

export type RemoteTargetStatus =
  | { kind: "off" }
  | { kind: "connecting" } // asked, or reconnecting
  | { kind: "on"; id: string } // its id as a target (the Remote menu does not list itself)
  | { kind: "conflict"; device: string } // on in another tab, for the same player
  | { kind: "replaced"; device: string }; // another tab took over

let status: RemoteTargetStatus = { kind: "off" };
let takeOver = false; // the next registration takes the player from another tab
const listeners = new Set<() => void>();

function set(next: RemoteTargetStatus): void {
  status = next;
  listeners.forEach((listener) => listener());
}

export function getRemoteTarget(): RemoteTargetStatus {
  return status;
}

/** Wanted on (connecting, on, or asking again after a conflict). */
export function remoteTargetWanted(): boolean {
  return status.kind === "connecting" || status.kind === "on";
}

export function enableRemoteTarget(options: { takeOver?: boolean } = {}): void {
  takeOver = options.takeOver ?? false;
  set({ kind: "connecting" });
}

export function disableRemoteTarget(): void {
  takeOver = false;
  set({ kind: "off" });
}

/** For the bridge: whether to take over, once (a reconnection does not). */
export function consumeTakeOver(): boolean {
  const value = takeOver;
  takeOver = false;
  return value;
}

/** For the bridge: what the server said. */
export function setRemoteTarget(next: RemoteTargetStatus): void {
  set(next);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useRemoteTarget(): RemoteTargetStatus {
  return useSyncExternalStore(subscribe, getRemoteTarget);
}
