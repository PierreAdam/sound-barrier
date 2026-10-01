// Audio playback engine: queue, shuffle, repeat and crossfade.
//
// Two audio elements ("decks") are used so the next track can start while the current
// one fades out. Only the active deck drives the state shown in the UI.
//
// Audiobooks and podcasts ("long-form" tracks) play without shuffle, repeat or crossfade
// (the settings stay as they are for the music), and "previous" / "next" move by the
// chapters inside the file when it has some.

import type { PlayerController } from "./controller";
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
  longForm?: boolean; // an audiobook or a podcast: its position is kept as a bookmark
  spokenKind?: "podcasts" | "audiobooks"; // the section of a long-form track
  chapters?: Chapter[]; // inside the file (audiobooks), by start
  book?: BookPlace; // audiobooks: where the file is in its book
}

/** Where a file is in its audiobook (the book's files in order, chapters inside them). */
export interface BookPlace {
  start: number; // seconds of the book before this file
  duration: number; // seconds: the whole book
  chapter: number; // the book's chapters before this file (a file without any counts as one)
  chapters: number; // the book's chapters
}

/** A chapter inside a file ("soft" chapter, from its tags). */
export interface Chapter {
  start: number; // seconds
  title: string;
}

/** The chapter playing at `position` (seconds), -1 before the first / without chapters. */
export function chapterIndex(chapters: readonly Chapter[] | undefined, position: number): number {
  if (!chapters) return -1;
  let found = -1;
  chapters.forEach((chapter, i) => {
    if (chapter.start <= position + CHAPTER_SLACK_SECONDS) found = i;
  });
  return found;
}

/** The subset of HTMLAudioElement the engine uses (lets tests use a fake). */
export interface AudioLike {
  src: string;
  currentTime: number;
  readonly duration: number;
  volume: number;
  muted: boolean;
  playbackRate: number;
  defaultPlaybackRate: number;
  readonly paused: boolean;
  readonly readyState: number;
  readonly seeking: boolean;
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
  /** An audiobook or a podcast is playing: no shuffle, repeat or crossfade. */
  spoken: boolean;
  /** The current track's chapter being played (-1: none / no chapters). */
  chapter: number;
  /** The current track was started at a chosen position (a chapter): not to be resumed. */
  positioned: boolean;
  /** Audiobooks and podcasts: pause when the current chapter (or file) ends, once. */
  pauseAtEnd: boolean;
  /** Playback speed of audiobooks and podcasts (music always plays at 1x). */
  speed: number;
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
  /** Told what the audio does (diagnostics, see audioTrace.ts). */
  trace?(line: string): void;
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
/** This close before a chapter's start counts as in it (seeks may land a bit early). */
const CHAPTER_SLACK_SECONDS = 0.5;
const FADE_TICK_MS = 50;
/** "Pause at end of chapter": the exact stop is timed when the chapter ends within this. */
const STOP_TIMER_SECONDS = 1.5;
const UNDO_LEVELS = 20;
const DECK_EVENTS = [
  "timeupdate",
  "durationchange",
  "loadedmetadata",
  "canplay",
  "play",
  "playing",
  "pause",
  "seeking",
  "seeked",
  "ended",
  "error",
] as const;
const HAVE_METADATA = 1; // HTMLMediaElement.readyState
const HAVE_FUTURE_DATA = 3;
/** A start position counts as reached this close (seeks land near, not on, a time). */
const START_SLACK_SECONDS = 1.5;
/** Seeks to a start position before giving up on it (Safari may drop each one). */
const START_TRIES = 5;
/** Playing and still seeking there after this: the seek is stuck, asked again. */
const STUCK_SEEK_MS = 2000;
/** Timeupdates traced after a start position was reached (to see playback go on). */
const TRACED_TICKS = 4;

export class PlayerEngine implements PlayerController {
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
  // Speed of podcasts and audiobooks (music always plays at 1x).
  private spokenSpeed = 1;
  private pauseAtEnd = false;
  private stopTimer: ReturnType<typeof setTimeout> | null = null;
  private history: { original: Entry[]; order: Entry[]; index: number }[] = [];
  // The entry started at a chosen position (playQueue's `startAt`).
  private positionedKey: number | null = null;
  // Where the current track must start, until its audio plays from there (see `place`).
  private startAt: number | null = null;
  private startTries = 0;
  private startTimer: ReturnType<typeof setTimeout> | null = null;
  private tracedTicks = 0;

  constructor(options: EngineOptions) {
    this.options = options;
    const create = options.createAudio ?? (() => new Audio());
    this.decks = [create(), create()];
    this.prefs = this.loadPreferences();
    this.attach();
    this.applyVolumes();
    this.snapshot = this.buildSnapshot();
  }

