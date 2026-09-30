// Remote mode: the player bar and the queue panel drive another player (a tab made
// controllable, or a server player). Its state and queue come from the remote link; every
// command goes to it, where its own player applies it. Nothing plays in this tab.

import type { PlayerController } from "../player/controller";
import type { AudioLike, PlayerSnapshot, Track } from "../player/engine";
import type { LinkView, RemoteLink } from "./link";
import type { RemoteCommand, RemoteQueue, RemoteState } from "./protocol";

// While playing, the position shown moves on at this pace (as an audio element's timeupdate).
const TICK_MS = 250;

export const EMPTY_SNAPSHOT: PlayerSnapshot = {
  queue: [],
  keys: [],
  index: -1,
  current: null,
  playing: false,
  position: 0,
  duration: 0,
  volume: 1,
  muted: false,
  shuffle: false,
  repeat: "off",
  crossfade: false,
  crossfadeSeconds: 5,
  hasNext: false,
  hasPrevious: false,
  canUndo: false,
  spoken: false,
  chapter: -1,
  positioned: false,
  pauseAtEnd: false,
  speed: 1,
};

/** Where the target is now: its reported position, advanced while it plays. */
function positionOf(state: RemoteState, at: number, now: number): number {
  const position = state.playing ? state.position + ((Math.max(now, at) - at) / 1000) * state.rate : state.position;
  return state.duration > 0 ? Math.min(position, state.duration) : position;
}

/** What the controller uses of the link (tests give it a fake one). */
export type LinkLike = Pick<RemoteLink, "acquire" | "watch" | "send" | "subscribe" | "getView">;

export class RemoteController implements PlayerController {
  readonly audioElements: readonly AudioLike[] = [];
  private target: string | null = null;
  private view: LinkView | null = null;
  private state: RemoteState | null = null;
  private at = 0; // when `state` arrived, or was changed here (a seek)
  private queue: RemoteQueue | null = null; // the target's, with the changes made here since
  private volume: number | null = null; // set here, until the target's answer
  private snapshot: PlayerSnapshot = EMPTY_SNAPSHOT;
  private listeners = new Set<() => void>();
  private release: (() => void) | null = null;
  private unsubscribe: (() => void) | null = null;
  private tick: ReturnType<typeof setInterval> | null = null;

  constructor(private readonly link: LinkLike) {}

  /** Mirrors this target (null: none). */
  connect(target: string | null): void {
    if (target === this.target) return;
    this.disconnect();
    if (target === null) return;
    this.target = target;
    this.release = this.link.acquire();
    this.link.watch(target);
    this.unsubscribe = this.link.subscribe(() => this.onLink(this.link.getView()));
    this.onLink(this.link.getView());
  }

  disconnect(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    if (this.target) this.link.watch(null);
    this.release?.();
    this.release = null;
    this.target = null;
    this.view = null;
    this.state = null;
    this.queue = null;
    this.volume = null;
    this.setTicking(false);
    this.emit();
  }

  // --- subscription (useSyncExternalStore) -----------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): PlayerSnapshot => this.snapshot;

  get currentTime(): number {
    return this.state ? positionOf(this.state, this.at, Date.now()) : 0;
  }

  get playbackRate(): number {
    return this.state?.rate ?? 1;
  }

  // --- commands -----------------------------------------------------------------

  playQueue(tracks: Track[], startIndex = 0, startAt?: number): void {
    this.send({ name: "playQueue", tracks, index: startIndex, startAt });
  }

  add(tracks: Track[]): void {
    if (tracks.length) this.send({ name: "add", tracks });
  }

  playNext(tracks: Track[]): void {
    if (tracks.length) this.send({ name: "playNext", tracks });
  }

  remove(positions: number[]): void {
    const keys = positions.map((p) => this.snapshot.keys[p]).filter((k): k is number => k !== undefined);
    if (!keys.length) return;
    // At once here (the target's queue follows).
    const doomed = new Set(keys);
    this.editQueue((entries) => entries.filter((entry) => !doomed.has(entry.key)));
    this.send({ name: "remove", keys });
  }

