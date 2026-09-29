import { useEffect, useMemo, useRef, useState } from "react";

import { api, type SongLyrics } from "../api/native";
import { usePlayer } from "../player/PlayerContext";
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

const cache = new Map<string, SongLyrics>();

/** The lyrics of a song, kept for the session (except when LRCLIB could not be asked). */
export function loadLyrics(songId: string): Promise<SongLyrics> {
  const cached = cache.get(songId);
  if (cached) return Promise.resolve(cached);
  return api.getSongLyrics(songId).then((found) => {
    if (!found.unavailable) cache.set(songId, found); // else asked again next time
    return found;
  });
}

/**
 * The song's lyrics. Synced ones follow the song: the view glides so the current line
 * stays in the middle, lines fade with their distance to it, and (option) the current
 * line fills word by word with a small cursor.
 */
export function Lyrics({ songId, emptyText = "No lyrics found for this song." }: { songId: string; emptyText?: string }) {
  const { engine } = usePlayer();
  const { preferences, update } = usePreferences();
  const karaoke = preferences?.lyrics.karaoke ?? false;
  const [lyrics, setLyrics] = useState<SongLyrics | null>(cache.get(songId) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const scroller = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const wordElements = useRef<(HTMLSpanElement | null)[]>([]);
  const manualUntil = useRef(0);

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
      let index = -1;
      for (let i = 0; i < synced.length && (synced[i]?.startMs ?? 0) <= position + LEAD_MS; i++) index = i;
      if (index !== current) {
        current = index;
        setActive(index);
      }

      const box = scroller.current;
      const line = index >= 0 ? list.current?.children[index] : null;
      if (box && line instanceof HTMLElement && Date.now() >= manualUntil.current) {
        const target = line.offsetTop + line.offsetHeight / 2 - box.clientHeight / 2;
        const gap = target - box.scrollTop;
        if (Math.abs(gap) > 0.5) box.scrollTop += gap * (1 - Math.exp(-elapsed / SCROLL_EASING_MS));
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
          {lyrics.lines.map((line, index) => {
            const start = line.startMs;
            const distance = active < 0 ? 3 : Math.min(Math.abs(index - active), 3);
            const current = index === active;
            return (
              <li
                key={index}
                className={`lyrics__line${current ? " lyrics__line--active" : ""}`}
                data-distance={lyrics.synced ? distance : undefined}
              >
                {start !== null ? (
                  <button
                    className="lyrics__seek"
                    type="button"
                    title="Play from here"
                    onClick={() => {
                      manualUntil.current = 0;
                      engine.seek(start / 1000);
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
