import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { invalidateSubsonicCache, useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { CoverArt } from "../components/CoverArt";
import { AddIcon, PlayIcon, RemoveIcon, ShuffleIcon, TrashIcon } from "../components/Icons";
import { formatTime, plural } from "../format";
import { songToTrack, usePlayer } from "../player/PlayerContext";

/** One playlist: play it, and for its owner rename, make public, remove songs, delete. */
export function PlaylistPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { client, user } = useSession();
  const { engine, state } = usePlayer();
  const { data, error, loading } = useSubsonic("getPlaylist", { id });
  const [renaming, setRenaming] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const playlist = data?.playlist;
  const songs = playlist?.entry ?? [];
  const tracks = songs.map(songToTrack);

  if (error) return <p className="text-error">{error.message}</p>;
  if (loading && !playlist) return <p className="text-muted">Loading…</p>;
  if (!playlist) return null;
  const owner = playlist.owner === user.username || user.adminRole;

  async function change(action: () => Promise<unknown>) {
    setProblem(null);
    try {
      await action();
      invalidateSubsonicCache();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault();
    const name = (renaming ?? "").trim();
    if (!name || !playlist) return;
    setRenaming(null);
    void change(() => client.call("updatePlaylist", { playlistId: playlist.id, name }));
  }

  async function remove() {
    if (!playlist || !window.confirm(`Delete the playlist “${playlist.name}”? The songs stay in the library.`)) return;
    await change(() => client.call("deletePlaylist", { id: playlist.id }));
    navigate("/playlists");
  }

  return (
    <div className="page album">
      <header className="album-header">
        <CoverArt id={playlist.coverArt} size={64} className="album-header__artist-image playlist__cover" alt="" />
        <div className="album-header__meta">
          <Link className="album-header__artist" to="/playlists">
            Playlists · {playlist.owner}
          </Link>
          <div className="album-header__title-row">
            {renaming !== null ? (
              <form className="playlist__rename" onSubmit={rename}>
                <input className="field__input" value={renaming} onChange={(e) => setRenaming(e.target.value)} autoFocus aria-label="Playlist name" />
                <button className="button button--primary" type="submit">
                  Save
                </button>
                <button className="button button--ghost" type="button" onClick={() => setRenaming(null)}>
                  Cancel
                </button>
              </form>
            ) : (
              <h1 className="album-header__title">{playlist.name}</h1>
            )}
            <button
              className="icon-button icon-button--primary album-header__play"
              type="button"
              aria-label="Play playlist"
              disabled={!tracks.length}
              onClick={() => engine.playQueue(tracks, 0)}
            >
              <PlayIcon />
            </button>
          </div>
          <p className="album-header__facts">
            {plural(playlist.songCount, "song")} • {formatTime(playlist.duration)}
            {playlist.public && <span className="badge playlist__badge">public</span>}
          </p>
        </div>
      </header>

      <nav className="action-bar" aria-label="Playlist actions">
        <button
          className="action-bar__item"
          type="button"
          disabled={!tracks.length}
          onClick={() => {
            if (!state.shuffle) engine.toggleShuffle();
            engine.playQueue(tracks, Math.floor(Math.random() * tracks.length));
          }}
        >
          <ShuffleIcon />
          Shuffle
        </button>
        <button className="action-bar__item" type="button" disabled={!tracks.length} onClick={() => engine.add(tracks)}>
          <AddIcon />
          Add to queue
        </button>
        {owner && (
          <>
            <button className="action-bar__item" type="button" onClick={() => setRenaming(playlist.name)}>
              Rename
            </button>
            <button
              className="action-bar__item"
              type="button"
              onClick={() => void change(() => client.call("updatePlaylist", { playlistId: playlist.id, public: !playlist.public }))}
              title="Public playlists are visible to the other users"
            >
              {playlist.public ? "Make private" : "Make public"}
            </button>
            <button className="action-bar__item" type="button" onClick={() => void remove()}>
              <TrashIcon />
              Delete
            </button>
          </>
        )}
      </nav>
      {problem && <p className="text-error">{problem}</p>}

      {songs.length === 0 ? (
        <p className="text-muted">This playlist is empty: add songs from an album (“Add to playlist”) or from the queue.</p>
      ) : (
        <table className="tracks">
          <tbody>
            {songs.map((song, index) => (
              <tr
                key={`${song.id}-${index}`}
                className={`tracks__row${state.current?.id === song.id ? " tracks__row--current" : ""}`}
                onDoubleClick={() => engine.playQueue(tracks, index)}
              >
                <td className="tracks__actions">
                  <button className="icon-button tracks__action" type="button" title="Play from here" aria-label={`Play ${song.title}`} onClick={() => engine.playQueue(tracks, index)}>
                    <PlayIcon />
                  </button>
                  <button className="icon-button tracks__action" type="button" title="Add to queue" aria-label={`Add ${song.title} to queue`} onClick={() => engine.add([songToTrack(song)])}>
                    <AddIcon />
                  </button>
                  {owner && (
                    <button
                      className="icon-button tracks__action"
                      type="button"
                      title="Remove from the playlist"
                      aria-label={`Remove ${song.title} from the playlist`}
                      onClick={() => void change(() => client.call("updatePlaylist", { playlistId: playlist.id, songIndexToRemove: index }))}
                    >
                      <RemoveIcon />
                    </button>
                  )}
                </td>
                <td className="tracks__number">{index + 1}</td>
                <td>{song.title}</td>
                <td className="text-muted">
                  {song.artistId ? (
                    <Link className="link" to={`/artists/${song.artistId}`}>
                      {song.displayArtist ?? song.artist}
                    </Link>
                  ) : (
                    (song.displayArtist ?? song.artist)
                  )}
                </td>
                <td className="text-muted">
                  {song.albumId ? (
                    <Link className="link" to={`/albums/${song.albumId}`}>
                      {song.album}
                    </Link>
                  ) : (
                    song.album
                  )}
                </td>
                <td className="tracks__duration">{formatTime(song.duration ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
