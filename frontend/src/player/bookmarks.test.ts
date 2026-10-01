import { describe, expect, it } from "vitest";

import { createBookmarkKeeper } from "./bookmarks";
import type { PlayerSnapshot, Track } from "./engine";

const BOOK: Track = { id: "book", title: "Chapter 1", durationSeconds: 3600, longForm: true };
const SONG: Track = { id: "song", title: "A song", durationSeconds: 200 };

function snapshot(track: Track | null, key: number, position: number, playing: boolean): PlayerSnapshot {
  return {
    current: track,
    index: track ? 0 : -1,
    keys: [key],
    position,
    duration: track?.durationSeconds ?? 0,
    playing,
  } as unknown as PlayerSnapshot;
}

function keeper() {
  const calls: string[] = [];
  const kept = createBookmarkKeeper({
    save: (track, seconds, keepalive) => calls.push(`save ${track.id} ${seconds}${keepalive ? " keepalive" : ""}`),
    remove: (track) => calls.push(`remove ${track.id}`),
    resume: (track) => calls.push(`resume ${track.id}`),
  });
  return { calls, kept };
}

/** With `started` too (the web player follows bookmarks across devices). */
function followingKeeper() {
  const calls: string[] = [];
  const kept = createBookmarkKeeper({
    save: (track, seconds) => calls.push(`save ${track.id} ${seconds}`),
    remove: (track) => calls.push(`remove ${track.id}`),
    resume: (track) => calls.push(`resume ${track.id}`),
    started: (track) => calls.push(`started ${track.id}`),
  });
  return { calls, kept };
}

describe("bookmark keeper", () => {
  it("resumes long-form tracks started from their beginning, not music", () => {
    const { calls, kept } = keeper();
    kept.update(snapshot(SONG, 1, 0, true));
    kept.update(snapshot(BOOK, 2, 0, true));
    expect(calls).toEqual(["resume book"]);
    // A restored queue (already far in the track): no resume.
    const other = keeper();
    other.kept.update(snapshot(BOOK, 1, 600, false));
    expect(other.calls).toEqual([]);
    // Started at a chosen chapter, even the first: no resume either.
    const chosen = keeper();
    chosen.kept.update({ ...snapshot(BOOK, 1, 0, true), positioned: true });
    expect(chosen.calls).toEqual([]);
  });

  it("saves while playing, on pause and when leaving", () => {
    const { calls, kept } = keeper();
    kept.update(snapshot(BOOK, 1, 0, true));
    kept.update(snapshot(BOOK, 1, 10, true));
    kept.update(snapshot(BOOK, 1, 16, true)); // 15 s since the start
    kept.update(snapshot(BOOK, 1, 20, true));
    kept.update(snapshot(BOOK, 1, 21, false)); // paused
    kept.leave();
    expect(calls).toEqual(["resume book", "save book 16", "save book 21", "save book 21 keepalive"]);
  });

  it("removes the bookmark once listened to the end, and never bookmarks music", () => {
    const { calls, kept } = keeper();
    kept.update(snapshot(BOOK, 1, 3580, true));
    kept.update(snapshot(SONG, 2, 0, true)); // the book ended, the next track plays
    kept.update(snapshot(SONG, 2, 100, true));
    kept.update(snapshot(SONG, 2, 120, false));
    expect(calls).toEqual(["remove book"]);
  });
});

describe("bookmark keeper, followed across devices", () => {
  it("tells when a long-form track becomes current, however it started, before resuming", () => {
    const { calls, kept } = followingKeeper();
    kept.update(snapshot(SONG, 1, 0, true));
    kept.update(snapshot(BOOK, 2, 0, true));
    kept.update(snapshot(BOOK, 3, 600, false)); // restored far in
    kept.update({ ...snapshot(BOOK, 4, 0, true), positioned: true }); // a chosen chapter
    // (The restored one is saved as it leaves, as before.)
    expect(calls).toEqual(["started book", "resume book", "started book", "save book 600", "started book"]);
  });

  it("does not save what it had once moved to another device's position", () => {
    const { calls, kept } = followingKeeper();
    kept.update(snapshot(BOOK, 1, 0, true));
    kept.update(snapshot(BOOK, 1, 120, true)); // saved at 120
    kept.forget(); // moved (paused) to 3000 s, where another device left it
    kept.update(snapshot(BOOK, 1, 3000, false)); // not "paused at 120": nothing saved
    kept.leave(); // from where it moved to
    expect(calls).toEqual(["started book", "resume book", "save book 120", "started book", "save book 3000"]);
  });
});
