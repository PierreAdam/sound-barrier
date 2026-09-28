import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import type { AlbumID3 } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { songToTrack, usePlayer } from "../player/PlayerContext";
import { CoverArt } from "./CoverArt";
import { AddIcon, PlayIcon } from "./Icons";

/**
 * An album in a grid: cover, name and a line of information. On hover, two buttons over
 * the cover play it (replacing the queue) or add it to the queue.
 */
export function AlbumCard({ album, info }: { album: AlbumID3; info?: ReactNode }) {
  const { client } = useSession();
  const { engine } = usePlayer();
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(false);

  async function withSongs(action: (tracks: ReturnType<typeof songToTrack>[]) => void) {
    setBusy(true);
    try {
      const response = await client.call("getAlbum", { id: album.id });
      action((response.album.song ?? []).map(songToTrack));
    } catch (e) {
      console.error(`Cannot load album ${album.id}`, e);
    } finally {
      setBusy(false);
    }
  }

  const play = () => void withSongs((tracks) => engine.playQueue(tracks, 0));
  const add = () =>
    void withSongs((tracks) => {
      engine.add(tracks);
      setAdded(true); // a short confirmation on the button
      setTimeout(() => setAdded(false), 1500);
    });

  return (
    <div className="album-card">
      <Link className="album-card__link" to={`/albums/${album.id}`} title={album.name}>
        <CoverArt id={album.coverArt} size={180} className="album-card__cover" alt="" />
        <span className="album-card__name">{album.name}</span>
        <span className="album-card__info">{info ?? album.year ?? " "}</span>
      </Link>
      <div className="album-card__actions">
        <button
          className="album-card__action"
          type="button"
          disabled={busy}
          aria-label={`Play ${album.name}`}
          title="Play (replaces the queue)"
          onClick={play}
        >
          <PlayIcon />
        </button>
        <button
          className={`album-card__action${added ? " album-card__action--done" : ""}`}
          type="button"
          disabled={busy}
          aria-label={`Add ${album.name} to the queue`}
          title={added ? "Added to the queue" : "Add to the queue"}
          onClick={add}
        >
          <AddIcon />
        </button>
      </div>
    </div>
  );
}
