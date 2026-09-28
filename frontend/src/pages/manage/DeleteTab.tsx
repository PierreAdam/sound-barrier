import { useMemo, useState } from "react";

import { api, type DeleteResult } from "../../api/native";
import type { AlbumID3 } from "../../api/types";
import { invalidateSubsonicCache, useSubsonic } from "../../api/useSubsonic";
import { CoverArt } from "../../components/CoverArt";
import { formatTime, plural } from "../../format";

/** Permanently delete albums or songs (files on disk and library entries). */
export function DeleteTab() {
  const artists = useSubsonic("getArtists");
  const [artistId, setArtistId] = useState<string>("");
  const [filter, setFilter] = useState("");
  const [albums, setAlbums] = useState<Set<string>>(() => new Set());
  const [songs, setSongs] = useState<Set<string>>(() => new Set());
  const [result, setResult] = useState<DeleteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const allArtists = useMemo(
    () => (artists.data?.artists.index ?? []).flatMap((group) => group.artist),
    [artists.data],
  );
  const shown = allArtists.filter((a) => a.name.toLowerCase().includes(filter.trim().toLowerCase()));
  // The chosen artist is gone once all its albums are deleted: back to "Choose an artist".
  const selected = allArtists.some((a) => a.id === artistId) ? artistId : "";

  function toggle(set: Set<string>, update: (s: Set<string>) => void, id: string) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    update(next);
  }

  async function onDelete() {
    const what = [albums.size && plural(albums.size, "album"), songs.size && plural(songs.size, "song")]
      .filter(Boolean)
      .join(" and ");
    if (!window.confirm(`Permanently delete ${what}?\n\nThe files are deleted from the disk. This cannot be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.deleteMusic([...albums], [...songs]));
      setAlbums(new Set());
      setSongs(new Set());
      invalidateSubsonicCache();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

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
          albums={albums}
          songs={songs}
          onToggleAlbum={(id) => toggle(albums, setAlbums, id)}
          onToggleSong={(id) => toggle(songs, setSongs, id)}
        />
      )}

      <div className="settings-section__actions">
        <button
          className="button button--danger"
          type="button"
          disabled={busy || (albums.size === 0 && songs.size === 0)}
          onClick={() => void onDelete()}
        >
          Delete selected ({plural(albums.size, "album")}, {plural(songs.size, "song")})
        </button>
      </div>
      {error && <p className="text-error">{error}</p>}
      {result && (
        <p className="text-success">
          Deleted {plural(result.songs, "song")} ({plural(result.filesDeleted, "file")}
          {result.filesAlreadyGone ? `, ${result.filesAlreadyGone} already missing` : ""}
          {result.foldersRemoved.length ? `, ${plural(result.foldersRemoved.length, "folder")} removed` : ""}).
        </p>
      )}
    </section>
  );
}

function ArtistAlbums({
  artistId,
  albums,
  songs,
  onToggleAlbum,
  onToggleSong,
}: {
  artistId: string;
  albums: Set<string>;
  songs: Set<string>;
  onToggleAlbum(id: string): void;
  onToggleSong(id: string): void;
}) {
  const artist = useSubsonic("getArtist", { id: artistId });
  const [open, setOpen] = useState<string | null>(null);
  if (artist.error) return <p className="text-error">{artist.error.message}</p>;
  const list: AlbumID3[] = artist.data?.artist.album ?? [];

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
    <ul className="delete-list__songs">
      {(album.data?.album.song ?? []).map((song) => (
        <li key={song.id} className="delete-list__row">
          <input
            type="checkbox"
            aria-label={`Delete song ${song.title}`}
            disabled={disabled}
            checked={disabled || songs.has(song.id)}
            onChange={() => onToggle(song.id)}
          />
          <span className="tracks__number">{song.track ?? ""}</span>
          <span>{song.title}</span>
          <span className="text-muted">{formatTime(song.duration)}</span>
        </li>
      ))}
    </ul>
  );
}
