// Audio playback engine: queue, shuffle, repeat and crossfade.
//
// Two audio elements ("decks") are used so the next track can start while the current
// one fades out. Only the active deck drives the state shown in the UI.

import { nextIndex, nextRepeatMode, previousIndex, type RepeatMode, shuffleEntries } from "./queue";

export interface Track {
  id: string;
  title: string;
  artist?: string;
  album?: string;
  albumId?: string;
  artistId?: string;
  coverArt?: string;
  durationSeconds?: number;
  year?: number;
  suffix?: string;
  size?: number; // bytes
  bitRate?: number; // kbps
}

/** The subset of HTMLAudioElement the engine uses (lets tests use a fake). */
export interface AudioLike {
  src: string;
  currentTime: number;
  readonly duration: number;
  volume: number;
  muted: boolean;
  readonly paused: boolean;
  play(): Promise<void>;
  pause(): void;
  load(): void;
  removeAttribute(name: string): void;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
}

export interface PlayerSnapshot {
  queue: Track[]; // in play order
  keys: number[]; // stable id of each queue entry (the same track can be queued twice)
  index: number; // position of the current track in `queue`, -1 if none
  current: Track | null;
  playing: boolean;
  position: number; // seconds
  duration: number; // seconds
  volume: number; // 0..1
  muted: boolean;
  shuffle: boolean;
  repeat: RepeatMode;
  crossfade: boolean;
  crossfadeSeconds: number;
  hasNext: boolean;
  hasPrevious: boolean;
  canUndo: boolean;
}

/** The queue as saved on the server (see useWebQueue). */
export interface QueueState {
  tracks: Track[]; // play order
  originalOrder: number[] | null; // shuffled: the play positions in the original order
  index: number;
  position: number; // seconds into the current track
}

export interface EngineOptions {
  streamUrl(trackId: string): string;
  createAudio?(): AudioLike;
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  now?(): number;
}

interface Entry {
  key: number; // the same track can be queued twice
  track: Track;
}

interface Preferences {
  volume: number;
  muted: boolean;
  shuffle: boolean;
  repeat: RepeatMode;
  crossfade: boolean;
  crossfadeSeconds: number;
}

const PREFERENCES_KEY = "sound-barrier.player";
const DEFAULT_PREFERENCES: Preferences = {
  volume: 1,
  muted: false,
  shuffle: false,
  repeat: "off",
  crossfade: false,
  crossfadeSeconds: 5,
};
export const MAX_CROSSFADE_SECONDS = 12;
/** "Previous" restarts the current track when it has played longer than this. */
const RESTART_THRESHOLD_SECONDS = 3;
const FADE_TICK_MS = 50;
const UNDO_LEVELS = 20;
const DECK_EVENTS = ["timeupdate", "durationchange", "play", "pause", "ended", "error"] as const;

export class PlayerEngine {
  private readonly options: EngineOptions;
  private readonly decks: [AudioLike, AudioLike];
  private readonly detach: (() => void)[] = [];
  private active = 0;
  private original: Entry[] = [];
  private order: Entry[] = [];
  private index = -1;
  private nextKey = 0;
  private prefs: Preferences;
  private fade: { timer: ReturnType<typeof setInterval>; next: number; start: number; ms: number } | null = null;
  private listeners = new Set<() => void>();
  private snapshot: PlayerSnapshot;
  private history: { original: Entry[]; order: Entry[]; index: number }[] = [];

  constructor(options: EngineOptions) {
    this.options = options;
    const create = options.createAudio ?? (() => new Audio());
    this.decks = [create(), create()];
    this.prefs = this.loadPreferences();
    this.decks.forEach((deck, deckIndex) => {
      for (const type of DECK_EVENTS) {
        const listener = () => this.onDeckEvent(deckIndex, type);
        deck.addEventListener(type, listener);
        this.detach.push(() => deck.removeEventListener(type, listener));
      }
    });
    this.applyVolumes();
    this.snapshot = this.buildSnapshot();
  }

  // --- subscription (useSyncExternalStore) -----------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): PlayerSnapshot => this.snapshot;

  destroy(): void {
    this.cancelFade();
    this.decks.forEach((deck) => deck.pause());
    this.detach.forEach((detach) => detach());
    this.listeners.clear();
  }

  // --- commands -----------------------------------------------------------------

