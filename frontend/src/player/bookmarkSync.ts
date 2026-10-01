// Audiobooks and podcasts followed across devices (useBookmarks in PlayerContext.tsx): when
// another device moved the bookmark, where this player must go. Pure logic.

import type { SyncedBookmark } from "../api/native";
import type { Track } from "./engine";

/** Checked this often while an audiobook / podcast is the current track (also when hidden:
 * it may be playing in the background), and at once when the tab is back in front. */
export const CHECK_EVERY_MS = 30_000;
/** Closer than this to the bookmark: already there (the last save's rounding). */
const SAME_PLACE_S = 2;

/** What a bookmark is followed for: the whole book (its files), or the episode. */
export function bookOf(track: Track): string {
  return track.spokenKind === "audiobooks" && track.albumId ? `book:${track.albumId}` : `file:${track.id}`;
}

export type Move =
  | { kind: "none" } // already there
  | { kind: "seek"; seconds: number } // in the current file
  | { kind: "queue"; index: number; seconds: number } // another file, in the queue
  | { kind: "book"; songId: string; seconds: number }; // another file, not queued: from the book

/** Where to go for `bookmark`, from `current` (at `position`) in this `queue`. */
export function moveFor(bookmark: SyncedBookmark, current: Track, position: number, queue: readonly Track[], index: number): Move {
  const seconds = bookmark.positionMs / 1000;
  if (bookmark.songId === current.id) {
    return Math.abs(seconds - position) < SAME_PLACE_S ? { kind: "none" } : { kind: "seek", seconds };
  }
  // The queued one closest after the current track (the same file may be queued twice).
  const after = queue.findIndex((track, i) => i > index && track.id === bookmark.songId);
  const found = after >= 0 ? after : queue.findIndex((track) => track.id === bookmark.songId);
  return found >= 0 ? { kind: "queue", index: found, seconds } : { kind: "book", songId: bookmark.songId, seconds };
}

/** "just now", "5 min ago", "3 h ago", else the date. */
export function ago(iso: string, now = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (!Number.isFinite(minutes) || minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return new Date(iso).toLocaleDateString();
}
