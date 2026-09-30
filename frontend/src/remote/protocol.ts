// Remote control: the messages exchanged over /api/remote/ws (see the backend's
// services/remote.py). A "target" is a player that can be controlled: a tab the user made
// controllable, or a server player. A "remote" is a tab in remote mode: its player bar
// and queue panel mirror the target, and what is played or queued in it goes there.

import type { PlayerSnapshot, Track } from "../player/engine";

/**
 * A target's player, as a remote mirrors it: its snapshot without the queue (sent apart,
 * `RemoteQueue`, only when it changes and only to the remotes watching this target).
 */
export interface RemoteState extends Omit<PlayerSnapshot, "queue" | "keys"> {
  /** How fast the position advances (the speed of audiobooks and podcasts, else 1). */
  rate: number;
  /** The queue this state goes with (`RemoteQueue.revision`). */
  queueRevision: number;
  /** The current entry's key: remotes find it in their copy of the queue (which may have
   * been changed there already, e.g. a drag and drop, before the target's answer). */
  currentKey: number | null;
}

export interface RemoteQueue {
  revision: number;
  keys: number[]; // of the entries, stable while queued: commands name entries by key
  tracks: Track[]; // play order
}

/** What a remote asks. Entries of the queue are named by key, never by position. */
export type RemoteCommand =
  | { name: "toggle" | "play" | "pause" | "previous" | "next" }
  | { name: "mute" | "shuffle" | "repeat" | "crossfade" | "clear" | "undo" }
  | { name: "pauseAtEnd"; value?: boolean } // no value: toggle
  | { name: "seek"; position: number }
  | { name: "skip"; seconds: number }
  | { name: "volume" | "speed" | "crossfadeSeconds"; value: number }
  | { name: "playQueue"; tracks: Track[]; index: number; startAt?: number }
  | { name: "add" | "playNext"; tracks: Track[] }
  | { name: "playAt"; key: number }
  | { name: "remove"; keys: number[] }
  | { name: "move"; key: number; before: number | null }; // null: at the end

// "screen": this tab's own TV page (cast/tv), driven without the server's relay.
export type TargetKind = "browser" | "server" | "screen";

export interface RemoteTargetInfo {
  id: string;
  playerName: string; // "Shared", or the player the user created (e.g. "PC")
  device: string; // e.g. "Vivaldi on Windows"
  kind: TargetKind;
  state: RemoteState | null;
}

export type ServerMessage =
  | { type: "target-on"; id: string }
  | { type: "conflict"; device: string }
  | { type: "replaced"; device: string }
  | { type: "command"; command: RemoteCommand }
  | { type: "targets"; targets: RemoteTargetInfo[] }
  | { type: "state"; target: string; state: RemoteState }
  | { type: "queue"; target: string; queue: RemoteQueue }
  | { type: "error"; message: string };

export type ClientMessage =
  | { type: "target"; player: string | null; playerName: string; device: string; takeOver: boolean }
  | { type: "state"; state: RemoteState }
  | { type: "queue"; queue: RemoteQueue }
  | { type: "stop" }
  | { type: "remote" }
  | { type: "watch"; target: string | null }
  | { type: "command"; target: string; command: RemoteCommand };

const text = (value: unknown): string | undefined => (typeof value === "string" ? value.slice(0, 500) : undefined);
const number = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/**
 * Tracks sent by a remote (the user's own, but still from the network): only the known
 * fields, of the right types. What cannot be a track is left out.
 */
export function tracksFrom(value: unknown): Track[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown): Track[] => {
    if (typeof item !== "object" || item === null) return [];
    const raw = item as Record<string, unknown>;
    const id = text(raw.id);
    const title = text(raw.title);
    if (!id || title === undefined) return [];
    const chapters = Array.isArray(raw.chapters)
      ? raw.chapters.flatMap((c: unknown) => {
          const chapter = (typeof c === "object" && c !== null ? c : {}) as Record<string, unknown>;
          const start = number(chapter.start);
          const name = text(chapter.title);
          return start === undefined || name === undefined ? [] : [{ start, title: name }];
        })
      : undefined;
    const spokenKind = raw.spokenKind === "podcasts" || raw.spokenKind === "audiobooks" ? raw.spokenKind : undefined;
    return [
      {
        id,
        title,
        artist: text(raw.artist),
        album: text(raw.album),
        albumId: text(raw.albumId),
        artistId: text(raw.artistId),
        coverArt: text(raw.coverArt),
        durationSeconds: number(raw.durationSeconds),
        year: number(raw.year),
        suffix: text(raw.suffix),
        size: number(raw.size),
        bitRate: number(raw.bitRate),
        longForm: raw.longForm === true ? true : undefined,
        spokenKind,
        chapters: chapters?.length ? chapters : undefined,
      },
    ];
  });
}

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
