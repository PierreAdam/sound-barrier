import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { formatTime } from "../format";
import type { Track } from "../player/engine";
import { usePlayer } from "../player/PlayerContext";
import { albumUrl, artistUrl } from "../player/tracks";
import { CoverArt } from "./CoverArt";
import { FullScreenIcon, RemoveIcon } from "./Icons";
import { loadLyrics, Lyrics } from "./Lyrics";
import { Visualizer } from "./Visualizer";

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

/**
 * The lyrics alone, over the whole screen (any layout). The browser's own full screen too
 * where a page may ask for it (desktops, Android; not iPhone: there, the page only).
 */
function useFullScreen(open: boolean) {
  const [full, setFull] = useState(false);

  const exit = useCallback(() => {
    setFull(false);
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
  }, []);

  const toggle = useCallback(() => {
    if (full) {
      exit();
      return;
    }
    setFull(true);
    const root = document.documentElement;
    if (root.requestFullscreen && !document.fullscreenElement) {
      void root.requestFullscreen({ navigationUI: "hide" }).catch(() => undefined);
    }
  }, [full, exit]);

  // The browser's full screen left (back gesture, Escape): this one too.
  useEffect(() => {
    const onChange = () => !document.fullscreenElement && setFull(false);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    if (!open) exit();
  }, [open, exit]);

  return { full, toggle, exit };
}

/** Big cover, visualizer and lyrics (synced ones follow the song) of the current track. */
export function NowPlaying() {
  const { open, close } = useNowPlaying();
  const fullScreen = useFullScreen(open);
  const { state } = usePlayer();
  const location = useLocation();
  const current = state.current;
  const artistLink = current ? artistUrl(current) : undefined;
  const albumLink = current ? albumUrl(current) : undefined;

  useEffect(() => {
    if (!open) return;
    // Escape leaves the full screen first, then Now playing.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (fullScreen.full) fullScreen.exit();
      else close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close, fullScreen.full, fullScreen.exit]);
  useEffect(close, [location.pathname, close]);

  if (!open) return null;
  return (
    <section className={`now-playing${fullScreen.full ? " now-playing--full" : ""}`} aria-label="Now playing">
      {current && (
        <button
          className={`icon-button now-playing__full-screen${fullScreen.full ? " icon-button--active" : ""}`}
          type="button"
          aria-label={fullScreen.full ? "Exit full screen" : "Lyrics in full screen"}
          aria-pressed={fullScreen.full}
          title={fullScreen.full ? "Exit full screen" : "Lyrics in full screen"}
          onClick={fullScreen.toggle}
        >
          <FullScreenIcon exit={fullScreen.full} />
        </button>
      )}
      {/* An icon like its neighbour's (a "×" character sat at its font's height, not theirs). */}
      <button className="icon-button now-playing__close" type="button" aria-label="Close" title="Close" onClick={close}>
        <RemoveIcon />
      </button>
      {current ? (
        <div className="now-playing__body">
          <div className="now-playing__side">
            <CoverArt id={current.coverArt} size={420} className="now-playing__cover" alt="" />
            <div className="now-playing__meta">
              <h2 className="now-playing__title">{current.title}</h2>
              <p className="now-playing__artist">
                {artistLink ? <Link to={artistLink}>{current.artist}</Link> : current.artist}
                {current.album && current.album !== current.title && (
                  <>
                    {" · "}
                    {albumLink ? <Link to={albumLink}>{current.album}</Link> : current.album}
                  </>
                )}
              </p>
            </div>
            <Visualizer className="now-playing__visualizer" bars={40} />
          </div>
          {current.longForm ? <Spoken track={current} /> : <Lyrics songId={current.id} />}
        </div>
      ) : (
        <p className="text-muted now-playing__empty">Nothing playing.</p>
      )}
    </section>
  );
}

/**
 * Podcasts and audiobooks: their text (a transcript, Settings → Transcripts) and the chapters
 * inside the file, with a switch when there are both. Chapters first when there is no text.
 */
function Spoken({ track }: { track: Track }) {
  const [hasText, setHasText] = useState<boolean | null>(null);
  const [view, setView] = useState<"text" | "chapters">("text");
  const hasChapters = Boolean(track.chapters?.length);

  useEffect(() => {
    let current = true;
    setHasText(null);
    setView("text");
    loadLyrics(track.id)
      .then((found) => current && setHasText(found.found && found.lines.length > 0))
      .catch(() => current && setHasText(false));
    return () => {
      current = false;
    };
  }, [track.id]);

  if (!hasChapters) return <Lyrics songId={track.id} emptyText="No text for this file yet." />;
  if (hasText === null) return <div />;
  if (!hasText) return <Chapters />;
  return (
    <div className="now-playing__spoken">
      <div className="now-playing__views" role="tablist" aria-label="Show">
        {(["text", "chapters"] as const).map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            className={`now-playing__view${view === id ? " now-playing__view--active" : ""}`}
            onClick={() => setView(id)}
          >
            {id === "text" ? "Text" : "Chapters"}
          </button>
        ))}
      </div>
      {view === "text" ? <Lyrics songId={track.id} /> : <Chapters />}
    </div>
  );
}

/** The chapters inside the current file (audiobooks): the one playing is highlighted, a click goes there. */
function Chapters() {
  const { state, engine } = usePlayer();
  const chapters = state.current?.chapters;
  const list = useRef<HTMLOListElement>(null);

  // The current chapter stays in view.
  useEffect(() => {
    list.current?.querySelector(".now-playing__chapter--current")?.scrollIntoView({ block: "nearest" });
  }, [state.chapter]);

  if (!chapters) return <div />;
  return (
    <ol className="now-playing__chapters" ref={list} aria-label="Chapters">
      {chapters.map((chapter, i) => (
        <li key={chapter.start}>
          <button
            className={`now-playing__chapter${i === state.chapter ? " now-playing__chapter--current" : ""}`}
            type="button"
            aria-current={i === state.chapter || undefined}
            onClick={() => {
              engine.seek(chapter.start);
              if (!state.playing) engine.togglePlay();
            }}
          >
            <span className="now-playing__chapter-title">{chapter.title}</span>
            <span className="text-muted">{formatTime(chapter.start)}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}
