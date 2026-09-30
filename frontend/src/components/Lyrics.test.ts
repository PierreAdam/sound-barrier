import { describe, expect, it } from "vitest";

import { lineAt, lineWindow, WINDOW_STEP } from "./Lyrics";

const lines = [0, 1000, 2500, 2500, 9000].map((startMs, i) => ({ startMs, text: `line ${i}`, words: null }));

describe("long lyrics", () => {
  it("finds the line playing by bisection", () => {
    expect(lineAt(lines, -1)).toBe(-1);
    expect(lineAt(lines, 0)).toBe(0);
    expect(lineAt(lines, 999)).toBe(0);
    expect(lineAt(lines, 2500)).toBe(3); // the last one started
    expect(lineAt(lines, 100_000)).toBe(4);
    expect(lineAt([], 5)).toBe(-1);
  });

  it("puts only a window of a long text in the page, moving by blocks", () => {
    expect(lineWindow(40, 12)).toEqual([0, 40]); // a song: whole
    expect(lineWindow(12770, -1)).toEqual([0, 2 * WINDOW_STEP]);
    expect(lineWindow(12770, 150)).toEqual([0, 300]);
    expect(lineWindow(12770, 5234)).toEqual([5100, 5400]); // the current line in the middle block
    expect(lineWindow(12770, 12769)).toEqual([12600, 12770]);
  });
});
