import { describe, expect, it } from "vitest";

import type { TranscriptBook } from "../../api/native";
import { listPage, PAGE_SIZE } from "./transcriptList";

function book(n: number, done: number, title = `Book ${n}`, author = "An Author"): TranscriptBook {
  return {
    id: String(n),
    kind: "audiobooks",
    title,
    author,
    coverArt: null,
    files: 2,
    durationMs: 1000,
    done,
    working: 0,
    failed: 0,
    pending: 2 - done,
  };
}

// 25 books: every third one fully transcribed (done 2 of 2).
const BOOKS = Array.from({ length: 25 }, (_, i) => book(i + 1, i % 3 === 0 ? 2 : i % 2));

describe("listPage", () => {
  it("shows only the books still missing text, by pages of 10", () => {
    const first = listPage(BOOKS, { query: "", withoutText: true, page: 1 });
    expect(first.matching).toBe(16);
    expect(first.pages).toBe(2);
    expect(first.books).toHaveLength(PAGE_SIZE);
    expect(first.books.every((b) => b.done < b.files)).toBe(true);
    expect(listPage(BOOKS, { query: "", withoutText: true, page: 2 }).books).toHaveLength(6);
  });

  it("shows them all without the filter", () => {
    const all = listPage(BOOKS, { query: "", withoutText: false, page: 3 });
    expect([all.matching, all.pages, all.page, all.books.length]).toEqual([25, 3, 3, 5]);
  });

  it("keeps the page in range (a book finished and left the list)", () => {
    expect(listPage(BOOKS, { query: "", withoutText: true, page: 9 }).page).toBe(2);
    expect(listPage([], { query: "", withoutText: true, page: 0 })).toEqual({ books: [], matching: 0, page: 1, pages: 1 });
  });

  it("searches the title and the author, every word, case and accents ignored", () => {
    const books = [book(1, 0, "Élégie pour un chat", "Jeanne Dupont"), book(2, 0, "Le Chien"), book(3, 2, "Chat perché")];
    expect(listPage(books, { query: "elegie", withoutText: true, page: 1 }).books.map((b) => b.id)).toEqual(["1"]);
    expect(listPage(books, { query: "chat dupont", withoutText: true, page: 1 }).books.map((b) => b.id)).toEqual(["1"]);
    // "Chat perché" has all its text: found only without the filter.
    expect(listPage(books, { query: "CHAT", withoutText: true, page: 1 }).matching).toBe(1);
    expect(listPage(books, { query: "  CHAT ", withoutText: false, page: 1 }).matching).toBe(2);
  });
});