  /** Replaces the queue and starts playing `tracks[startIndex]`. */
  playQueue(tracks: Track[], startIndex = 0): void {
    if (this.order.length) this.remember();
    this.original = tracks.map((track) => ({ key: this.nextKey++, track }));
    const first = this.original[startIndex];
    if (this.prefs.shuffle) {
      this.order = shuffleEntries(this.original, first);
      this.index = first ? 0 : -1;
    } else {
      this.order = [...this.original];
      this.index = first ? startIndex : -1;
    }
    this.load(true);
  }

  /** Appends tracks to the end of the queue. An empty queue gets them without autoplay. */
  add(tracks: Track[]): void {
    const entries = tracks.map((track) => ({ key: this.nextKey++, track }));
    if (!entries.length) return;
    this.original.push(...entries);
    this.order.push(...entries);
    if (this.index === -1) {
      this.index = 0;
      this.load(false);
    } else {
      this.emit();
    }
  }

  /** Inserts tracks right after the current one. */
  playNext(tracks: Track[]): void {
    const entries = tracks.map((track) => ({ key: this.nextKey++, track }));
    if (!entries.length) return;
    const current = this.currentEntry;
    if (!current) {
      this.add(tracks);
      return;
    }
    this.cancelFade(); // the upcoming track changes
    this.order.splice(this.index + 1, 0, ...entries);
    this.original.splice(this.original.indexOf(current) + 1, 0, ...entries);
    this.emit();
  }

  /** Removes the tracks at these queue positions. Removing the playing track moves on. */
  remove(positions: number[]): void {
    const doomed = new Set(positions.map((p) => this.order[p]).filter((e): e is Entry => e !== undefined));
    if (!doomed.size) return;
    this.remember();
    this.cancelFade();
    const current = this.currentEntry;
    const removingCurrent = current !== undefined && doomed.has(current);
    const following = removingCurrent ? this.order.slice(this.index + 1).find((e) => !doomed.has(e)) : undefined;
    this.order = this.order.filter((e) => !doomed.has(e));
    this.original = this.original.filter((e) => !doomed.has(e));
    if (!removingCurrent) {
      this.index = current ? this.order.indexOf(current) : -1;
      this.emit();
      return;
    }
    const wasPlaying = !this.deck.paused;
    this.index = following ? this.order.indexOf(following) : -1;
    this.load(wasPlaying);
  }

  /** Moves the track at queue position `from` to position `to` (drag and drop). */
  move(from: number, to: number): void {
    const length = this.order.length;
    if (from === to || from < 0 || from >= length || to < 0 || to >= length) return;
    this.remember();
    this.cancelFade(); // the upcoming track may change
    const current = this.currentEntry;
    const [entry] = this.order.splice(from, 1);
    if (entry) this.order.splice(to, 0, entry);
    // Without shuffle, the manual order becomes the queue order.
    if (!this.prefs.shuffle) this.original = [...this.order];
    this.index = current ? this.order.indexOf(current) : -1;
    this.emit();
  }

  /** Empties the queue and stops playback. */
  clear(): void {
    if (!this.order.length) return;
    this.remember();
    this.original = [];
    this.order = [];
    this.index = -1;
    this.load(false);
  }

  /** Reverts the last queue change (replace, remove, move, clear). */
  undo(): void {
    const previous = this.history.pop();
    if (!previous) return;
    this.cancelFade();
    const current = this.currentEntry;
    this.original = previous.original;
    this.order = previous.order;
    if (current && this.order.includes(current)) {
      // Keep playing what is playing now.
      this.index = this.order.indexOf(current);
      this.emit();
    } else {
      this.index = previous.index;
      this.load(false);
    }
  }

  /** Plays the track at `index` of the current (play-order) queue. */
  playAt(index: number): void {
    if (index < 0 || index >= this.order.length) return;
    this.index = index;
    this.load(true);
  }

  togglePlay(): void {
    const deck = this.deck;
    if (!this.currentEntry) return;
    if (deck.paused) {
      void deck.play().catch(() => this.emit());
    } else {
      this.cancelFade();
      deck.pause();
    }
  }

  next(): void {
    const next = nextIndex(this.index, this.order.length, this.prefs.repeat, false);
    if (next === null) return;
    this.index = next;
    this.load(true);
  }

  previous(): void {
    if (this.deck.currentTime > RESTART_THRESHOLD_SECONDS) {
      this.seek(0);
      return;
    }
    const previous = previousIndex(this.index, this.order.length, this.prefs.repeat);
    if (previous === null) {
      this.seek(0);
      return;
    }
    this.index = previous;
    this.load(true);
  }

