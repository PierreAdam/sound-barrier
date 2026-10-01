// What the progress line and the time show: the chapter playing when the file has chapters
// inside it (a 13-hour M4B is unreadable as one line), and where it is in the whole book.
// From the track and the player's position only, so a remote (and the TV) show it alike.

import { formatTime } from "../format";
import type { Track } from "./engine";

export interface Progress {
  /** The span the progress line covers, in seconds of the file: a chapter, or the file. */
  start: number;
  end: number;
  /** "12:04 / 31:10", in that span. */
  time: string;
  /** Under the time (null: nothing to add): e.g. "Chapter 22 of 50", then "7h58min left" (in the book). */
  chapter: string | null;
  left: string | null;
}

/**
 * The progress at `position` seconds into the current file (`duration` long), whose
 * chapter playing is `chapter` (the engine's, -1: none).
 */
export function progressOf(track: Track | null, position: number, duration: number, chapter: number): Progress {
  const chapters = track?.chapters;
  const inChapter = chapters !== undefined && chapter >= 0 && chapter < chapters.length;
  const start = inChapter ? (chapters[chapter]?.start ?? 0) : 0;
  const nextStart = inChapter ? chapters[chapter + 1]?.start : undefined;
  const end = nextStart !== undefined && nextStart > start ? nextStart : Math.max(duration, start);
  const elapsed = Math.min(Math.max(position - start, 0), end - start);
  return {
    start,
    end,
    time: `${formatTime(elapsed)} / ${formatTime(end - start)}`,
    ...contextOf(track, position, duration, inChapter ? chapter : 0),
  };
}

function contextOf(
  track: Track | null,
  position: number,
  duration: number,
  chapter: number,
): Pick<Progress, "chapter" | "left"> {
  const book = track?.book;
  const chapters = track?.chapters?.length ?? 0;
  if (book && book.chapters > 1) {
    const number = Math.min(book.chapter + Math.min(chapter, Math.max(chapters - 1, 0)) + 1, book.chapters);
    return {
      chapter: `Chapter ${number} of ${book.chapters}`,
      left: `${shortDuration(book.duration - book.start - position)} left`,
    };
  }
  // Chapters inside a file that is not part of a known book (a podcast episode): the file.
  if (chapters > 1) {
    return { chapter: `Chapter ${chapter + 1} of ${chapters}`, left: `${shortDuration(duration - position)} left` };
  }
  return { chapter: null, left: null };
}

/** 29940 -> "8h19min", 300 -> "5min" (the player bar has little room). */
function shortDuration(seconds: number): string {
  const minutes = Math.round(Math.max(seconds, 0) / 60);
  return minutes < 60 ? `${minutes}min` : `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}min`;
}