  // --- subscription (useSyncExternalStore) -----------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): PlayerSnapshot => this.snapshot;

  /** The exact position in seconds (the snapshot's follows "timeupdate", ~4 times a second). */
  get currentTime(): number {
    return this.position;
  }

  /** Both audio elements (crossfade): the visualizer listens to them. */
  get audioElements(): readonly AudioLike[] {
    return this.decks;
  }

  /**
   * Listens to the audio elements again after `destroy` (done by the constructor). React's
   * StrictMode unmounts and mounts every component once in development: without this, the
   * engine kept by the provider no longer heard its decks (time and lyrics stood still).
   */
  attach(): void {
    if (this.detach.length) return;
    this.decks.forEach((deck, deckIndex) => {
      for (const type of DECK_EVENTS) {
        const listener = () => this.onDeckEvent(deckIndex, type);
        deck.addEventListener(type, listener);
        this.detach.push(() => deck.removeEventListener(type, listener));
      }
    });
  }

  destroy(): void {
    this.cancelFade();
    this.clearStopTimer();
    if (this.startTimer) clearTimeout(this.startTimer);
    this.startTimer = null;
    this.decks.forEach((deck) => deck.pause());
    this.detach.forEach((detach) => detach());
    this.detach.length = 0;
    this.listeners.clear();
  }

  // --- commands -----------------------------------------------------------------

  /**
   * Replaces the queue and starts playing `tracks[startIndex]`, from `startAt` seconds
   * when given (a chapter). Audiobooks and podcasts are never shuffled.
   */
  playQueue(tracks: Track[], startIndex = 0, startAt?: number): void {
    if (this.order.length) this.remember();
    this.original = tracks.map((track) => ({ key: this.nextKey++, track }));
    const first = this.original[startIndex];
    if (this.prefs.shuffle && !first?.track.longForm) {
      this.order = shuffleEntries(this.original, first);
      this.index = first ? 0 : -1;
    } else {
      this.order = [...this.original];
      this.index = first ? startIndex : -1;
    }
    this.positionedKey = first && startAt !== undefined ? first.key : null;
    this.load(true);
    if (first && startAt) {
      this.place(startAt);
      this.emit();
    }
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
      this.pause();
    }
  }

  pause(): void {
    this.cancelFade();
    this.clearStopTimer();
    this.deck.pause();
  }

  next(): void {
    const chapters = this.currentEntry?.track.chapters;
    const chapter = chapters?.[chapterIndex(chapters, this.position) + 1];
    if (chapter) {
      this.seek(chapter.start);
      return;
    }
    const next = nextIndex(this.index, this.order.length, this.repeatMode, false);
    if (next === null) return;
    this.index = next;
    this.load(true);
  }

  previous(): void {
    const position = this.position;
    const chapters = this.currentEntry?.track.chapters;
    const current = chapterIndex(chapters, position);
    if (chapters && current >= 0) {
      // The chapter's start, or the previous chapter right after it started.
      const start = chapters[current]?.start ?? 0;
      const target = position - start > RESTART_THRESHOLD_SECONDS ? start : chapters[current - 1]?.start;
      if (target !== undefined) {
        this.seek(target);
        return;
      }
    }
    if (position > RESTART_THRESHOLD_SECONDS) {
      this.seek(0);
      return;
    }
    const previous = previousIndex(this.index, this.order.length, this.repeatMode);
    if (previous === null) {
      this.seek(0);
      return;
    }
    this.index = previous;
    this.load(true);
  }

  seek(seconds: number): void {
    this.cancelFade();
    this.clearStopTimer();
    this.place(seconds);
    this.emit();
  }

  /**
   * Audiobooks and podcasts: pause at the end of the chapter playing when it ends (a
   * chapter inside the file, else the file), exactly at the next one's start, so playing
   * again starts it. Once: it turns itself off. Turned off by a music track.
   */
  setPauseAtEnd(enabled: boolean): void {
    this.pauseAtEnd = enabled;
    this.clearStopTimer();
    this.checkPauseAtEnd();
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
    if (this.spoken) return;
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
    if (this.spoken) return;
    this.prefs.repeat = nextRepeatMode(this.prefs.repeat);
    this.savePreferences();
    this.emit();
  }

  toggleCrossfade(): void {
    if (this.spoken) return;
    this.setCrossfade(!this.prefs.crossfade);
  }

  setCrossfade(enabled: boolean): void {
    if (this.prefs.crossfade === enabled) return;
    this.prefs.crossfade = enabled;
    this.savePreferences();
    if (!enabled) this.cancelFade();
    this.emit();
  }