  seek(seconds: number): void {
    this.cancelFade();
    this.deck.currentTime = seconds;
    this.emit();
  }

  setVolume(volume: number): void {
    this.prefs.volume = Math.min(1, Math.max(0, volume));
    if (this.prefs.volume > 0) this.prefs.muted = false;
    this.savePreferences();
    if (!this.fade) this.applyVolumes();
    this.emit();
  }

  toggleMute(): void {
    this.prefs.muted = !this.prefs.muted;
    this.savePreferences();
    this.decks.forEach((deck) => (deck.muted = this.prefs.muted));
    this.emit();
  }

  /** Shuffle randomizes the current queue; turning it off restores the original order. */
  toggleShuffle(): void {
    const current = this.currentEntry;
    this.prefs.shuffle = !this.prefs.shuffle;
    this.savePreferences();
    this.cancelFade();
    if (this.prefs.shuffle) {
      this.order = shuffleEntries(this.original, current);
      this.index = current ? 0 : -1;
    } else {
      this.order = [...this.original];
      this.index = current ? this.order.indexOf(current) : -1;
    }
    this.emit();
  }

  cycleRepeat(): void {
    this.prefs.repeat = nextRepeatMode(this.prefs.repeat);
    this.savePreferences();
    this.emit();
  }

  toggleCrossfade(): void {
    this.setCrossfade(!this.prefs.crossfade);
  }

  setCrossfade(enabled: boolean): void {
    if (this.prefs.crossfade === enabled) return;
    this.prefs.crossfade = enabled;
    this.savePreferences();
    if (!enabled) this.cancelFade();
    this.emit();
  }

  setCrossfadeSeconds(seconds: number): void {
    this.prefs.crossfadeSeconds = Math.min(MAX_CROSSFADE_SECONDS, Math.max(1, Math.round(seconds)));
    this.savePreferences();
    this.emit();
  }

  /** The queue to save: play order, original order when shuffled, current track. */
  exportQueue(): QueueState {
    let originalOrder: number[] | null = null;
    if (this.prefs.shuffle) {
      const playPosition = new Map(this.order.map((entry, position) => [entry, position]));
      originalOrder = this.original.map((entry) => playPosition.get(entry) ?? 0);
    }
    return {
      tracks: this.order.map((entry) => entry.track),
      originalOrder,
      index: this.index,
      position: this.deck.currentTime || 0,
    };
  }

  /**
   * Replaces the queue with a saved one, paused on its current track at its position
   * (browsers only play after a click anyway). The shuffle mode follows the saved queue.
   * The undo history starts afresh.
   */
  restoreQueue(state: QueueState): void {
    this.cancelFade();
    this.history = [];
    this.order = state.tracks.map((track) => ({ key: this.nextKey++, track }));
    const length = this.order.length;
    const original = state.originalOrder;
    const valid = original !== null && original.length === length && new Set(original).size === length;
    this.original = valid ? original.map((position) => this.order[position] as Entry) : [...this.order];
    if (this.prefs.shuffle !== valid) {
      this.prefs.shuffle = valid;
      this.savePreferences();
    }
    this.index = length ? Math.min(Math.max(state.index, 0), length - 1) : -1;
    this.load(false);
    // Before the audio is loaded, this sets where it will start.
    if (this.currentEntry && state.position > 0) this.deck.currentTime = state.position;
    this.emit();
  }

  // --- internals ----------------------------------------------------------------

  private remember(): void {
    this.history.push({ original: [...this.original], order: [...this.order], index: this.index });
    if (this.history.length > UNDO_LEVELS) this.history.shift();
  }

  private get deck(): AudioLike {
    return this.decks[this.active] as AudioLike;
  }

  private get otherDeck(): AudioLike {
    return this.decks[1 - this.active] as AudioLike;
  }

  private get currentEntry(): Entry | undefined {
    return this.order[this.index];
  }

  private load(autoplay: boolean): void {
    this.cancelFade();
    const deck = this.deck;
    const entry = this.currentEntry;
    if (!entry) {
      deck.pause();
      deck.removeAttribute("src");
      deck.load();
      this.emit();
      return;
    }
    deck.src = this.options.streamUrl(entry.track.id);
    this.applyVolumes();
    if (autoplay) void deck.play().catch(() => this.emit());
    this.emit();
  }

  private onDeckEvent(deckIndex: number, type: (typeof DECK_EVENTS)[number]): void {
    if (deckIndex !== this.active) return; // the incoming deck of a crossfade is silent state-wise
    if (type === "ended") {
      this.onEnded();
      return;
    }
    if (type === "timeupdate") this.maybeStartCrossfade();
    this.emit();
  }

