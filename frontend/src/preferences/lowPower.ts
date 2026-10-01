// "Lighter animations" (My account → Player): what animates while playing (the visualizers,
// the lyrics' scroll and karaoke fill) draws fewer frames, for a less powerful computer.
// Per browser, like the volume: the same account may be used on a desktop and a small laptop.

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "sb.low-power";
/** Frames per second of those animations when on (else the display's rate). */
export const LOW_POWER_FPS = 20;

const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

let current = read();

export function lowPower(): boolean {
  return current;
}

export function setLowPower(on: boolean): void {
  current = on;
  try {
    if (on) localStorage.setItem(STORAGE_KEY, "1");
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // private browsing: for this page only
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Changed in another tab of this browser.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    current = read();
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The frame rate animations are limited to: LOW_POWER_FPS, or null (the display's). */
export function useFrameRate(): number | null {
  return useSyncExternalStore(subscribe, lowPower) ? LOW_POWER_FPS : null;
}

export function useLowPower(): boolean {
  return useSyncExternalStore(subscribe, lowPower);
}
