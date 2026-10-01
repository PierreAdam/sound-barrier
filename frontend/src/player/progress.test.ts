import { describe, expect, it } from "vitest";

import type { Track } from "./engine";
import { progressOf } from "./progress";

// One 3-hour file with 3 chapters inside it (one file of its book).
const M4B: Track = {
  id: "m4b",
  title: "The Book",
  durationSeconds: 10800,
  longForm: true,
  spokenKind: "audiobooks",
  chapters: [
    { start: 0, title: "One" },
    { start: 600, title: "Two" },
    { start: 4200, title: "Three" },
  ],
  book: { start: 0, duration: 10800, chapter: 0, chapters: 3 },
};

describe("progressOf", () => {
  it("covers the chapter playing, with the book under it", () => {
    const progress = progressOf(M4B, 1324, 10800, 1);
    expect([progress.start, progress.end]).toEqual([600, 4200]);
    expect(progress.time).toBe("12:04 / 1:00:00");
    expect([progress.chapter, progress.left]).toEqual(["Chapter 2 of 3", "2h38min left"]);
  });

  it("ends the last chapter at the end of the file", () => {
    const progress = progressOf(M4B, 5000, 10800, 2);
    expect([progress.start, progress.end]).toEqual([4200, 10800]);
    expect(progress.time).toBe("13:20 / 1:50:00");
  });

  it("numbers the chapters across the files of the book", () => {
    // A book of 40 one-chapter files: the 3rd file, 2 hours in.
    const file: Track = { id: "f3", title: "Part 3", durationSeconds: 1800, book: { start: 7200, duration: 72000, chapter: 2, chapters: 40 } };
    const progress = progressOf(file, 60, 1800, -1);
    expect([progress.start, progress.end]).toEqual([0, 1800]);
    expect(progress.time).toBe("1:00 / 30:00");
    expect([progress.chapter, progress.left]).toEqual(["Chapter 3 of 40", "17h59min left"]);
    // A later file of a book with chapters inside its files.
    const later: Track = { ...M4B, book: { start: 10800, duration: 30000, chapter: 3, chapters: 9 } };
    expect(progressOf(later, 4300, 10800, 2)).toMatchObject({ chapter: "Chapter 6 of 9", left: "4h08min left" });
  });

  it("shows the file alone when there is nothing more to tell", () => {
    const song: Track = { id: "s", title: "Song", durationSeconds: 200 };
    expect(progressOf(song, 65, 200, -1)).toEqual({ start: 0, end: 200, time: "1:05 / 3:20", chapter: null, left: null });
    // A book in one file without chapters: its time is the book's.
    const single: Track = { ...song, book: { start: 0, duration: 200, chapter: 0, chapters: 1 } };
    expect(progressOf(single, 65, 200, -1)).toMatchObject({ chapter: null, left: null });
    expect(progressOf(null, 0, 0, -1)).toEqual({ start: 0, end: 0, time: "0:00 / 0:00", chapter: null, left: null });
  });

  it("tells the time left in the episode for a podcast with chapters", () => {
    const episode: Track = { ...M4B, spokenKind: "podcasts", book: undefined };
    expect(progressOf(episode, 600, 10800, 1)).toMatchObject({ chapter: "Chapter 2 of 3", left: "2h50min left" });
    expect(progressOf(episode, 10500, 10800, 2).left).toBe("5min left");
  });

  it("stays in the chapter's span while the position catches up", () => {
    // The engine's chapter may lag a seek: the elapsed time is clamped to the span.
    const progress = progressOf(M4B, 590, 10800, 1);
    expect(progress.time).toBe("0:00 / 1:00:00");
  });
});
