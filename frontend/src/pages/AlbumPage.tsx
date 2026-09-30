import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { Child } from "../api/types";
import { useSubsonic } from "../api/useSubsonic";
import { AddToPlaylist } from "../components/AddToPlaylist";
import { CoverArt } from "../components/CoverArt";
import { useSession } from "../auth/AuthContext";
import { AddIcon, EditIcon, PlayIcon, PlayNextIcon, ShuffleIcon, TrashIcon } from "../components/Icons";
import { formatTime, plural } from "../format";
import { songToTrack, usePlayer } from "../player/PlayerContext";
import { AlbumsDelete } from "./manage/DeleteTab";

/** Album view: header with actions, track list, cover on the right (like Subsonic). */
export function AlbumPage() {
  const { id = "" } = useParams();
  const { data, error, loading } = useSubsonic("getAlbum", { id });
  const { state, engine } = usePlayer();
  const { user, client } = useSession();
  const album = data?.album;
  const songs = album?.song ?? [];
  // Ticked tracks: "Add to queue" and "Play next" then only take those.
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [deleting, setDeleting] = useState(false); // admins: the delete panel is open
  const navigate = useNavigate();
  useEffect(() => {
    setSelected(new Set());
    setDeleting(false);
  }, [id]);

  if (error) return <p className="text-error">{error.message}</p>;
  if (loading && !album) return <p className="text-muted">Loading…</p>;
  if (!album) return null;

  const tracks = songs.map(songToTrack);
  const multiDisc = new Set(songs.map((s) => s.discNumber ?? 1)).size > 1;
  const discTitle = (disc: number) => album.discTitles?.find((d) => d.disc === disc)?.title;
  const genres = album.genres?.map((g) => g.name) ?? (album.genre ? [album.genre] : []);

  const chosen = selected.size ? tracks.filter((t) => selected.has(t.id)) : tracks;
  function withSelection(action: (chosenTracks: typeof tracks) => void) {
    action(chosen);
    setSelected(new Set());
  }
  function toggle(songId: string) {
    const next = new Set(selected);
    if (next.has(songId)) next.delete(songId);
    else next.add(songId);
    setSelected(next);
  }

  function shuffle() {
    if (!state.shuffle) engine.toggleShuffle();
    engine.playQueue(tracks, Math.floor(Math.random() * tracks.length));
  }

  return (
    <div className="page album">
      <header className="album-header">
        <CoverArt id={album.artistId} size={64} className="album-header__artist-image" alt="" />
        <div className="album-header__meta">
          {album.artistId && (
            <Link className="album-header__artist" to={`/artists/${album.artistId}`}>
              {album.artist}
            </Link>
          )}
          <div className="album-header__title-row">
            <h1 className="album-header__title">{album.name}</h1>
            <button
              className="icon-button icon-button--primary album-header__play"
              type="button"
              aria-label="Play album"
              disabled={!tracks.length}
              onClick={() => engine.playQueue(tracks, 0)}
            >
              <PlayIcon />
            </button>
          </div>
          <p className="album-header__facts">
            {[album.year, plural(album.songCount, "track"), formatTime(album.duration)]
              .filter(Boolean)
              .join(" • ")}
            {genres.length > 0 && <span className="album-header__genres"> • {genres.join(" | ")}</span>}
          </p>
        </div>
      </header>

      <nav className="action-bar" aria-label="Album actions">
        <button className="action-bar__item" type="button" onClick={shuffle} disabled={!tracks.length}>
          <ShuffleIcon />
          Shuffle
        </button>
        <button className="action-bar__item" type="button" onClick={() => withSelection((t) => engine.add(t))} disabled={!tracks.length}>
          <AddIcon />
          Add to queue
        </button>
        <button className="action-bar__item" type="button" onClick={() => withSelection((t) => engine.playNext(t))} disabled={!tracks.length}>
          <PlayNextIcon />
          Play next
        </button>
        <AddToPlaylist songIds={chosen.map((t) => t.id)} />
        {user.adminRole && (
          <Link className="action-bar__item" to={`/albums/${id}/tags`}>
            <EditIcon />
            Edit tags
          </Link>
        )}
        {user.adminRole && (
          <button
            className={`action-bar__item${deleting ? " action-bar__item--active" : ""}`}
            type="button"
            aria-pressed={deleting}
            onClick={() => setDeleting(!deleting)}
            title="Delete this album, or some of its songs, from the library and the disk"
          >
            <TrashIcon />
            Delete…
          </button>
        )}
        {selected.size > 0 && (
          <span className="selection-tag" title="Add to queue and Play next only take the ticked tracks">
            {plural(selected.size, "track")}
            <button className="selection-tag__clear" type="button" aria-label="Clear the selection" onClick={() => setSelected(new Set())}>
              ×
            </button>
          </span>
        )}
      </nav>

      {deleting && user.adminRole && (
        <AlbumsDelete
          albums={[album]}
          expanded
          onDeleted={(albumIds, songIds) => {
            // The whole album (or all its songs): off to its artist, or Browse if they went too.
            const gone = albumIds.includes(album.id) || songs.every((s) => songIds.includes(s.id));
            if (!gone) return;
            const artistId = album.artistId;
            const artistPage = artistId
              ? client.call("getArtist", { id: artistId }).then(
                  () => `/artists/${artistId}`,
                  () => "/browse",
                )
              : Promise.resolve("/browse");
            void artistPage.then((page) => navigate(page, { replace: true }));
          }}
        />
      )}

      <div className="album__body">
        <table className="tracks">
          <thead>
            <tr>
              <th className="tracks__actions" aria-label="Actions" />
              <th className="tracks__select">
                <SelectAll
                  count={selected.size}
                  total={songs.length}
                  onChange={(all) => setSelected(new Set(all ? songs.map((s) => s.id) : []))}
                />
              </th>
              <th className="tracks__number">#</th>
              <th>Title</th>
              <th className="tracks__artist-column">Artist</th>
              <th className="tracks__duration" aria-label="Duration">
                ⏱
              </th>
            </tr>
          </thead>
          <tbody>
            {songs.map((song, index) => {
              const disc = song.discNumber ?? 1;
              const discStarts = multiDisc && (index === 0 || (songs[index - 1]?.discNumber ?? 1) !== disc);
              return (
                <Fragment key={song.id}>
                  {discStarts && (
                    <tr className="tracks__disc">
                      <td colSpan={6}>
                        Disc {disc}
                        {discTitle(disc) ? ` — ${discTitle(disc)}` : ""}
                      </td>
                    </tr>
                  )}
                  <TrackRow
                    song={song}
                    current={state.current?.id === song.id}
                    onPlay={() => engine.playQueue(tracks, index)}
                    onAdd={() => engine.add([songToTrack(song)])}
                    onPlayNext={() => engine.playNext([songToTrack(song)])}
                    selected={selected.has(song.id)}
                    onToggle={() => toggle(song.id)}
                  />
                </Fragment>
              );
            })}
          </tbody>
        </table>

        <div className="album__cover-box">
          <CoverArt id={album.coverArt} size={300} className="album__cover" alt={album.name} />
          {user.adminRole && (
            <Link className="album__cover-edit" to={`/albums/${id}/cover`} title="Choose another cover" aria-label="Choose another cover">
              <EditIcon />
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

/** Ticks or clears every track; half-ticked when only some are. */
function SelectAll({ count, total, onChange }: { count: number; total: number; onChange(all: boolean): void }) {
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = count > 0 && count < total;
  }, [count, total]);
  return (
    <input
      ref={box}
      type="checkbox"
      aria-label="Select all tracks"
      checked={total > 0 && count === total}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

interface TrackRowProps {
  song: Child;
  current: boolean;
  onPlay(): void;
  onAdd(): void;
  onPlayNext(): void;
  selected: boolean;
  onToggle(): void;
}

function TrackRow({ song, current, onPlay, onAdd, onPlayNext, selected, onToggle }: TrackRowProps) {
  return (
    <tr className={`tracks__row${current ? " tracks__row--current" : ""}`} onDoubleClick={onPlay}>
      <td className="tracks__actions">
        <button className="icon-button tracks__action" type="button" title="Play" aria-label={`Play ${song.title}`} onClick={onPlay}>
          <PlayIcon />
        </button>
        <button className="icon-button tracks__action" type="button" title="Add to queue" aria-label={`Add ${song.title} to queue`} onClick={onAdd}>
          <AddIcon />
        </button>
        <button className="icon-button tracks__action" type="button" title="Play next" aria-label={`Play ${song.title} next`} onClick={onPlayNext}>
          <PlayNextIcon />
        </button>
      </td>
      <td className="tracks__select">
        <input type="checkbox" aria-label={`Select ${song.title}`} checked={selected} onChange={onToggle} />
      </td>
      <td className="tracks__number">{song.track ?? ""}</td>
      <td className="tracks__title">{song.title}</td>
      <td className="tracks__artist-column">{song.displayArtist ?? song.artist}</td>
      <td className="tracks__duration">{formatTime(song.duration)}</td>
    </tr>
  );
}
