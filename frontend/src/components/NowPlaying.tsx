import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { formatTime } from "../format";
import { usePlayer } from "../player/PlayerContext";
import { albumUrl, artistUrl } from "../player/tracks";
import { CoverArt } from "./CoverArt";
import { Lyrics } from "./Lyrics";
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

/** Big cover, visualizer and lyrics (synced ones follow the song) of the current track. */
export function NowPlaying() {
  const { open, close } = useNowPlaying();
  const { state } = usePlayer();
  const location = useLocation();
  const current = state.current;
  const artistLink = current ? artistUrl(current) : undefined;
  const albumLink = current ? albumUrl(current) : undefined;

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
          {/* No lyrics for podcasts and audiobooks: their chapters, if the file has some. */}
          {current.longForm ? <Chapters /> : <Lyrics songId={current.id} />}
        </div>
      ) : (
        <p className="text-muted now-playing__empty">Nothing playing.</p>
      )}
    </section>
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
