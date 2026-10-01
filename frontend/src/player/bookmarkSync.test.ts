import { describe, expect, it } from "vitest";

import type { SyncedBookmark } from "../api/native";
import { ago, bookOf, moveFor } from "./bookmarkSync";
import type { Track } from "./engine";

const file = (n: number): Track => ({ id: `f${n}`, title: `Part ${n}`, albumId: "book", spokenKind: "audiobooks", longForm: true });
const QUEUE = [file(1), file(2), file(3)];
const mark = (songId: string, positionMs: number): SyncedBookmark => ({
  songId,
  positionMs,
  changedAt: "2026-10-01T12:00:00.123456Z",
  source: "Chrome on Android",
});

describe("bookOf", () => {
  it("follows an audiobook as a whole, a podcast episode by itself", () => {
    expect(bookOf(file(1))).toBe(bookOf(file(3)));
    const episode: Track = { id: "e1", title: "Episode", albumId: "show", spokenKind: "podcasts", longForm: true };
    expect(bookOf(episode)).not.toBe(bookOf({ ...episode, id: "e2" }));
  });
});

describe("moveFor", () => {
  it("seeks in the current file, unless already there", () => {
    expect(moveFor(mark("f1", 600_000), file(1), 120, QUEUE, 0)).toEqual({ kind: "seek", seconds: 600 });
    expect(moveFor(mark("f1", 600_000), file(1), 599, QUEUE, 0)).toEqual({ kind: "none" });
  });

  it("goes to another queued file of the book, or takes it from the book", () => {
    expect(moveFor(mark("f3", 5000), file(1), 120, QUEUE, 0)).toEqual({ kind: "queue", index: 2, seconds: 5 });
    // An earlier file (the other device went back): found before the current one too.
    expect(moveFor(mark("f1", 5000), file(3), 120, QUEUE, 2)).toEqual({ kind: "queue", index: 0, seconds: 5 });
    expect(moveFor(mark("f9", 5000), file(1), 120, QUEUE, 0)).toEqual({ kind: "book", songId: "f9", seconds: 5 });
  });

  it("prefers the copy after the current track when a file is queued twice", () => {
    const twice = [file(2), file(1), file(2)];
    expect(moveFor(mark("f2", 1000), file(1), 0, twice, 1)).toEqual({ kind: "queue", index: 2, seconds: 1 });
  });
});

describe("ago", () => {
  const now = Date.parse("2026-10-01T12:00:00Z");
  it("tells how long ago, briefly", () => {
    expect(ago("2026-10-01T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-10-01T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-10-01T09:30:00Z", now)).toBe("2 h ago");
    expect(ago("not a date", now)).toBe("just now");
  });
});
