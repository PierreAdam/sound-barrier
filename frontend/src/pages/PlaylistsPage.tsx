import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { invalidateSubsonicCache, useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { CoverArt } from "../components/CoverArt";
import { formatTime, plural } from "../format";

/** The user's playlists and the public ones of other users. */
export function PlaylistsPage() {
  const { client, user } = useSession();
  const navigate = useNavigate();
  const { data, error, loading } = useSubsonic("getPlaylists");
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const playlists = data?.playlists.playlist ?? [];
  const mine = playlists.filter((p) => p.owner === user.username);
  const others = playlists.filter((p) => p.owner !== user.username);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await client.call("createPlaylist", { name: name.trim() });
      invalidateSubsonicCache();
      navigate(`/playlists/${created.playlist.id}`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">Playlists</h1>
        <form className="playlists__new" onSubmit={(e) => void create(e)}>
          <input
            className="field__input"
            placeholder="New playlist"
            aria-label="New playlist name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="button button--primary" type="submit" disabled={creating || !name.trim()}>
            Create
          </button>
        </form>
      </div>
      {error && <p className="text-error">{error.message}</p>}
      {loading && !data && <p className="text-muted">Loading…</p>}
      {data && !playlists.length && (
        <p className="text-muted">
          No playlist yet. Create one here, or use “Save as playlist” in the queue and “Add to playlist” on an album.
        </p>
      )}
      <PlaylistGrid playlists={mine} />
      {others.length > 0 && (
        <>
          <h2 className="playlists__title">Shared by other users</h2>
          <PlaylistGrid playlists={others} showOwner />
        </>
      )}
    </div>
  );
}

function PlaylistGrid({
  playlists,
  showOwner = false,
}: {
  playlists: { id: string; name: string; owner: string; songCount: number; duration: number; coverArt?: string; public: boolean }[];
  showOwner?: boolean;
}) {
  return (
    <ul className="album-grid">
      {playlists.map((p) => (
        <li key={p.id}>
          <div className="album-card">
            <Link className="album-card__link" to={`/playlists/${p.id}`} title={p.name}>
              <CoverArt id={p.coverArt} size={180} className="album-card__cover" alt="" />
              <span className="album-card__name">{p.name}</span>
              <span className="album-card__info">
                {[showOwner ? p.owner : null, plural(p.songCount, "song"), formatTime(p.duration), p.public && !showOwner ? "public" : null]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </Link>
          </div>
        </li>
      ))}
    </ul>
  );
}
