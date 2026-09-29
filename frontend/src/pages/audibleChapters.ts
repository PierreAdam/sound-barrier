// "Look up on Audible" (Edit details): a book's chapter titles from Audible, fitted to its
// files. Nothing is saved until the admin saves the form.

import type { AudibleChapters, SpokenFileDetails } from "../api/native";

export type Applied = { files: SpokenFileDetails[]; message: string } | { error: string };

/** Audible times its chapters in its own file, which starts with a jingle a copy of the
 * book may not have: the shift that lines them up with ours (0 to the jingle's length). */
function shiftOf(audible: AudibleChapters, durationMs: number): number {
  return Math.min(Math.max(audible.runtimeMs - durationMs, 0), audible.introMs);
}

export function applyAudible(files: SpokenFileDetails[], audible: AudibleChapters): Applied {
  const titles = audible.chapters.map((c) => c.title);
  const count = titles.length;
  const soft = files.reduce((sum, f) => sum + (f.chapters?.length ?? 0), 0);

  if (files.length === 1) {
    const file = files[0]!;
    const chapters = file.chapters ?? [];
    if (chapters.length === count) {
      return {
        files: [{ ...file, chapters: chapters.map((c, i) => ({ ...c, title: titles[i]! })) }],
        message: `${count} chapter titles from Audible, in order (the file's times are kept). Check them, then save.`,
      };
    }
    if (!file.canWriteChapters) {
      return { error: `Audible has ${count} chapters, the file ${chapters.length}: its chapters cannot be replaced (MP3 and M4A / M4B only).` };
    }
    const shift = shiftOf(audible, file.durationMs);
    const replaced = audible.chapters
      .map((c, i) => ({ startMs: i === 0 ? 0 : Math.max(0, c.startMs - shift), title: c.title }))
      .filter((c) => c.startMs < file.durationMs);
    return {
      files: [{ ...file, chapters: replaced }],
      message:
        `The file's ${chapters.length || "no"} chapters replaced by Audible's ${replaced.length}` +
        (shift ? `, ${(shift / 1000).toFixed(1)} s earlier (Audible's jingle)` : "") +
        ". Check them, then save.",
    };
  }

  if (soft === 0 && files.length === count) {
    return {
      files: files.map((f, i) => ({ ...f, title: titles[i]! })),
      message: `${count} file titles from Audible's chapters, in order. Check them, then save.`,
    };
  }
  if (soft === count) {
    let next = 0;
    return {
      files: files.map((f) => ({ ...f, chapters: (f.chapters ?? []).map((c) => ({ ...c, title: titles[next++]! })) })),
      message: `${count} chapter titles from Audible, in order across the files. Check them, then save.`,
    };
  }
  return {
    error:
      `Audible has ${count} chapters; this book has ${files.length} files` +
      (soft ? ` and ${soft} chapters inside them` : "") +
      ": they cannot be matched automatically. Edit the titles by hand.",
  };
}
