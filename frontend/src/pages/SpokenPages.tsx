import { type CSSProperties, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  api,
  type SpokenKind,
  type SpokenPage as PageData,
  type SpokenShow,
  type SpokenShowData,
} from "../api/native";
import type { Child } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { CoverArt } from "../components/CoverArt";
import { PlayIcon } from "../components/Icons";
import { formatDuration, formatTime, plural } from "../format";
import { songToTrack, usePlayer } from "../player/PlayerContext";

const TITLES: Record<SpokenKind, string> = { podcasts: "Podcasts", audiobooks: "Audiobooks" };
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const showUrl = (show: SpokenShow) => `/${show.kind}/${show.id}`;
const seriesUrl = (series: string) => `/audiobooks/series/${encodeURIComponent(series)}`;

/** A series' books in reading order: by number (1, 1.5, 2...), then title. */
function inSeriesOrder(books: SpokenShow[]): SpokenShow[] {
  const number = (b: SpokenShow) => {
    const n = Number.parseFloat(b.seriesNumber ?? "");
    return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
  };
  return [...books].sort((a, b) => number(a) - number(b) || a.title.localeCompare(b.title));
}

/** An item of the Audiobooks grid: a book, or a series (its books behind one card). */
type GridItem = { book: SpokenShow } | { series: string; books: SpokenShow[] };

function gridItems(shows: SpokenShow[], kind: SpokenKind): GridItem[] {
  if (kind !== "audiobooks") return shows.map((book) => ({ book }));
  const series = new Map<string, SpokenShow[]>();
  const items: GridItem[] = [];
  for (const show of shows) {
    if (!show.series) {
      items.push({ book: show });
      continue;
    }
    const key = show.series.toLocaleLowerCase();
    const books = series.get(key);
    if (books) books.push(show);
    else {
      const first = [show];
      series.set(key, first);
      items.push({ series: show.series, books: first });
    }
  }
  const name = (item: GridItem) => ("book" in item ? item.book.title : item.series);
  return items
    .map((item) => ("books" in item ? { ...item, books: inSeriesOrder(item.books) } : item))
    .sort((a, b) => name(a).localeCompare(name(b), undefined, { sensitivity: "base" }));
}

function BookCard({
  show,
  kind,
  label,
  number,
}: {
  show: SpokenShow;
  kind: SpokenKind;
  label?: string;
  number?: string | null; // a series' book: its number, over the cover
}) {
  return (
    <Link className="album-card spoken__card" to={showUrl(show)} title={show.title}>
      <CoverArt id={show.coverArt ?? undefined} size={320} className="album-card__cover" alt="" />
      {number && (
        <span className="spoken__book-number" aria-label={`Book ${number}`}>
          {number}
        </span>
      )}
      <span className="album-card__name">{show.title}</span>
      <span className="album-card__info">
        {label ?? (kind === "audiobooks" ? show.author : plural(show.episodes, "episode"))}
        {show.started > 0 && <span className="badge spoken__badge">Started</span>}
      </span>
    </Link>
  );
}

function SeriesCard({ series, books }: { series: string; books: SpokenShow[] }) {
  const cover = books.find((b) => b.coverArt)?.coverArt;
  const authors = [...new Set(books.map((b) => b.author))].join(", ");
  return (
    <Link className="album-card spoken__card spoken__series-card" to={seriesUrl(series)} title={series}>
      <CoverArt id={cover ?? undefined} size={320} className="album-card__cover" alt="" />
      <span className="album-card__name">{series}</span>
      <span className="album-card__info">
        {plural(books.length, "book")} · {authors}
        {books.some((b) => b.started > 0) && <span className="badge spoken__badge">Started</span>}
      </span>
    </Link>
  );
}

/** Seconds listened of an episode: its bookmark (ms). */
const listened = (episode: Child) => (episode.bookmarkPosition ?? 0) / 1000;

