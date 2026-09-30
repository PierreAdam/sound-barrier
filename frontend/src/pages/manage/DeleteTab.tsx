import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type DeleteResult, type SpokenKind, type SpokenShow } from "../../api/native";
import type { AlbumID3, Child } from "../../api/types";
import { invalidateSubsonicCache, useSubsonic } from "../../api/useSubsonic";
import { useSections } from "../../api/useSections";
import { CoverArt } from "../../components/CoverArt";
import { formatTime, plural } from "../../format";

/** Permanently delete music, audiobooks or podcasts (files on disk and library entries). */
export function DeleteTab() {
  const { sections } = useSections();
  return (
    <>
      <MusicDelete />
      {sections.audiobooks && <SpokenDelete kind="audiobooks" />}
      {sections.podcasts && <SpokenDelete kind="podcasts" />}
    </>
  );
}

/** What each section deletes: albums (music), books (audiobooks), shows (podcasts). */
const WORDS = {
  music: { whole: "album", part: "song" },
  audiobooks: { whole: "book", part: "file" }, // files: a file may hold many chapters
  podcasts: { whole: "podcast", part: "episode" },
} as const;

type Words = (typeof WORDS)[keyof typeof WORDS];

/** The ticked albums / songs of a section, and deleting them (`onDeleted`: what went). */
function useDeletion(words: Words, onDeleted?: (albumIds: string[], songIds: string[]) => void) {
  const [albums, setAlbums] = useState<Set<string>>(() => new Set());
  const [songs, setSongs] = useState<Set<string>>(() => new Set());
  const [result, setResult] = useState<DeleteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = (set: Set<string>, update: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    update(next);
  };

  async function onDelete() {
    const what = [albums.size && plural(albums.size, words.whole), songs.size && plural(songs.size, words.part)]
      .filter(Boolean)
      .join(" and ");
    if (!window.confirm(`Permanently delete ${what}?\n\nThe files are deleted from the disk. This cannot be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      const deleted = { albums: [...albums], songs: [...songs] };
      setResult(await api.deleteMusic(deleted.albums, deleted.songs));
      setAlbums(new Set());
      setSongs(new Set());
      invalidateSubsonicCache();
      onDeleted?.(deleted.albums, deleted.songs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const footer = (
    <>
      <div className="settings-section__actions">
        <button
          className="button button--danger"
          type="button"
          disabled={busy || (albums.size === 0 && songs.size === 0)}
          onClick={() => void onDelete()}
        >
          Delete selected ({plural(albums.size, words.whole)}, {plural(songs.size, words.part)})
        </button>
      </div>
      {error && <p className="text-error">{error}</p>}
      {result && (
        <p className="text-success">
          Deleted {plural(result.songs, words.part)} ({plural(result.filesDeleted, "file")}
          {result.filesAlreadyGone ? `, ${result.filesAlreadyGone} already missing` : ""}
          {result.foldersRemoved.length ? `, ${plural(result.foldersRemoved.length, "folder")} removed` : ""}).
        </p>
      )}
    </>
  );

  return {
    albums,
    songs,
    toggleAlbum: (id: string) => toggle(albums, setAlbums, id),
    toggleSong: (id: string) => toggle(songs, setSongs, id),
    footer,
  };
}

function MusicDelete() {
  const artists = useSubsonic("getArtists");
  const [artistId, setArtistId] = useState<string>("");
  const [filter, setFilter] = useState("");
  const deletion = useDeletion(WORDS.music);

  const allArtists = useMemo(
    () => (artists.data?.artists.index ?? []).flatMap((group) => group.artist),
    [artists.data],
  );
  const shown = allArtists.filter((a) => a.name.toLowerCase().includes(filter.trim().toLowerCase()));
  // The chosen artist is gone once all its albums are deleted: back to "Choose an artist".
  const selected = allArtists.some((a) => a.id === artistId) ? artistId : "";

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Delete music</h2>
      <p className="text-muted">Choose an artist, tick whole albums or single songs, then delete. Files are removed from disk.</p>
      <div className="form-grid">
        <label className="field">
          <span className="field__label">Filter artists</span>
          <input className="field__input" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Artist</span>
          <select className="field__input" value={selected} onChange={(e) => setArtistId(e.target.value)}>
            <option value="">Choose an artist ({shown.length})</option>
            {shown.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({plural(a.albumCount, "album")})
              </option>
            ))}
          </select>
        </label>
      </div>

      {selected && (
        <ArtistAlbums
          artistId={selected}
          albums={deletion.albums}
          songs={deletion.songs}
          onToggleAlbum={deletion.toggleAlbum}
          onToggleSong={deletion.toggleSong}
        />
      )}
      {deletion.footer}
    </section>
  );
}

/**
 * Deleting some of these albums, or single songs of them (an artist page, an album page):
 * the list of Library Management → Delete, with its button. `onDeleted`: what went.
 */
export function AlbumsDelete({
  albums,
  expanded = false,
  onDeleted,
}: {
  albums: AlbumID3[];
  expanded?: boolean; // the songs shown at once (a single album)
  onDeleted?(albumIds: string[], songIds: string[]): void;
}) {
  const deletion = useDeletion(WORDS.music, onDeleted);
  return (
    <section className="settings-section settings-section--wide">
      <p className="text-muted">Tick whole albums or single songs, then delete. Files are removed from disk.</p>
      <AlbumList
        list={albums}
        expanded={expanded}
        albums={deletion.albums}
        songs={deletion.songs}
        onToggleAlbum={deletion.toggleAlbum}
        onToggleSong={deletion.toggleSong}
      />
      {deletion.footer}
    </section>
  );
}

function ArtistAlbums({
  artistId,
  ...ticks
}: {
  artistId: string;
  albums: Set<string>;
  songs: Set<string>;
  onToggleAlbum(id: string): void;
  onToggleSong(id: string): void;
}) {
  const artist = useSubsonic("getArtist", { id: artistId });
  if (artist.error) return <p className="text-error">{artist.error.message}</p>;
  return <AlbumList list={artist.data?.artist.album ?? []} {...ticks} />;
}

function AlbumList({
  list,
  expanded = false,
  albums,
  songs,
  onToggleAlbum,
  onToggleSong,
}: {
  list: AlbumID3[];
  expanded?: boolean;
  albums: Set<string>;
  songs: Set<string>;
  onToggleAlbum(id: string): void;
  onToggleSong(id: string): void;
}) {
  const [open, setOpen] = useState<string | null>(expanded ? (list[0]?.id ?? null) : null);

  return (
    <ul className="delete-list">
      {list.map((album) => (
        <li key={album.id} className="delete-list__album">
          <div className="delete-list__row">
            <input
              type="checkbox"
              aria-label={`Delete album ${album.name}`}
              checked={albums.has(album.id)}
              onChange={() => onToggleAlbum(album.id)}
            />
            <CoverArt id={album.coverArt} size={40} className="delete-list__cover" />
            <button className="browser__open" type="button" onClick={() => setOpen(open === album.id ? null : album.id)}>
              <strong>{album.name}</strong>
              <span className="text-muted">
                {[album.year, plural(album.songCount, "song")].filter(Boolean).join(" · ")}
              </span>
            </button>
          </div>
          {open === album.id && (
            <AlbumSongs albumId={album.id} disabled={albums.has(album.id)} songs={songs} onToggle={onToggleSong} />
          )}
        </li>
      ))}
    </ul>
  );
}

function AlbumSongs({
  albumId,
  disabled,
  songs,
  onToggle,
}: {
  albumId: string;
  disabled: boolean;
  songs: Set<string>;
  onToggle(id: string): void;
}) {
  const album = useSubsonic("getAlbum", { id: albumId });
  return (
    <SongRows
      songs={album.data?.album.song ?? []}
      disabled={disabled}
      ticked={songs}
      onToggle={onToggle}
      label="song"
      number={(song) => song.track ?? ""}
    />
  );
}

function SongRows({
  songs,
  disabled,
  ticked,
  onToggle,
  label,
  number,
}: {
  songs: Child[];
  disabled: boolean;
  ticked: Set<string>;
  onToggle(id: string): void;
  label: string;
  number(song: Child, index: number): string | number;
}) {
  return (
    <ul className="delete-list__songs">
      {songs.map((song, index) => (
        <li key={song.id} className="delete-list__row">
          <input
            type="checkbox"
            aria-label={`Delete ${label} ${song.title}`}
            disabled={disabled}
            checked={disabled || ticked.has(song.id)}
            onChange={() => onToggle(song.id)}
          />
          <span className="tracks__number">{number(song, index)}</span>
          <span>{song.title}</span>
          <span className="text-muted">{formatTime(song.duration)}</span>
        </li>
      ))}
    </ul>
  );
}

const SPOKEN_TITLES: Record<SpokenKind, string> = { audiobooks: "Delete audiobooks", podcasts: "Delete podcasts" };

/** Audiobooks or podcasts: whole books / shows, or single chapters / episodes. */
function SpokenDelete({ kind }: { kind: SpokenKind }) {
  const words = WORDS[kind];
  const [shows, setShows] = useState<SpokenShow[] | null>(null);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getSpokenPage(kind)
      .then((page) => setShows(page.shows))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [kind]);
  useEffect(load, [load]);
  const deletion = useDeletion(words, load);
  const shown = (shows ?? []).filter((s) =>
    `${s.title} ${s.author}`.toLowerCase().includes(filter.trim().toLowerCase()),
  );

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">{SPOKEN_TITLES[kind]}</h2>
      <p className="text-muted">
        Tick whole {words.whole}s or single {words.part}s, then delete. Files are removed from disk.
      </p>
      {error && <p className="text-error">{error}</p>}
      {shows && shows.length === 0 && <p className="text-muted">Nothing here.</p>}
      {shows && shows.length > 0 && (
        <>
          {shows.length > 8 && (
            <label className="field">
              <span className="field__label">Filter</span>
              <input className="field__input" value={filter} onChange={(e) => setFilter(e.target.value)} />
            </label>
          )}
          <ul className="delete-list">
            {shown.map((show) => (
              <li key={show.id} className="delete-list__album">
                <div className="delete-list__row">
                  <input
                    type="checkbox"
                    aria-label={`Delete ${words.whole} ${show.title}`}
                    checked={deletion.albums.has(show.id)}
                    onChange={() => deletion.toggleAlbum(show.id)}
                  />
                  <CoverArt id={show.coverArt ?? undefined} size={40} className="delete-list__cover" />
                  <button className="browser__open" type="button" onClick={() => setOpen(open === show.id ? null : show.id)}>
                    <strong>{show.title}</strong>
                    <span className="text-muted">
                      {[show.author, plural(show.episodes, words.part)].filter(Boolean).join(" · ")}
                    </span>
                  </button>
                </div>
                {open === show.id && (
                  <ShowEpisodes
                    showId={show.id}
                    label={words.part}
                    numbered={kind === "audiobooks"}
                    disabled={deletion.albums.has(show.id)}
                    songs={deletion.songs}
                    onToggle={deletion.toggleSong}
                  />
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {deletion.footer}
    </section>
  );
}

function ShowEpisodes({
  showId,
  label,
  numbered,
  disabled,
  songs,
  onToggle,
}: {
  showId: string;
  label: string;
  numbered: boolean;
  disabled: boolean;
  songs: Set<string>;
  onToggle(id: string): void;
}) {
  const [episodes, setEpisodes] = useState<Child[] | null>(null);
  useEffect(() => {
    api
      .getSpokenShow(showId)
      .then((page) => setEpisodes(page.episodes))
      .catch(() => setEpisodes([]));
  }, [showId]);
  if (!episodes) return <p className="text-muted">Loading…</p>;
  return (
    <SongRows
      songs={episodes}
      disabled={disabled}
      ticked={songs}
      onToggle={onToggle}
      label={label}
      number={(_, index) => (numbered ? index + 1 : "")}
    />
  );
}