  /** Playback speed of podcasts and audiobooks (1 to 2); music is not affected. */
  setSpokenSpeed(speed: number): void {
    this.spokenSpeed = Math.min(2, Math.max(1, speed));
    const current = this.currentEntry;
    if (current) this.applySpeed(this.deck, current.track);
    this.emit();
  }

  /** The current playback speed (for the OS' lock screen progress). */
  get playbackRate(): number {
    return this.deck.playbackRate || 1;
  }

  get currentSpokenSpeed(): number {
    return this.spokenSpeed;
  }

  private applySpeed(deck: AudioLike, track: Track): void {
    const speed = track.longForm ? this.spokenSpeed : 1;
    // Both: browsers reset playbackRate to defaultPlaybackRate when a new source loads.
    deck.defaultPlaybackRate = speed;
    deck.playbackRate = speed;
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
      position: this.position,
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
    if (this.currentEntry && state.position > 0) this.place(state.position);
    this.emit();
  }

  // --- internals ----------------------------------------------------------------

  /** Where the current track is, or will start once its audio is loaded. */
  private get position(): number {
    return this.startAt ?? (this.deck.currentTime || 0);
  }

  /**
   * Puts the current track at `seconds`. Its audio not loaded yet (phones load it only
   * once played), the position is kept as its start position instead, reported (and
   * saved) meanwhile, and sought once it plays (`followStart`): Safari on iOS starts a
   * seek asked before, and never completes it (it reads the position, and plays from 0).
   */
  private place(seconds: number): void {
    const deck = this.deck;
    this.clearStart();
    if (deck.readyState >= HAVE_METADATA) {
      this.setTime(deck, seconds);
      return;
    }
    this.startAt = seconds;
    this.trace(`start at ${seconds.toFixed(1)} (not loaded)`);
  }

  /** A start position is pending: once the audio plays, it goes there (see `place`). */
  private followStart(type: (typeof DECK_EVENTS)[number]): void {
    const deck = this.deck;
    const target = this.startAt;
    // Not before it plays, and has the data to (a seek is not asked before on iOS).
    if (target === null || deck.paused || deck.readyState < HAVE_FUTURE_DATA || deck.seeking) return;
    if (Math.abs(deck.currentTime - target) > START_SLACK_SECONDS) {
      this.seekStart(target, "not there");
    } else if (type === "timeupdate" || type === "seeked") {
      this.clearStart();
      this.tracedTicks = TRACED_TICKS;
      this.trace("start reached");
    }
  }

  private seekStart(target: number, why: string): void {
    if (this.startTimer) clearTimeout(this.startTimer);
    this.startTimer = null;
    if (this.startTries >= START_TRIES) {
      this.clearStart();
      this.trace(`start given up (${why})`);
      return;
    }
    this.startTries++;
    this.trace(`seek to start (${why}, try ${this.startTries})`);
    this.setTime(this.deck, target);
    // Safari may leave a seek pending, playing on from where it was (and no timeupdate).
    this.startTimer = setTimeout(() => {
      this.startTimer = null;
      const deck = this.deck;
      if (this.startAt === target && deck.seeking && !deck.paused) this.seekStart(target, "stuck");
    }, STUCK_SEEK_MS);
  }

  private clearStart(): void {
    if (this.startTimer) clearTimeout(this.startTimer);
    this.startTimer = null;
    this.startAt = null;
    this.startTries = 0;
  }

  private setTime(deck: AudioLike, seconds: number): void {
    try {
      deck.currentTime = seconds;
    } catch (error) {
      this.trace(`currentTime refused: ${String(error)}`);
    }
  }

  private trace(line: string): void {
    this.options.trace?.(line);
  }

  private traceDeck(type: string): void {
    if (!this.options.trace) return;
    if (type === "timeupdate" && this.startAt === null) {
      if (this.tracedTicks <= 0) return;
      this.tracedTicks--;
    }
    const deck = this.deck;
    const flags = [deck.seeking && "seeking", deck.paused && "paused"].filter(Boolean).join(" ");
    const pending = this.startAt === null ? "" : ` start ${this.startAt.toFixed(1)}`;
    this.trace(`${type} rs${deck.readyState} t${(deck.currentTime || 0).toFixed(1)} ${flags}${pending}`);
  }

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

  /** An audiobook or a podcast is playing. */
  private get spoken(): boolean {
    return this.currentEntry?.track.longForm ?? false;
  }

  /** Repeat as it applies now: never for audiobooks and podcasts. */
  private get repeatMode(): RepeatMode {
    return this.spoken ? "off" : this.prefs.repeat;
  }

