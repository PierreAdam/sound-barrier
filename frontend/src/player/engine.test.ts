import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type AudioLike, chapterIndex, PlayerEngine, type Track } from "./engine";
import { nextIndex, previousIndex, shuffleEntries } from "./queue";

class FakeAudio implements AudioLike {
  playbackRate = 1;
  defaultPlaybackRate = 1;
  src = "";
  currentTime = 0;
  duration = Number.NaN;
  volume = 1;
  muted = false;
  paused = true;
  private listeners = new Map<string, Set<() => void>>();

  play(): Promise<void> {
    this.paused = false;
    this.fire("play");
    return Promise.resolve();
  }
  pause(): void {
    this.paused = true;
    this.fire("pause");
  }
  load(): void {}
  removeAttribute(name: string): void {
    if (name === "src") this.src = "";
  }
  addEventListener(type: string, listener: () => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }
  removeEventListener(type: string, listener: () => void): void {
    this.listeners.get(type)?.delete(listener);
  }
  fire(type: string): void {
    this.listeners.get(type)?.forEach((listener) => listener());
  }
  /** Simulates playback reaching `time` seconds. */
  advance(time: number, duration = 200): void {
    this.duration = duration;
    this.currentTime = time;
    this.fire("timeupdate");
  }
}

const tracks: Track[] = ["a", "b", "c", "d"].map((id) => ({ id, title: id.toUpperCase() }));

