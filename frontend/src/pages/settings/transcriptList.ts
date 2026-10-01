// Settings → Transcripts: the podcasts and audiobooks list, searched, filtered and paged
// here (the overview has them all, refreshed every few seconds).

import type { TranscriptBook } from "../../api/native";

export const PAGE_SIZE = 10;

export interface ListOptions {
  query: string;
  withoutText: boolean; // only those not fully transcribed (in progress and failed too)
  page: number; // 1-based, kept in range
}

export interface ListPage {
  books: TranscriptBook[]; // of this page
  matching: number;
  page: number;
  pages: number; // at least 1
}

/** Case and accents ignored: "Elegie" finds "Élégie". */
function normalize(value: string): string {
  return value.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Not every file has its text yet. */
export function withoutText(book: TranscriptBook): boolean {
  return book.done < book.files;
}

export function listPage(books: readonly TranscriptBook[], options: ListOptions): ListPage {
  const words = normalize(options.query).split(/\s+/).filter(Boolean);
  const found = books.filter((book) => {
    if (options.withoutText && !withoutText(book)) return false;
    const text = normalize(`${book.title} ${book.author}`);
    return words.every((word) => text.includes(word));
  });
  const pages = Math.max(1, Math.ceil(found.length / PAGE_SIZE));
  const page = Math.min(Math.max(1, Math.floor(options.page)), pages);
  return {
    books: found.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    matching: found.length,
    page,
    pages,
  };
}