  private load(autoplay: boolean): void {
    this.cancelFade();
    this.clearStopTimer();
    this.clearStart(); // a new source starts at 0
    this.tracedTicks = 0;
    const deck = this.deck;
    const entry = this.currentEntry;
    if (!entry?.track.longForm) this.pauseAtEnd = false;
    if (!entry) {
      deck.pause();
      deck.removeAttribute("src");
      deck.load();
      this.emit();
      return;
    }
    deck.src = this.options.streamUrl(entry.track.id);
    this.applySpeed(deck, entry.track);
    this.applyVolumes();
    if (autoplay) void deck.play().catch(() => this.emit());
    this.emit();
  }

  private onDeckEvent(deckIndex: number, type: (typeof DECK_EVENTS)[number]): void {
    if (deckIndex !== this.active) return; // the incoming deck of a crossfade is silent state-wise
    this.traceDeck(type);
    if (type === "ended") {
      this.onEnded();
      return;
    }
    this.followStart(type);
    if (type === "timeupdate") this.maybeStartCrossfade();
    if (type === "timeupdate" || type === "play") this.checkPauseAtEnd();
    this.emit();
  }

  /** The next chapter's start inside the file (the end of the one playing), if any. */
  private chapterEnd(position: number): number | undefined {
    // Past the slack: a chapter chosen by a seek landing just before its start is not "ended".
    return this.currentEntry?.track.chapters?.find((c) => c.start > position + CHAPTER_SLACK_SECONDS)?.start;
  }

  /** Times the stop when the current chapter is about to end (timeupdate is too coarse). */
  private checkPauseAtEnd(): void {
    const deck = this.deck;
    if (!this.pauseAtEnd || !this.spoken || deck.paused || this.stopTimer) return;
    const end = this.chapterEnd(deck.currentTime);
    if (end === undefined) return; // the file's end: onEnded
    const remaining = (end - deck.currentTime) / (deck.playbackRate || 1);
    if (remaining > STOP_TIMER_SECONDS) return;
    this.stopTimer = setTimeout(() => {
      this.stopTimer = null;
      if (!this.pauseAtEnd || this.deck.paused) return;
      this.pauseAtEnd = false;
      this.deck.pause();
      this.deck.currentTime = end;
      this.emit();
    }, Math.max(remaining, 0) * 1000);
  }

  private clearStopTimer(): void {
    if (this.stopTimer) clearTimeout(this.stopTimer);
    this.stopTimer = null;
  }

  private onEnded(): void {
    if (this.fade) {
      this.finishFade();
      return;
    }
    if (this.pauseAtEnd && this.spoken) {
      // The file ended: paused on the next one (at its start), if there is one.
      this.pauseAtEnd = false;
      this.deck.pause();
      const following = nextIndex(this.index, this.order.length, "off", true);
      if (following === null) {
        this.emit();
        return;
      }
      this.index = following;
      this.load(false);
      return;
    }
    const next = nextIndex(this.index, this.order.length, this.repeatMode, true);
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
    if (!this.prefs.crossfade || this.fade || this.prefs.repeat === "one" || this.spoken) return;
    const deck = this.deck;
    const duration = deck.duration;
    if (deck.paused || !Number.isFinite(duration) || duration < seconds * 2) return;
    const remaining = duration - deck.currentTime;
    if (remaining > seconds) return;
    const next = nextIndex(this.index, this.order.length, this.prefs.repeat, true);
    const entry = next === null ? undefined : this.order[next];
    if (next === null || !entry || entry.track.longForm) return;

    const incoming = this.otherDeck;
    incoming.src = this.options.streamUrl(entry.track.id);
    this.applySpeed(incoming, entry.track);
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
    const entry = this.currentEntry;
    const current = entry?.track ?? null;
    const length = this.order.length;
    const position = this.position;
    const chapter = chapterIndex(current?.chapters, position);
    return {
      queue: this.order.map((entry) => entry.track),
      keys: this.order.map((entry) => entry.key),
      index: this.index,
      current,
      playing: current !== null && !deck.paused,
      position,
      duration: Number.isFinite(deck.duration) && deck.duration > 0 ? deck.duration : (current?.durationSeconds ?? 0),
      volume: this.prefs.volume,
      muted: this.prefs.muted,
      shuffle: this.prefs.shuffle,
      repeat: this.prefs.repeat,
      crossfade: this.prefs.crossfade,
      crossfadeSeconds: this.prefs.crossfadeSeconds,
      hasNext:
        current !== null &&
        (chapter + 1 < (current.chapters?.length ?? 0) || nextIndex(this.index, length, this.repeatMode, false) !== null),
      hasPrevious: current !== null,
      canUndo: this.history.length > 0,
      spoken: current?.longForm ?? false,
      chapter,
      positioned: entry !== undefined && entry.key === this.positionedKey,
      pauseAtEnd: this.pauseAtEnd,
      speed: this.spokenSpeed,
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
