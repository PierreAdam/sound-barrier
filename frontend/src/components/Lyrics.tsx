import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { api, type SongLyrics } from "../api/native";
import { usePlayerEngine } from "../player/PlayerContext";
import { keepFocus } from "../player/shortcuts";
import { usePreferences } from "../preferences/PreferencesContext";

// A synced line shows a little before its time (it takes a moment to read).
const LEAD_MS = 250;
// After the user scrolls the lyrics, they are not followed again for a while.
const MANUAL_SCROLL_MS = 4000;
// The scroll glides to the current line: the larger, the slower (ms, exponential easing).
const SCROLL_EASING_MS = 220;
// Karaoke sweep without word timing: a line is "sung" at about this pace at most, so a
// long instrumental gap after it does not make its sweep crawl.
const MS_PER_CHARACTER = 85;
const MIN_LINE_MS = 1200;
const LAST_LINE_MS = 5000;
// Long texts (an audiobook's transcript: 10,000+ lines) are not all in the page: only a
// window of lines around the current one, moved by this many lines at a time.
export const WINDOW_STEP = 100;
// Texts kept in memory (a transcript with word timings is big).
const CACHE_SIZE = 4;
const SOURCES: Record<string, string> = {
  lrc: "a .lrc file",
  embedded: "the file's tags",
  transcript: "a transcript (speech to text)",
  lrclib: "LRCLIB",
};

type Lines = SongLyrics["lines"];

interface TimedWord {
  text: string;
  start: number; // ms
  end: number;
}

/** The words of a synced line with their times: real ones when the lyrics have them, else
 * spread over the line in proportion to their length. */
function timedWords(lines: Lines, index: number): TimedWord[] {
  const line = lines[index];
  const lineStart = line?.startMs;
  if (!line || lineStart === null || lineStart === undefined) return [];
  const next = lines[index + 1]?.startMs ?? lineStart + LAST_LINE_MS;
  const sung = Math.min(next - lineStart, Math.max(MIN_LINE_MS, line.text.length * MS_PER_CHARACTER));
  if (line.words?.length) {
    return line.words.map((word, i) => {
      const following = line.words?.[i + 1]?.startMs;
      const end = following ?? Math.min(next, word.startMs + Math.max(300, word.text.length * MS_PER_CHARACTER));
      return { text: word.text, start: word.startMs, end: Math.max(end, word.startMs + 1) };
    });
  }
  const pieces = line.text.match(/\S+\s*/g) ?? [];
  const total = pieces.reduce((sum, piece) => sum + piece.trim().length, 0) || 1;
  let done = 0;
  return pieces.map((piece) => {
    const start = lineStart + (sung * done) / total;
    done += piece.trim().length;
    return { text: piece, start, end: lineStart + (sung * done) / total };
  });
}

/** The synced line playing at `positionMs` (-1 before the first): the last one started. */
export function lineAt(lines: Lines, positionMs: number): number {
  let low = 0;
  let high = lines.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if ((lines[middle]?.startMs ?? 0) <= positionMs) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

/** The lines in the page: [start, end). Around the current line, from WINDOW_STEP lines
 * before its block to two blocks after; a short text is whole. */
export function lineWindow(count: number, active: number): [number, number] {
  const base = active < 0 ? 0 : Math.floor(active / WINDOW_STEP) * WINDOW_STEP;
  return [Math.max(0, base - WINDOW_STEP), Math.min(count, base + 2 * WINDOW_STEP)];
}

// The last texts asked for, the most recent last (a Map keeps the insertion order).
const cache = new Map<string, SongLyrics>();

function remember(songId: string, lyrics: SongLyrics): void {
  cache.delete(songId);
  cache.set(songId, lyrics);
  while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value as string);
}

/** The lyrics of a song, kept while they are among the last few asked for (except when
 * LRCLIB could not be asked). */