  move(from: number, to: number): void {
    const keys = this.snapshot.keys;
    const key = keys[from];
    if (key === undefined || from === to) return;
    const others = keys.filter((_, i) => i !== from);
    const before = others[to] ?? null;
    this.editQueue((entries) => {
      const [moved] = entries.splice(from, 1);
      if (moved) entries.splice(to, 0, moved);
      return entries;
    });
    this.send({ name: "move", key, before });
  }

  clear(): void {
    this.send({ name: "clear" });
  }

  undo(): void {
    this.send({ name: "undo" });
  }

  playAt(index: number): void {
    const key = this.snapshot.keys[index];
    if (key !== undefined) this.send({ name: "playAt", key });
  }

  togglePlay(): void {
    this.send({ name: "toggle" });
  }

  pause(): void {
    this.send({ name: "pause" });
  }

  next(): void {
    this.send({ name: "next" });
  }

  previous(): void {
    this.send({ name: "previous" });
  }

  seek(seconds: number): void {
    if (this.state) {
      this.state = { ...this.state, position: seconds };
      this.at = Date.now();
      this.emit();
    }
    this.send({ name: "seek", position: seconds });
  }

  setPauseAtEnd(enabled: boolean): void {
    this.send({ name: "pauseAtEnd", value: enabled });
  }

  setVolume(volume: number): void {
    this.volume = Math.min(1, Math.max(0, volume));
    this.emit();
    this.send({ name: "volume", value: this.volume });
  }

  toggleMute(): void {
    this.send({ name: "mute" });
  }

  toggleShuffle(): void {
    this.send({ name: "shuffle" });
  }

  cycleRepeat(): void {
    this.send({ name: "repeat" });
  }

  toggleCrossfade(): void {
    this.send({ name: "crossfade" });
  }

  setCrossfade(enabled: boolean): void {
    if (this.state && this.state.crossfade !== enabled) this.toggleCrossfade();
  }

  setCrossfadeSeconds(seconds: number): void {
    this.send({ name: "crossfadeSeconds", value: seconds });
  }

  setSpokenSpeed(speed: number): void {
    this.send({ name: "speed", value: speed });
  }

  // --- internals ----------------------------------------------------------------

  /** Changes this copy of the queue at once (the target's answer replaces it). */
  private editQueue(edit: (entries: { key: number; track: Track }[]) => { key: number; track: Track }[]): void {
    const queue = this.queue;
    if (!queue) return;
    const entries = queue.keys.flatMap((key, i) => {
      const track = queue.tracks[i];
      return track ? [{ key, track }] : [];
    });
    const edited = edit(entries);
    this.queue = { ...queue, keys: edited.map((e) => e.key), tracks: edited.map((e) => e.track) };
    this.emit();
  }

  private send(command: RemoteCommand): void {
    if (this.target) this.link.send(this.target, command);
  }

  private onLink(view: LinkView): void {
    const previous = this.view;
    this.view = view;
    const target = view.targets?.find((t) => t.id === this.target);
    const previousTarget = previous?.targets?.find((t) => t.id === this.target);
    if (target?.state && (target.state !== previousTarget?.state || !this.state)) {
      this.state = target.state;
      this.at = target.at;
      this.volume = null; // the target's answer
    }
    if (view.queue !== previous?.queue) this.queue = view.queue;
    this.emit();
  }

  private setTicking(on: boolean): void {
    if (on && !this.tick) this.tick = setInterval(() => this.emit(), TICK_MS);
    if (!on && this.tick) {
      clearInterval(this.tick);
      this.tick = null;
    }
  }

  private emit(): void {
    this.snapshot = this.buildSnapshot();
    this.setTicking(this.snapshot.playing);
    this.listeners.forEach((listener) => listener());
  }

  private buildSnapshot(): PlayerSnapshot {
    const state = this.state;
    if (!state) return EMPTY_SNAPSHOT;
    const { rate: _rate, queueRevision: _revision, currentKey, ...rest } = state;
    const queue = this.queue;
    // The current entry in this copy of the queue (it may have moved here already).
    const index = queue ? (currentKey === null ? -1 : queue.keys.indexOf(currentKey)) : state.index;
    return {
      ...rest,
      queue: queue?.tracks ?? [],
      keys: queue?.keys ?? [],
      index: queue && index < 0 && currentKey !== null ? state.index : index,
      position: positionOf(state, this.at, Date.now()),
      volume: this.volume ?? state.volume,
    };
  }
}
