// Remote control: the messages exchanged over /api/remote/ws (see the backend's
// services/remote.py). A "target" is a tab the user made controllable; a "remote" drives
// it from another tab, computer or phone signed in to the same account.

import type { RepeatMode } from "../player/queue";

/** What a remote shows of a target's player (sent by the target when it changes). */
export interface RemoteState {
  track: {
    id: string;
    title: string;
    artist: string | null;
    album: string | null;
    coverArt: string | null;
    chapter: string | null; // the chapter playing (audiobooks)
  } | null;
  playing: boolean;
  position: number; // seconds, when the state was sent (remotes advance it while playing)
  rate: number; // how fast it advances (the speed of audiobooks and podcasts, else 1)
  duration: number;
  volume: number; // 0..1
  muted: boolean;
  shuffle: boolean;
  repeat: RepeatMode;
  crossfade: boolean;
  spoken: boolean; // an audiobook or a podcast: skips, speed, pause at end (no shuffle...)
  chapters: boolean; // previous / next move by chapter
  pauseAtEnd: boolean;
  pauseAtEndLabel: string;
  speed: number;
  hasPrevious: boolean;
  hasNext: boolean;
  index: number; // in the queue, -1: none
  count: number; // tracks in the queue
}

/** What a remote asks (the player bar's controls). */
export type RemoteCommand =
  | { name: "toggle" | "play" | "pause" | "previous" | "next" }
  | { name: "mute" | "shuffle" | "repeat" | "crossfade" | "pauseAtEnd" }
  | { name: "seek"; position: number }
  | { name: "skip"; seconds: number }
  | { name: "volume"; value: number }
  | { name: "speed"; value: number };

export interface RemoteTargetInfo {
  id: string;
  playerName: string; // "Shared", or the player the user created (e.g. "PC")
  device: string; // e.g. "Vivaldi on Windows"
  state: RemoteState | null;
}

export type ServerMessage =
  | { type: "target-on"; id: string }
  | { type: "conflict"; device: string }
  | { type: "replaced"; device: string }
  | { type: "command"; command: RemoteCommand }
  | { type: "targets"; targets: RemoteTargetInfo[] }
  | { type: "state"; target: string; state: RemoteState }
  | { type: "error"; message: string };

export type ClientMessage =
  | { type: "target"; player: string | null; playerName: string; device: string; takeOver: boolean }
  | { type: "state"; state: RemoteState }
  | { type: "stop" }
  | { type: "remote" }
  | { type: "command"; target: string; command: RemoteCommand };

/** This browser, as a remote lists it: e.g. "Vivaldi on Windows". */
export function deviceName(): string {
  const data = (navigator as Navigator & { userAgentData?: { brands: { brand: string }[]; platform: string } })
    .userAgentData;
  const brands = data?.brands.map((b) => b.brand).filter((b) => !/not.?a.?brand/i.test(b)) ?? [];
  // The browser's own brand (e.g. "Vivaldi", "Microsoft Edge") rather than the engine's.
  const brand = brands.find((b) => !/^(Chromium|Google Chrome)$/.test(b)) ?? brands[0];
  if (brand && data?.platform) return `${brand} on ${data.platform}`;
  // Firefox and Safari have no userAgentData: from the user agent string (in this order:
  // Edge's and Chrome's also name Safari, Android's names Linux).
  const ua = navigator.userAgent;
  const browser = BROWSERS.find(([pattern]) => pattern.test(ua))?.[1] ?? "A browser";
  const system = SYSTEMS.find(([pattern]) => pattern.test(ua))?.[1];
  return system ? `${browser} on ${system}` : browser;
}

const BROWSERS: [RegExp, string][] = [
  [/Firefox\//, "Firefox"],
  [/Edg\//, "Edge"],
  [/Chrome\//, "Chrome"],
  [/Safari\//, "Safari"],
];

const SYSTEMS: [RegExp, string][] = [
  [/iPhone|iPad/, "iOS"],
  [/Android/, "Android"],
  [/Mac OS X/, "macOS"],
  [/Windows/, "Windows"],
  [/Linux/, "Linux"],
];