function setup() {
  const decks: FakeAudio[] = [];
  let now = 0;
  const engine = new PlayerEngine({
    streamUrl: (id) => `/stream/${id}`,
    createAudio: () => {
      const deck = new FakeAudio();
      decks.push(deck);
      return deck;
    },
    now: () => now,
  });
  const playing = () => decks.find((d) => !d.paused);
  const tick = (ms: number) => {
    now += ms;
    vi.advanceTimersByTime(ms);
  };
  return { engine, decks, playing, tick };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("queue helpers", () => {
  it("keeps the current track first when shuffling", () => {
    const entries = [1, 2, 3, 4, 5];
    const shuffled = shuffleEntries(entries, 3, () => 0.5);
    expect(shuffled[0]).toBe(3);
    expect([...shuffled].sort()).toEqual(entries);
  });

  it("computes next / previous with repeat modes", () => {
    expect(nextIndex(1, 3, "off", false)).toBe(2);
    expect(nextIndex(2, 3, "off", true)).toBeNull();
    expect(nextIndex(2, 3, "all", true)).toBe(0);
    expect(nextIndex(1, 3, "one", true)).toBe(1); // track ended: replay it
    expect(nextIndex(1, 3, "one", false)).toBe(2); // "next" button still moves on
    expect(previousIndex(0, 3, "off")).toBeNull();
    expect(previousIndex(0, 3, "all")).toBe(2);
  });
});

describe("PlayerEngine", () => {
  it("plays a queue and moves to the next track when one ends", () => {
    const { engine, playing } = setup();
    engine.playQueue(tracks, 1);
    expect(engine.getSnapshot().current?.id).toBe("b");
    expect(playing()?.src).toBe("/stream/b");

    playing()?.fire("ended");
    expect(engine.getSnapshot().current?.id).toBe("c");
    expect(playing()?.src).toBe("/stream/c");
  });

  it("stops at the end without repeat and wraps with repeat all", () => {
    const { engine, playing } = setup();
    engine.playQueue(tracks, 3);
    const deck = playing();
    deck?.pause();
    deck?.fire("ended");
    expect(engine.getSnapshot().current?.id).toBe("d");
    expect(engine.getSnapshot().hasNext).toBe(false);

    engine.cycleRepeat(); // all
    expect(engine.getSnapshot().hasNext).toBe(true);
    engine.next();
    expect(engine.getSnapshot().current?.id).toBe("a");
  });

  it("previous restarts the track after a few seconds, else goes back", () => {
    const { engine, playing } = setup();
    engine.playQueue(tracks, 2);
    playing()?.advance(10);
    engine.previous();
    expect(engine.getSnapshot().current?.id).toBe("c");
    expect(playing()?.currentTime).toBe(0);
    engine.previous();
    expect(engine.getSnapshot().current?.id).toBe("b");
  });

  it("shuffles the queue around the current track and restores the order", () => {
    const { engine } = setup();
    engine.playQueue(tracks, 2);
    engine.toggleShuffle();
    let state = engine.getSnapshot();
    expect(state.current?.id).toBe("c");
    expect(state.index).toBe(0);
    expect(state.queue.map((t) => t.id).sort()).toEqual(["a", "b", "c", "d"]);

    engine.toggleShuffle();
    state = engine.getSnapshot();
    expect(state.queue.map((t) => t.id)).toEqual(["a", "b", "c", "d"]);
    expect(state.index).toBe(2);
  });

  it("adds to the end of the queue and inserts after the current track", () => {
    const { engine, playing } = setup();
    engine.add([tracks[0] as Track]); // empty queue: loaded, not playing
    expect(engine.getSnapshot().current?.id).toBe("a");
    expect(playing()).toBeUndefined();

    engine.add([tracks[1] as Track]);
    engine.playNext([tracks[2] as Track, tracks[3] as Track]);
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["a", "c", "d", "b"]);
    expect(engine.getSnapshot().current?.id).toBe("a");
  });

  it("removes tracks and moves on when the playing one is removed", () => {
    const { engine, playing } = setup();
    engine.playQueue(tracks, 1);
    engine.remove([0]);
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["b", "c", "d"]);
    expect(engine.getSnapshot().index).toBe(0);

    engine.remove([0]); // the playing track: continue with the next one
    expect(engine.getSnapshot().current?.id).toBe("c");
    expect(playing()?.src).toBe("/stream/c");

    engine.undo();
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["b", "c", "d"]);
    expect(engine.getSnapshot().current?.id).toBe("c"); // keeps playing
    engine.undo();
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["a", "b", "c", "d"]);
    expect(engine.getSnapshot().canUndo).toBe(false);
  });

  it("reorders the queue by drag and drop", () => {
    const { engine } = setup();
    engine.playQueue(tracks, 0);
    engine.move(0, 2); // playing track moved
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["b", "c", "a", "d"]);
    expect(engine.getSnapshot().index).toBe(2);
    expect(engine.getSnapshot().current?.id).toBe("a");
    engine.next();
    expect(engine.getSnapshot().current?.id).toBe("d");
  });

  it("clears the queue and undoes it without playing", () => {
    const { engine, playing } = setup();
    engine.playQueue(tracks, 2);
    engine.clear();
    expect(engine.getSnapshot().current).toBeNull();
    expect(playing()).toBeUndefined();
    engine.undo();
    expect(engine.getSnapshot().current?.id).toBe("c");
    expect(playing()).toBeUndefined();
  });

  it("crossfades into the next track before the current one ends", () => {
    const { engine, decks, tick } = setup();
    engine.setCrossfadeSeconds(4);
    engine.toggleCrossfade();
    engine.playQueue(tracks, 0);
    const [first, second] = decks as [FakeAudio, FakeAudio];

    first.advance(190); // 10 s left: nothing yet
    expect(second.paused).toBe(true);

    first.advance(196); // 4 s left: next track starts silently
    expect(second.paused).toBe(false);
    expect(second.src).toBe("/stream/b");
    expect(second.volume).toBe(0);
    expect(engine.getSnapshot().current?.id).toBe("a");

    tick(2000); // halfway
    expect(first.volume).toBeCloseTo(0.5, 1);
    expect(second.volume).toBeCloseTo(0.5, 1);

    tick(2100); // done: the second deck becomes the active one
    expect(first.paused).toBe(true);
    expect(second.volume).toBe(1);
    expect(engine.getSnapshot().current?.id).toBe("b");
  });

  it("cancels a crossfade when the user seeks", () => {
    const { engine, decks } = setup();
    engine.toggleCrossfade();
    engine.playQueue(tracks, 0);
    const [first, second] = decks as [FakeAudio, FakeAudio];
    first.advance(197);
    expect(second.paused).toBe(false);

    engine.seek(30);
    expect(second.paused).toBe(true);
    expect(first.volume).toBe(1);
    expect(engine.getSnapshot().current?.id).toBe("a");
  });

  it("does not crossfade with repeat one", () => {
    const { engine, decks } = setup();
    engine.toggleCrossfade();
    engine.cycleRepeat();
    engine.cycleRepeat(); // one
    engine.playQueue(tracks, 0);
    const [first, second] = decks as [FakeAudio, FakeAudio];
    first.advance(199);
    expect(second.paused).toBe(true);
    first.fire("ended");
    expect(engine.getSnapshot().current?.id).toBe("a");
    expect(first.currentTime).toBe(0);
  });
});