  private onEnded(): void {
    if (this.fade) {
      this.finishFade();
      return;
    }
    const next = nextIndex(this.index, this.order.length, this.prefs.repeat, true);
    if (next === null) {
      this.emit();
      return;
    }
    if (next === this.index) {
      this.deck.currentTime = 0;
      void this.deck.play().catch(() => this.emit());
      return;
    }
    this.index = next;
    this.load(true);
  }

  private maybeStartCrossfade(): void {
    const seconds = this.prefs.crossfadeSeconds;
    if (!this.prefs.crossfade || this.fade || this.prefs.repeat === "one") return;
    const deck = this.deck;
    const duration = deck.duration;
    if (deck.paused || !Number.isFinite(duration) || duration < seconds * 2) return;
    const remaining = duration - deck.currentTime;
    if (remaining > seconds) return;
    const next = nextIndex(this.index, this.order.length, this.prefs.repeat, true);
    const entry = next === null ? undefined : this.order[next];
    if (next === null || !entry) return;

    const incoming = this.otherDeck;
    incoming.src = this.options.streamUrl(entry.track.id);
    incoming.volume = 0;
    incoming.muted = this.prefs.muted;
    void incoming.play().catch(() => this.cancelFade());
    this.fade = {
      timer: setInterval(() => this.fadeTick(), FADE_TICK_MS),
      next,
      start: this.now(),
      ms: Math.max(remaining, 0.1) * 1000,
    };
  }

  private fadeTick(): void {
    if (!this.fade) return;
    const progress = Math.min(1, (this.now() - this.fade.start) / this.fade.ms);
    this.deck.volume = this.prefs.volume * (1 - progress);
    this.otherDeck.volume = this.prefs.volume * progress;
    if (progress >= 1) this.finishFade();
  }

  private finishFade(): void {
    if (!this.fade) return;
    clearInterval(this.fade.timer);
    const outgoing = this.deck;
    outgoing.pause();
    outgoing.removeAttribute("src");
    outgoing.load();
    this.active = 1 - this.active;
    this.index = this.fade.next;
    this.fade = null;
    this.applyVolumes();
    this.emit();
  }

  private cancelFade(): void {
    if (!this.fade) return;
    clearInterval(this.fade.timer);
    this.fade = null;
    const incoming = this.otherDeck;
    incoming.pause();
    incoming.removeAttribute("src");
    incoming.load();
    this.applyVolumes();
  }

  private applyVolumes(): void {
    for (const deck of this.decks) {
      deck.volume = this.prefs.volume;
      deck.muted = this.prefs.muted;
    }
  }

  private now(): number {
    return this.options.now ? this.options.now() : Date.now();
  }

  private emit(): void {
    this.snapshot = this.buildSnapshot();
    this.listeners.forEach((listener) => listener());
  }

  private buildSnapshot(): PlayerSnapshot {
    const deck = this.deck;
    const current = this.currentEntry?.track ?? null;
    const length = this.order.length;
    return {
      queue: this.order.map((entry) => entry.track),
      keys: this.order.map((entry) => entry.key),
      index: this.index,
      current,
      playing: current !== null && !deck.paused,
      position: deck.currentTime || 0,
      duration: Number.isFinite(deck.duration) && deck.duration > 0 ? deck.duration : (current?.durationSeconds ?? 0),
      volume: this.prefs.volume,
      muted: this.prefs.muted,
      shuffle: this.prefs.shuffle,
      repeat: this.prefs.repeat,
      crossfade: this.prefs.crossfade,
      crossfadeSeconds: this.prefs.crossfadeSeconds,
      hasNext: current !== null && nextIndex(this.index, length, this.prefs.repeat, false) !== null,
      hasPrevious: current !== null,
      canUndo: this.history.length > 0,
    };
  }

  private loadPreferences(): Preferences {
    try {
      const raw = this.options.storage?.getItem(PREFERENCES_KEY);
      if (raw) return { ...DEFAULT_PREFERENCES, ...(JSON.parse(raw) as Partial<Preferences>) };
    } catch {
      // unavailable storage or corrupted value
    }
    return { ...DEFAULT_PREFERENCES };
  }

  private savePreferences(): void {
    try {
      this.options.storage?.setItem(PREFERENCES_KEY, JSON.stringify(this.prefs));
    } catch {
      // storage unavailable: preferences last for this page only
    }
  }
}
