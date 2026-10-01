import { describe, expect, it } from "vitest";

import { tracksFrom } from "./protocol";

describe("tracksFrom", () => {
  it("keeps a file's place in its book, only when complete", () => {
    const book = { start: 3600, duration: 7200, chapter: 3, chapters: 10 };
    const [kept, partial, wrong] = tracksFrom([
      { id: "a", title: "A", book },
      { id: "b", title: "B", book: { start: 0, duration: 1, chapter: 0 } },
      { id: "c", title: "C", book: { ...book, chapters: "10" } },
    ]);
    expect(kept?.book).toEqual(book);
    expect(partial?.book).toBeUndefined();
    expect(wrong?.book).toBeUndefined();
  });
});
