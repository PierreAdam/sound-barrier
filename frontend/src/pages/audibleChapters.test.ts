import { describe, expect, it } from "vitest";

import type { AudibleChapters, SpokenFileDetails } from "../api/native";
import { applyAudible } from "./audibleChapters";

const audible: AudibleChapters = {
  asin: "B08V8B2CGV",
  runtimeMs: 100_000,
  introMs: 4000,
  outroMs: 5000,
  accurate: true,
  chapters: [
    { startMs: 0, lengthMs: 17_000, title: "Opening Credits" },
    { startMs: 17_000, lengthMs: 40_000, title: "Chapter 1" },
    { startMs: 57_000, lengthMs: 43_000, title: "Chapter 2" },
  ],
};

function file(chapters: number[] | null, durationMs = 96_000, canWriteChapters = true): SpokenFileDetails {
  return {
    id: `f${Math.random()}`,
    title: "001",
    fileName: "book.m4b",
    durationMs,
    canWriteChapters,
    chapters: chapters?.map((startMs, i) => ({ startMs, title: String(i + 1).padStart(3, "0") })) ?? [],
  };
}

describe("Audible's chapters on a book", () => {
  it("names a file's chapters in order, keeping its times", () => {
    const result = applyAudible([file([0, 16_000, 56_000])], audible);
    if ("error" in result) throw new Error(result.error);
    expect(result.files[0]!.chapters).toEqual([
      { startMs: 0, title: "Opening Credits" },
      { startMs: 16_000, title: "Chapter 1" },
      { startMs: 56_000, title: "Chapter 2" },
    ]);
  });

  it("replaces a file's chapters when the counts differ, without Audible's jingle", () => {
    const result = applyAudible([file([0, 50_000])], audible); // 96 s: 4 s shorter
    if ("error" in result) throw new Error(result.error);
    expect(result.files[0]!.chapters?.map((c) => c.startMs)).toEqual([0, 13_000, 53_000]);
    expect(result.message).toContain("4.0 s earlier");
  });

  it("names the files of a book in order", () => {
    const result = applyAudible([file(null), file(null), file(null)], audible);
    if ("error" in result) throw new Error(result.error);
    expect(result.files.map((f) => f.title)).toEqual(["Opening Credits", "Chapter 1", "Chapter 2"]);
  });

  it("says so when nothing matches", () => {
    const result = applyAudible([file(null), file(null)], audible);
    expect("error" in result && result.error).toContain("cannot be matched");
  });
});
