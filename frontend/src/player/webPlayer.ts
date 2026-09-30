import { useSyncExternalStore } from "react";

// The player this browser is assigned to, per account (another account signing in on
// the same browser has its own). Nothing kept: the Shared player.
const KEY_PREFIX = "sound-barrier.web-player.";

const listeners = new Set<() => void>();
const memory = new Map<string, string>(); // when local storage cannot be used

function read(username: string): string | null {
  try {
    return localStorage.getItem(KEY_PREFIX + username);
  } catch {
    return memory.get(username) ?? null;
  }
}

/** The id of the player this browser plays for the user, null for the Shared one. */
export function getWebPlayerId(username: string): string | null {
  return read(username);
}

/** Assigns this browser to one of the user's players (null: back to Shared). */
export function setWebPlayerId(username: string, playerId: string | null): void {
  if (read(username) === playerId) return;
  try {
    if (playerId) localStorage.setItem(KEY_PREFIX + username, playerId);
    else localStorage.removeItem(KEY_PREFIX + username);
  } catch {
    if (playerId) memory.set(username, playerId);
    else memory.delete(username);
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The player this browser plays (re-renders when it is switched, in this tab). */
export function useWebPlayerId(username: string): string | null {
  return useSyncExternalStore(subscribe, () => read(username));
}