describe("audiobooks and podcasts", () => {
  const book: Track[] = [
    {
      id: "file1",
      title: "Book, file 1",
      longForm: true,
      chapters: [
        { start: 0, title: "One" },
        { start: 60, title: "Two" },
        { start: 120, title: "Three" },
      ],
    },
    { id: "file2", title: "Book, file 2", longForm: true },
  ];

  it("finds the chapter at a position", () => {
    const chapters = book[0]!.chapters;
    expect(chapterIndex(chapters, 0)).toBe(0);
    expect(chapterIndex(chapters, 59)).toBe(0);
    expect(chapterIndex(chapters, 59.8)).toBe(1); // a seek landing just before it
    expect(chapterIndex(chapters, 500)).toBe(2);
    expect(chapterIndex(undefined, 10)).toBe(-1);
  });

  it("pauses at the end of the chapter, at the next one's start, once", () => {
    const { engine, decks, tick } = setup();
    engine.playQueue(book, 0);
    const deck = decks[0] as FakeAudio;
    deck.advance(10);
    engine.setPauseAtEnd(true);
    expect(engine.getSnapshot().pauseAtEnd).toBe(true);

    deck.advance(58); // "One" ends at 60: not yet timed
    tick(1000);
    expect(deck.paused).toBe(false);
    deck.advance(59); // within 1.5 s: the stop is timed
    tick(999);
    expect(deck.paused).toBe(false);
    tick(1);
    expect(deck.paused).toBe(true);
    expect(deck.currentTime).toBe(60); // "Two" starts when played again
    expect(engine.getSnapshot().pauseAtEnd).toBe(false);

    void deck.play(); // off now: plays through
    deck.advance(119);
    tick(2000);
    expect(deck.paused).toBe(false);
  });

  it("pauses at the end of the chapter reached, not of the one it was turned on in", () => {
    const { engine, decks, tick } = setup();
    engine.playQueue(book, 0);
    const deck = decks[0] as FakeAudio;
    deck.advance(10);
    engine.setPauseAtEnd(true);
    engine.next(); // "Two" (a seek to 60)
    deck.advance(60.2);
    tick(2000);
    expect(deck.paused).toBe(false); // not stopped at the start of "Two"
    deck.advance(119);
    tick(1000);
    expect(deck.paused).toBe(true);
    expect(deck.currentTime).toBe(120);
  });

  it("at the end of a file, pauses on the next file", () => {
    const { engine, decks } = setup();
    engine.playQueue(book, 0);
    const deck = decks[0] as FakeAudio;
    deck.advance(130); // "Three": the last chapter of the file
    engine.setPauseAtEnd(true);
    deck.fire("ended");
    const state = engine.getSnapshot();
    expect(state.current?.id).toBe("file2");
    expect(state.playing).toBe(false);
    expect(state.pauseAtEnd).toBe(false);
  });

  it("is turned off by a music track", () => {
    const { engine } = setup();
    engine.playQueue(book, 0);
    engine.setPauseAtEnd(true);
    engine.playQueue(tracks, 0);
    expect(engine.getSnapshot().pauseAtEnd).toBe(false);
  });

  it("moves by the chapters inside the file, then by file", () => {
    const { engine, decks } = setup();
    engine.playQueue(book, 0);
    const deck = decks[0] as FakeAudio;
    deck.advance(10);
    expect(engine.getSnapshot().chapter).toBe(0);

    engine.next();
    expect(deck.currentTime).toBe(60);
    expect(engine.getSnapshot().chapter).toBe(1);
    engine.next();
    expect(deck.currentTime).toBe(120);
    expect(engine.getSnapshot().hasNext).toBe(true); // the next file
    engine.next();
    expect(engine.getSnapshot().current?.id).toBe("file2");
    deck.currentTime = 0; // a new source starts at 0

    engine.previous(); // at its start: back to the previous file
    expect(engine.getSnapshot().current?.id).toBe("file1");
    deck.advance(130);
    engine.previous(); // 10 s into "Three": its start
    expect(deck.currentTime).toBe(120);
    engine.previous(); // right at its start: "Two"
    expect(deck.currentTime).toBe(60);
  });

  it("starts at a chosen position, marked so the bookmark does not override it", () => {
    const { engine, decks } = setup();
    engine.playQueue(book, 0, 120);
    expect((decks[0] as FakeAudio).currentTime).toBe(120);
    expect(engine.getSnapshot().positioned).toBe(true);
    engine.playQueue(book, 0);
    expect(engine.getSnapshot().positioned).toBe(false);
  });

  it("plays them without shuffle, repeat or crossfade, keeping the music settings", () => {
    const { engine, decks } = setup();
    engine.toggleShuffle();
    engine.cycleRepeat(); // all
    engine.toggleCrossfade();
    engine.playQueue(book, 0);
    const state = engine.getSnapshot();
    expect(state.spoken).toBe(true);
    expect(state.queue.map((t) => t.id)).toEqual(["file1", "file2"]); // not shuffled

    engine.toggleShuffle();
    engine.cycleRepeat();
    engine.toggleCrossfade();
    expect([engine.getSnapshot().shuffle, engine.getSnapshot().repeat, engine.getSnapshot().crossfade]).toEqual([
      true,
      "all",
      true,
    ]);

    const [first, second] = decks as [FakeAudio, FakeAudio];
    engine.next();
    engine.next();
    engine.next(); // file2
    first.advance(199);
    expect(second.paused).toBe(true); // no crossfade
    first.fire("ended");
    expect(engine.getSnapshot().current?.id).toBe("file2"); // no repeat: stays on the last one
    expect(engine.getSnapshot().index).toBe(1);
  });
});