export function loadLyrics(songId: string): Promise<SongLyrics> {
  const cached = cache.get(songId);
  if (cached) {
    remember(songId, cached);
    return Promise.resolve(cached);
  }
  return api.getSongLyrics(songId).then((found) => {
    if (!found.unavailable) remember(songId, found); // else asked again next time
    return found;
  });
}

/**
 * The song's lyrics. Synced ones follow the song: the view glides so the current line
 * stays in the middle, lines fade with their distance to it, and (option) the current
 * line fills word by word with a small cursor.
 *
 * The position is read every animation frame, from the engine: the component renders
 * only when the current line changes, not at every player tick. Long synced texts only
 * have a window of lines in the page (lineWindow).
 */
export function Lyrics({ songId, emptyText = "No lyrics found for this song." }: { songId: string; emptyText?: string }) {
  const engine = usePlayerEngine();
  const { preferences, update } = usePreferences();
  const karaoke = preferences?.lyrics.karaoke ?? false;
  const [lyrics, setLyrics] = useState<SongLyrics | null>(cache.get(songId) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const scroller = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const wordElements = useRef<(HTMLSpanElement | null)[]>([]);
  const manualUntil = useRef(0);
  // Where the current line was (offsetTop), to keep it in place when the window moves.
  const activeTop = useRef<number | null>(null);
  // The lyrics the view was placed for: new ones (the next song) are placed at once, not
  // glided to from where the previous song's were (the same box: its lines flew by).
  const placedFor = useRef<Lines | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLyrics(cache.get(songId) ?? null);
    setError(null);
    setActive(-1);
    if (cache.has(songId)) return;
    loadLyrics(songId)
      .then((found) => !cancelled && setLyrics(found))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [songId]);

  const synced = lyrics?.synced ? lyrics.lines : null;
  // Real word timing (else the karaoke fill is estimated from the words' lengths).
  const wordSynced = synced?.some((line) => line.words?.length) ?? false;
  const words = useMemo(() => (synced && karaoke && active >= 0 ? timedWords(synced, active) : []), [synced, karaoke, active]);
  const [start, end] = synced ? lineWindow(synced.length, active) : [0, lyrics?.lines.length ?? 0];
  const startRef = useRef(start);
  startRef.current = start;

  // The window moved: lines went out above the current one. Scroll by as much, so what
  // is on screen does not jump.
  useLayoutEffect(() => {
    const box = scroller.current;
    const line = active >= 0 ? list.current?.children[active - start] : null;
    if (box && line instanceof HTMLElement && activeTop.current !== null) {
      box.scrollTop += line.offsetTop - activeTop.current;
    }
    activeTop.current = null;
  }, [start]); // only when the window moves

  // Every frame: the current line, the scroll gliding to it, and the karaoke fill.
  useEffect(() => {
    if (!synced) return;
    let frame = 0;
    let last = performance.now();
    let current = -1;
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      const elapsed = Math.min(now - last, 100);
      last = now;
      const position = engine.currentTime * 1000;
      const index = lineAt(synced, position + LEAD_MS);
      const box = scroller.current;
      if (index !== current) {
        // Where the new current line is now (still in the page: the window moves by
        // blocks): if the window moves with it, the view stays put.
        const coming = index >= 0 ? list.current?.children[index - startRef.current] : null;
        activeTop.current = coming instanceof HTMLElement ? coming.offsetTop : null;
        current = index;
        setActive(index);
      }

      const line = index >= 0 ? list.current?.children[index - startRef.current] : null;
      const target = line instanceof HTMLElement && box ? line.offsetTop + line.offsetHeight / 2 - box.clientHeight / 2 : null;
      if (box && placedFor.current !== synced) {
        // New lyrics: at the current line, or at the top before the first one.
        placedFor.current = synced;
        box.scrollTop = target ?? 0;
      } else if (box && target !== null && Date.now() >= manualUntil.current) {
        const gap = target - box.scrollTop;
        const step = gap * (1 - Math.exp(-elapsed / SCROLL_EASING_MS));
        // At least a pixel: the browser rounds the scroll to device pixels, smaller steps
        // were lost and the glide stopped a few pixels short of the middle.
        if (Math.abs(gap) > 0.5) box.scrollTop += Math.abs(step) < 1 ? Math.sign(gap) * Math.min(Math.abs(gap), 1) : step;
      }

      wordElements.current.forEach((element, i) => {
        const word = words[i];
        if (!element || !word) return;
        const fill = Math.min(1, Math.max(0, (position - word.start) / (word.end - word.start)));
        element.style.setProperty("--fill", fill.toFixed(3));
        element.classList.toggle("lyrics__word--current", fill > 0 && fill < 1);
      });
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [synced, engine, words]);

  const userScrolled = () => {
    manualUntil.current = Date.now() + MANUAL_SCROLL_MS;
  };
  const toggleKaraoke = () =>
    update((current) => ({ ...current, lyrics: { ...current.lyrics, karaoke: !current.lyrics.karaoke } }));

  if (error) return <p className="text-error now-playing__lyrics">Lyrics: {error}</p>;
  if (!lyrics) return <p className="text-muted now-playing__lyrics">Looking for the lyrics…</p>;
  if (lyrics.unavailable) {
    return <p className="text-muted now-playing__lyrics">The lyrics service (LRCLIB) is not reachable right now: try again later.</p>;
  }
  if (!lyrics.found || (!lyrics.lines.length && !lyrics.instrumental)) {
    return <p className="text-muted now-playing__lyrics">{emptyText}</p>;
  }
  if (lyrics.instrumental && !lyrics.lines.length) {
    return <p className="text-muted now-playing__lyrics">Instrumental.</p>;
  }

  return (
    <div className="now-playing__lyrics-panel">
      {lyrics.synced && (
        <div className="now-playing__karaoke">
          <label className="checkbox" title="The current line fills word by word">
            <input type="checkbox" checked={karaoke} disabled={!preferences} onChange={toggleKaraoke} />
            Karaoke
          </label>
          {wordSynced ? (
            <span className="badge" title="These lyrics give the time of each word: the fill follows the singing">
              Word by word
            </span>
          ) : (
            <span
              className="badge badge--muted"
              title="These lyrics only give the time of each line: the words are spread over it by their length"
            >
              Estimated
            </span>
          )}
        </div>
      )}
      {/* Clicking a line does not focus it: Space still plays / pauses. */}
      <div
        ref={scroller}
        className="now-playing__lyrics"
        onWheel={userScrolled}
        onTouchMove={userScrolled}
        onMouseDown={keepFocus}
      >
        <ol ref={list} className={`lyrics${lyrics.synced ? " lyrics--synced" : ""}`}>
          {lyrics.lines.slice(start, end).map((line, offset) => {
            const index = start + offset;
            const lineStart = line.startMs;
            const distance = active < 0 ? 3 : Math.min(Math.abs(index - active), 3);
            const current = index === active;
            return (
              <li
                key={index}
                className={`lyrics__line${current ? " lyrics__line--active" : ""}`}
                data-distance={lyrics.synced ? distance : undefined}
              >
                {lineStart !== null ? (
                  <button
                    className="lyrics__seek"
                    type="button"
                    title="Play from here"
                    onClick={() => {
                      manualUntil.current = 0;
                      engine.seek(lineStart / 1000);
                    }}
                  >
                    {current && words.length
                      ? words.map((word, i) => (
                          <span
                            key={i}
                            ref={(element) => {
                              wordElements.current[i] = element;
                            }}
                            className="lyrics__word"
                          >
                            {word.text}
                          </span>
                        ))
                      : line.text || "♪"}
                  </button>
                ) : (
                  line.text || " "
                )}
              </li>
            );
          })}
        </ol>
        <p className="credit">
          Lyrics from{" "}
          {lyrics.source === "lrclib" ? (
            <a className="link" href="https://lrclib.net" target="_blank" rel="noreferrer">
              LRCLIB
            </a>
          ) : (
            (lyrics.source && SOURCES[lyrics.source]) ?? "?"
          )}
          .
        </p>
      </div>
    </div>
  );
}
