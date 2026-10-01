// What the player's audio did lately (its events, and how a start position was reached),
// for About → "Player diagnostics" (PlayerDiagnostics.tsx): playback bugs only seen on a
// phone, like a resumed position Safari on iOS never sought. Kept for the page's life, the
// last lines only.

export interface TraceLine {
  id: number;
  time: string; // hh:mm:ss.mmm
  text: string;
}

const MAX_LINES = 200;
let lines: readonly TraceLine[] = [];
let nextId = 0;
const listeners = new Set<() => void>();

function changed(next: readonly TraceLine[]): void {
  lines = next;
  listeners.forEach((listener) => listener());
}

export function traceAudio(text: string): void {
  const now = new Date();
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${pad(now.getMilliseconds(), 3)}`;
  changed([...lines.slice(-(MAX_LINES - 1)), { id: nextId++, time, text }]);
}

export function clearAudioTrace(): void {
  changed([]);
}

/** For useSyncExternalStore. */
export function subscribeAudioTrace(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function audioTrace(): readonly TraceLine[] {
  return lines;
}
