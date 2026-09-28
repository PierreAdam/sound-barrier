// Pure play-queue logic (no audio), unit tested in queue.test.ts.

export type RepeatMode = "off" | "all" | "one";

export const REPEAT_MODES: RepeatMode[] = ["off", "all", "one"];

export function nextRepeatMode(mode: RepeatMode): RepeatMode {
  return REPEAT_MODES[(REPEAT_MODES.indexOf(mode) + 1) % REPEAT_MODES.length] ?? "off";
}

/** Random order of `entries`, with `first` (the current track) kept in first position. */
export function shuffleEntries<T>(entries: readonly T[], first?: T, random: () => number = Math.random): T[] {
  const rest = entries.filter((entry) => entry !== first);
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [rest[i], rest[j]] = [rest[j] as T, rest[i] as T];
  }
  return first === undefined ? rest : [first, ...rest];
}

/**
 * Index to play after `index`, or null to stop.
 * `automatic` is true when the track ended by itself (repeat "one" then replays it).
 */
export function nextIndex(index: number, length: number, repeat: RepeatMode, automatic: boolean): number | null {
  if (length === 0) return null;
  if (automatic && repeat === "one") return index;
  if (index + 1 < length) return index + 1;
  return repeat === "off" ? null : 0;
}

export function previousIndex(index: number, length: number, repeat: RepeatMode): number | null {
  if (index > 0) return index - 1;
  return repeat !== "off" && length > 0 ? length - 1 : null;
}