/**
 * Plays a show's episodes from one of them: an audiobook goes on with the next chapters,
 * a podcast plays that episode only. The player resumes it at its bookmark, unless a
 * position is given (a chapter inside the file).
 */
function usePlayFrom() {
  const { engine, state } = usePlayer();
  return (kind: SpokenKind, episodes: Child[], index: number, startAt?: number) => {
    const episode = episodes[index];
    if (startAt !== undefined && episode && state.current?.id === episode.id) {
      // Already the current file: only move in it.
      engine.seek(startAt);
      if (!state.playing) engine.togglePlay();
      return;
    }
    const tracks = episodes.map(songToTrack);
    if (kind === "audiobooks") engine.playQueue(tracks.slice(index), 0, startAt);
    else engine.playQueue(tracks.slice(index, index + 1), 0, startAt);
  };
}

/** A chapter to listen to: a whole file ("hard" chapter) or a chapter inside one ("soft"). */
interface Part {
  file: number; // index in the episodes
  start: number; // seconds into the file
  end: number;
  title: string;
}

/** The book as a list of chapters: each file, or the chapters inside it when it has some. */
function bookParts(episodes: Child[]): Part[] {
  return episodes.flatMap((episode, file) => {
    const duration = episode.duration ?? 0;
    const inside = episode.chapters;
    if (!inside?.length) return [{ file, start: 0, end: duration, title: episode.title }];
    return inside.map((chapter, i) => ({
      file,
      start: chapter.startMs / 1000,
      end: (inside[i + 1]?.startMs ?? duration * 1000) / 1000,
      title: chapter.title,
    }));
  });
}

/** The part at `position` seconds into `file` (-1: none). */
function partAt(parts: Part[], file: number, position: number): number {
  let found = -1;
  parts.forEach((part, i) => {
    if (part.file === file && part.start <= position + 0.5) found = i;
  });
  return found;
}

