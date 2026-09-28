import { Link } from "react-router-dom";

import type { Child } from "../api/types";
import { formatTime } from "../format";
import { songToTrack, usePlayer } from "../player/PlayerContext";
import { AddIcon, PlayIcon } from "./Icons";

/**
 * A list of songs from different albums (top songs, search results): play from a song
 * (the list becomes the queue) or add one to the queue.
 */
export function SongTable({ songs, showArtist = false }: { songs: Child[]; showArtist?: boolean }) {
  const { engine, state } = usePlayer();
  const tracks = songs.map(songToTrack);
  return (
    <table className="tracks">
      <tbody>
        {songs.map((song, index) => (
          <tr
            key={song.id}
            className={`tracks__row${state.current?.id === song.id ? " tracks__row--current" : ""}`}
            onDoubleClick={() => engine.playQueue(tracks, index)}
          >
            <td className="tracks__actions">
              <button
                className="icon-button tracks__action"
                type="button"
                title="Play (this list from here)"
                aria-label={`Play ${song.title}`}
                onClick={() => engine.playQueue(tracks, index)}
              >
                <PlayIcon />
              </button>
              <button
                className="icon-button tracks__action"
                type="button"
                title="Add to queue"
                aria-label={`Add ${song.title} to queue`}
                onClick={() => engine.add([songToTrack(song)])}
              >
                <AddIcon />
              </button>
            </td>
            <td className="tracks__number">{index + 1}</td>
            <td>{song.title}</td>
            {showArtist && (
              <td className="text-muted">
                {song.artistId ? (
                  <Link className="link" to={`/artists/${song.artistId}`}>
                    {song.displayArtist ?? song.artist}
                  </Link>
                ) : (
                  (song.displayArtist ?? song.artist)
                )}
              </td>
            )}
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
  );
}
