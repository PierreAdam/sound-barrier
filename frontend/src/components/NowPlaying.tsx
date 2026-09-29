import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { api, type SongLyrics } from "../api/native";
import { usePlayer } from "../player/PlayerContext";
import { CoverArt } from "./CoverArt";
import { Visualizer } from "./Visualizer";

// A synced line shows a little before its time (it takes a moment to read).
const LEAD_MS = 250;
const TICK_MS = 100;
// After the user scrolls the lyrics, they are not scrolled back to the current line for a while.
const MANUAL_SCROLL_MS = 4000;
const SOURCES: Record<string, string> = { lrc: "a .lrc file", embedded: "the file's tags", lrclib: "LRCLIB" };

interface NowPlayingValue {
  open: boolean;
  toggle(): void;
  close(): void;
}

const NowPlayingContext = createContext<NowPlayingValue | null>(null);

export function NowPlayingProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((value) => !value), []);
  const close = useCallback(() => setOpen(false), []);
  return <NowPlayingContext.Provider value={{ open, toggle, close }}>{children}</NowPlayingContext.Provider>;
}

export function useNowPlaying(): NowPlayingValue {
  const value = useContext(NowPlayingContext);
  if (!value) throw new Error("useNowPlaying must be used inside <NowPlayingProvider>");
  return value;
}

/** Big cover, visualizer and lyrics (synced ones follow the song) of the current track. */
export function NowPlaying() {
  const { open, close } = useNowPlaying();
  const { state } = usePlayer();
  const location = useLocation();
  const current = state.current;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);
  useEffect(close, [location.pathname, close]);

  if (!open) return null;
  return (
    <section className="now-playing" aria-label="Now playing">
      <button className="icon-button now-playing__close" type="button" aria-label="Close" onClick={close}>
        ×
      </button>
      {current ? (
        <div className="now-playing__body">
          <div className="now-playing__side">
            <CoverArt id={current.coverArt} size={420} className="now-playing__cover" alt="" />
            <div className="now-playing__meta">
              <h2 className="now-playing__title">{current.title}</h2>
              <p className="now-playing__artist">
                {current.artistId ? <Link to={`/artists/${current.artistId}`}>{current.artist}</Link> : current.artist}
                {current.album && (
                  <>
                    {" · "}
                    {current.albumId ? <Link to={`/albums/${current.albumId}`}>{current.album}</Link> : current.album}
                  </>
                )}
              </p>
            </div>
            <Visualizer className="now-playing__visualizer" bars={40} />
          </div>
          <Lyrics songId={current.id} />
        </div>
      ) : (
        <p className="text-muted now-playing__empty">Nothing playing.</p>
      )}
    </section>
  );
}

const cache = new Map<string, SongLyrics>();

function Lyrics({ songId }: { songId: string }) {
  const { engine } = usePlayer();
  const [lyrics, setLyrics] = useState<SongLyrics | null>(cache.get(songId) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const list = useRef<HTMLOListElement>(null);
  const manualUntil = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLyrics(cache.get(songId) ?? null);
    setError(null);
    setActive(-1);
    if (cache.has(songId)) return;
    api
      .getSongLyrics(songId)
      .then((found) => {
        if (!found.unavailable) cache.set(songId, found); // else asked again next time
        if (!cancelled) setLyrics(found);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [songId]);

  // Synced: the line being sung, from the player's exact position.
  const synced = lyrics?.synced ? lyrics.lines : null;
  useEffect(() => {
    if (!synced) return;
    const timer = setInterval(() => {
      const now = engine.currentTime * 1000 + LEAD_MS;
      let index = -1;
      for (let i = 0; i < synced.length && (synced[i]?.startMs ?? 0) <= now; i++) index = i;
      setActive(index);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [synced, engine]);

  useEffect(() => {
    if (active < 0 || Date.now() < manualUntil.current) return;
    const line = list.current?.children[active];
    if (line instanceof HTMLElement) line.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  const userScrolled = () => {
    manualUntil.current = Date.now() + MANUAL_SCROLL_MS;
  };

  if (error) return <p className="text-error now-playing__lyrics">Lyrics: {error}</p>;
  if (!lyrics) return <p className="text-muted now-playing__lyrics">Looking for the lyrics…</p>;
  if (lyrics.unavailable) {
    return <p className="text-muted now-playing__lyrics">The lyrics service (LRCLIB) is not reachable right now: try again later.</p>;
  }
  if (!lyrics.found || (!lyrics.lines.length && !lyrics.instrumental)) {
    return <p className="text-muted now-playing__lyrics">No lyrics found for this song.</p>;
  }
  if (lyrics.instrumental && !lyrics.lines.length) {
    return <p className="text-muted now-playing__lyrics">Instrumental.</p>;
  }
  return (
    <div className="now-playing__lyrics" onWheel={userScrolled} onTouchMove={userScrolled}>
      <ol ref={list} className={`lyrics${lyrics.synced ? " lyrics--synced" : ""}`}>
        {lyrics.lines.map((line, index) => {
          const start = line.startMs;
          const classes = ["lyrics__line", index === active && "lyrics__line--active", index < active && "lyrics__line--past"];
          return (
            <li key={index} className={classes.filter(Boolean).join(" ")}>
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
                  {line.text || "♪"}
                </button>
              ) : (
                line.text || " "
              )}
            </li>
          );
        })}
      </ol>
      <p className="credit">Lyrics from {lyrics.source ? SOURCES[lyrics.source] : "?"}.</p>
    </div>
  );
}