describe("saved queue", () => {
  it("exports and restores a shuffled queue, paused at the saved position", () => {
    const first = setup();
    first.engine.playQueue(tracks, 1);
    first.engine.toggleShuffle();
    first.decks[0]!.advance(42);
    const saved = first.engine.exportQueue();
    expect(saved.tracks.map((t) => t.id)[0]).toBe("b"); // the current track leads a shuffle
    expect([...(saved.originalOrder ?? [])].sort()).toEqual([0, 1, 2, 3]);

    const other = setup(); // another browser
    other.engine.restoreQueue(saved);
    const state = other.engine.getSnapshot();
    expect(state.queue.map((t) => t.id)).toEqual(saved.tracks.map((t) => t.id));
    expect(state.current?.id).toBe("b");
    expect(state.shuffle).toBe(true);
    expect(state.playing).toBe(false); // restored paused
    expect(other.decks[0]!.currentTime).toBe(42);
    expect(state.canUndo).toBe(false);

    other.engine.toggleShuffle(); // back to the original order
    expect(other.engine.getSnapshot().queue.map((t) => t.id)).toEqual(["a", "b", "c", "d"]);
  });

  it("restores an unshuffled queue and an empty one", () => {
    const { engine } = setup();
    engine.toggleShuffle(); // this browser was shuffling
    engine.restoreQueue({ tracks, originalOrder: null, index: 2, position: 0 });
    expect(engine.getSnapshot().shuffle).toBe(false); // follows the saved queue
    expect(engine.getSnapshot().current?.id).toBe("c");
    expect(engine.exportQueue().originalOrder).toBeNull();

    engine.restoreQueue({ tracks: [], originalOrder: null, index: -1, position: 0 });
    expect(engine.getSnapshot().current).toBeNull();
  });
});