function Progress({ value }: { value: number }) {
  return (
    <div className="meter spoken__meter" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="meter__fill" style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` } as CSSProperties} />
    </div>
  );
}

/** Podcasts or Audiobooks: what you started, then every show / book. */
export function SpokenPage({ kind }: { kind: SpokenKind }) {
  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const playFrom = usePlayFrom();

  useEffect(() => {
    setData(null);
    setError(null);
    api
      .getSpokenPage(kind)
      .then(setData)
      .catch((e: unknown) => setError(errorText(e)));
  }, [kind]);

  async function resume(show: SpokenShow, episodeId: string) {
    try {
      const { episodes } = await api.getSpokenShow(show.id);
      const index = episodes.findIndex((e) => e.id === episodeId);
      if (index >= 0) playFrom(kind, episodes, index);
    } catch (e) {
      setError(errorText(e));
    }
  }

  // "Dismiss" asks first: the buttons become Confirm (where Resume was) and Cancel, so a
  // slip of the finger cannot forget where the user stopped.
  const [dismissing, setDismissing] = useState<string | null>(null);

  /** Out of "Continue listening": the show's / book's bookmarks go. */
  async function dismiss(show: SpokenShow) {
    setDismissing(null);
    try {
      await api.forgetSpokenShow(show.id);
      setData((current) =>
        current && {
          continueListening: current.continueListening.filter((r) => r.show.id !== show.id),
          shows: current.shows.map((s) => (s.id === show.id ? { ...s, started: 0 } : s)),
        },
      );
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="page spoken">
      <h1 className="page__title">{TITLES[kind]}</h1>
      {error && <p className="text-error">{error}</p>}
      {!data && !error && <p className="text-muted">Loading…</p>}
      {data && data.continueListening.length > 0 && (
        <section className="spoken__section">
          <h2 className="spoken__heading">Continue listening</h2>
          <ul className="spoken__resume-list">
            {data.continueListening.map(({ show, episode }) => {
              const duration = episode.duration ?? 0;
              return (
                <li key={show.id} className="spoken__resume">
                  <CoverArt id={show.coverArt ?? undefined} size={64} className="spoken__resume-cover" alt="" />
                  <div className="spoken__resume-text">
                    <Link className="spoken__resume-show" to={showUrl(show)}>
                      {show.title}
                    </Link>
                    <span className="text-muted">
                      {episode.title}
                      {/* The chapter inside the file, when it has some. */}
                      {(() => {
                        const parts = bookParts([episode]);
                        const part = episode.chapters?.length ? parts[partAt(parts, 0, listened(episode))] : undefined;
                        return part && part.title !== episode.title ? ` · ${part.title}` : "";
                      })()}
                    </span>
                    <Progress value={duration ? listened(episode) / duration : 0} />
                    <span className="text-muted spoken__small">{formatDuration(Math.max(0, duration - listened(episode)))} left</span>
                  </div>
                  {dismissing === show.id ? (
                    <div className="spoken__resume-actions" role="group" aria-label={`Dismiss ${show.title}?`}>
                      <button
                        className="button button--danger"
                        type="button"
                        title="Forget where you stopped: out of this list"
                        onClick={() => void dismiss(show)}
                      >
                        Confirm
                      </button>
                      <button className="button" type="button" onClick={() => setDismissing(null)}>
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="spoken__resume-actions">
                      <button className="button button--primary" type="button" onClick={() => void resume(show, episode.id)}>
                        <PlayIcon /> Resume
                      </button>
                      <button
                        className="button"
                        type="button"
                        title="Forget where you stopped: out of this list (asks to confirm)"
                        onClick={() => setDismissing(show.id)}
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {data && (
        <section className="spoken__section">
          {data.continueListening.length > 0 && <h2 className="spoken__heading">All {TITLES[kind].toLowerCase()}</h2>}
          {data.shows.length === 0 ? (
            <div className="empty-state">
              <p className="text-muted">
                Nothing yet. Add {kind} with Library Management → Import ("Import as"), or copy them into the {kind}{" "}
                folder.
              </p>
            </div>
          ) : (
            <ul className="album-grid">
              {gridItems(data.shows, kind).map((item) =>
                "book" in item ? (
                  <li key={item.book.id}>
                    <BookCard show={item.book} kind={kind} />
                  </li>
                ) : (
                  // A series: one card, its books behind it.
                  <li key={`series:${item.series}`}>
                    <SeriesCard series={item.series} books={item.books} />
                  </li>
                ),
              )}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

/** The books of a series, in reading order (a series card of the Audiobooks page). */
export function SpokenSeriesPage() {
  const { series = "" } = useParams();
  const [books, setBooks] = useState<SpokenShow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBooks(null);
    api
      .getSpokenPage("audiobooks")
      .then((page) =>
        setBooks(inSeriesOrder(page.shows.filter((s) => s.series?.toLocaleLowerCase() === series.toLocaleLowerCase()))),
      )
      .catch((e: unknown) => setError(errorText(e)));
  }, [series]);

  if (error) return <p className="text-error">{error}</p>;
  if (!books) return <p className="text-muted">Loading…</p>;
  const authors = [...new Set(books.map((b) => b.author))].join(", ");
  const total = books.reduce((sum, b) => sum + b.durationMs, 0) / 1000;
  return (
    <div className="page spoken">
      <p className="text-muted">
        <Link className="link" to="/audiobooks">
          Audiobooks
        </Link>{" "}
        · Series
      </p>
      <h1 className="page__title">{books[0]?.series ?? series}</h1>
      <p className="text-muted">
        {authors} · {plural(books.length, "book")} · {formatDuration(total)}
      </p>
      {books.length === 0 ? (
        <p className="text-muted">No book of this series.</p>
      ) : (
        <ul className="album-grid">
          {books.map((book) => (
            <li key={book.id}>
              <BookCard show={book} kind="audiobooks" label={book.author} number={book.seriesNumber} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A podcast (episodes, newest first) or an audiobook (chapters, with the book's progress). */
export function SpokenShowPage({ kind }: { kind: SpokenKind }) {
  const { id = "" } = useParams();
  const { state } = usePlayer();
  const { user } = useSession();
  const playFrom = usePlayFrom();
  const [data, setData] = useState<SpokenShowData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setData(null);
    setError(null);
    api
      .getSpokenShow(id)
      .then(setData)
      .catch((e: unknown) => setError(errorText(e)));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <p className="text-error">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const { show, episodes, description, genre } = data;
  const book = kind === "audiobooks";
  const first = episodes[0];

  // Audiobook: the chapter being listened to (in a file, or a whole file), and how far
  // into the whole book.
  const current = episodes.findIndex((e) => e.bookmarkPosition !== undefined);
  const parts = bookParts(episodes);
  const currentPart = current >= 0 ? partAt(parts, current, listened(episodes[current]!)) : -1;
  const total = show.durationMs / 1000;
  const done =
    current >= 0
      ? episodes.slice(0, current).reduce((sum, e) => sum + (e.duration ?? 0), 0) + listened(episodes[current]!)
      : 0;

  async function startOver() {
    // The book starts again: its bookmarks go.
    await api.forgetSpokenShow(show.id).catch(() => undefined);
    const cleared = episodes.map((e) => ({ ...e, bookmarkPosition: undefined }));
    setData({ ...data!, episodes: cleared });
    playFrom(kind, cleared, 0);
  }

  return (
    <div className="page spoken">
      <header className="spoken__header">
        <CoverArt id={show.coverArt ?? undefined} size={220} className="spoken__cover" alt="" />
        <div className="spoken__header-text">
          <span className="text-muted">{book ? "Audiobook" : "Podcast"}</span>
          <h1 className="page__title">{show.title}</h1>
          {show.author && <p className="spoken__author">{show.author}</p>}
          {book && show.series && (
            <p className="spoken__series">
              {show.seriesNumber ? `Book ${show.seriesNumber} of ` : ""}
              <Link className="link" to={seriesUrl(show.series)}>
                {show.series}
              </Link>
            </p>
          )}
          <p className="text-muted">
            {plural(book ? parts.length : show.episodes, book ? "chapter" : "episode")} · {formatDuration(total)}
          </p>
          {book && current >= 0 && (
            <div className="spoken__book-progress">
              <Progress value={total ? done / total : 0} />
              <span className="text-muted spoken__small">
                Chapter {currentPart + 1} of {parts.length} · {formatDuration(Math.max(0, total - done))} left
              </span>
            </div>
          )}
          <div className="settings-section__actions">
            {book ? (
              <>
                <button className="button button--primary" type="button" onClick={() => playFrom(kind, episodes, Math.max(current, 0))}>
                  <PlayIcon /> {current >= 0 ? "Resume" : "Play"}
                </button>
                {current >= 0 && (
                  <button className="button" type="button" onClick={() => void startOver()}>
                    Start from the beginning
                  </button>
                )}
              </>
            ) : (
              episodes.length > 0 && (
                <button className="button button--primary" type="button" onClick={() => playFrom(kind, episodes, 0)}>
                  <PlayIcon /> Play the latest
                </button>
              )
            )}
            {user.adminRole && (
              <Link className="button button--ghost" to={`/${kind}/${show.id}/details`}>
                Edit details
              </Link>
            )}
          </div>
        </div>
      </header>

      <section className="spoken__about" aria-label="Details">
        {description && <Description text={description} />}
        <dl className="spoken__details">
          {show.narrator && (
            <>
              <dt>Narrated by</dt>
              <dd>{show.narrator}</dd>
            </>
          )}
          {show.year && (
            <>
              <dt>Year</dt>
              <dd>{show.year}</dd>
            </>
          )}
          {genre && (
            <>
              <dt>Genre</dt>
              <dd>{genre}</dd>
            </>
          )}
          <dt>Length</dt>
          <dd>{formatDuration(total)}</dd>
          {first?.suffix && (
            <>
              <dt>Format</dt>
              <dd>
                {first.suffix.toUpperCase()}
                {first.bitRate ? ` · ${first.bitRate} kbps` : ""} · {plural(episodes.length, "file")}
              </dd>
            </>
          )}
        </dl>
      </section>

      <ol className="spoken__episodes">
        {episodes.map((episode, index) => {
          const duration = episode.duration ?? 0;
          const position = listened(episode);
          const playing = state.current?.id === episode.id;
          return (
            <li key={episode.id} className={`spoken__episode${playing ? " spoken__episode--playing" : ""}`}>
              <button
                className="icon-button"
                type="button"
                aria-label={`Play ${episode.title}`}
                onClick={() => playFrom(kind, episodes, index)}
              >
                <PlayIcon />
              </button>
              <div className="spoken__episode-text">
                <span className="spoken__episode-title">
                  {book ? `${index + 1}. ` : ""}
                  {episode.title}
                </span>
                <span className="text-muted spoken__small">
                  {formatTime(duration)}
                  {episode.bookmarkPosition !== undefined && ` · ${formatDuration(Math.max(0, duration - position))} left`}
                  {episode.bookmarkPosition === undefined && episode.playCount ? " · Played" : ""}
                </span>
                {episode.bookmarkPosition !== undefined && <Progress value={duration ? position / duration : 0} />}
                {book && episode.chapters && episode.chapters.length > 0 && (
                  <SoftChapters
                    parts={parts.filter((p) => p.file === index)}
                    // Where the file is: live while it plays, else its bookmark.
                    position={playing ? state.position : episode.bookmarkPosition !== undefined ? position : null}
                    onPlay={(start) => playFrom(kind, episodes, index, start)}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** A description: its first lines, and all of it on demand when it is long. */
function Description({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 420 || text.split("\n").length > 5;
  return (
    <div className="spoken__description-block">
      <p className={`spoken__description${long && !open ? " spoken__description--folded" : ""}`}>{text}</p>
      {long && (
        <button className="link spoken__more" type="button" onClick={() => setOpen(!open)}>
          {open ? "Less" : "More"}
        </button>
      )}
    </div>
  );
}

/**
 * The chapters inside a file, under it: folded to the current one, unfolded on demand.
 * `position`: where the file is (seconds), null when not started.
 */
function SoftChapters({
  parts,
  position,
  onPlay,
}: {
  parts: Part[];
  position: number | null;
  onPlay(start: number): void;
}) {
  const [open, setOpen] = useState(false);
  const current = position === null ? -1 : partAt(parts, parts[0]?.file ?? 0, position);
  const shown = open ? parts : parts.filter((_, i) => i === current);

  return (
    <div className="spoken__soft">
      {shown.length > 0 && (
        <ol className="spoken__soft-list">
          {shown.map((part) => {
            const i = parts.indexOf(part);
            const here = i === current && position !== null;
            const length = part.end - part.start;
            return (
              <li key={part.start} className={`spoken__soft-chapter${here ? " spoken__soft-chapter--current" : ""}`}>
                <button className="icon-button" type="button" aria-label={`Play ${part.title}`} onClick={() => onPlay(part.start)}>
                  <PlayIcon />
                </button>
                <span className="spoken__soft-title">{part.title}</span>
                <span className="text-muted spoken__small">
                  {formatTime(part.start)}
                  {here && ` · ${formatDuration(Math.max(0, part.end - position))} left`}
                </span>
                {here && <Progress value={length > 0 ? (position - part.start) / length : 0} />}
              </li>
            );
          })}
        </ol>
      )}
      <button className="link-button spoken__soft-toggle" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide the chapters" : `Show ${plural(parts.length, "chapter")}`}
      </button>
    </div>
  );
}
