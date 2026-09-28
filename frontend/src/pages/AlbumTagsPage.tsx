import { type FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { type AlbumTags, api } from "../api/native";
import { invalidateSubsonicCache } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";

/** Admins: edit an album's tags (written into the files, then rescanned). */
export function AlbumTagsPage() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const navigate = useNavigate();
  const [tags, setTags] = useState<AlbumTags | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user.adminRole) return;
    api
      .getAlbumTags(id)
      .then(setTags)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [id, user.adminRole]);

  if (!user.adminRole) return <Navigate to={`/albums/${id}`} replace />;
  if (!tags) return error ? <p className="text-error">{error}</p> : <p className="text-muted">Loading…</p>;

  function set(update: Partial<AlbumTags>) {
    setTags((current) => (current ? { ...current, ...update } : current));
  }

  function setTrack(index: number, update: Partial<AlbumTags["tracks"][number]>) {
    setTags((current) =>
      current ? { ...current, tracks: current.tracks.map((t, i) => (i === index ? { ...t, ...update } : t)) } : current,
    );
  }

  function number(value: string): number | null {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!tags) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.setAlbumTags(id, tags);
      invalidateSubsonicCache();
      navigate(`/albums/${saved.albumId ?? id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="page tag-editor">
      <div className="page__header">
        <h1 className="page__title">Edit tags</h1>
        <Link className="link" to={`/albums/${id}`}>
          Back to the album
        </Link>
      </div>
      <p className="text-muted">
        Written into the audio files (and beets' database for the files it knows): the web UI and every Subsonic app
        show the change. File and folder names are not changed.
      </p>

      <form className="tag-editor__form" onSubmit={(e) => void save(e)}>
        <div className="tag-editor__album">
          <label className="field">
            <span className="field__label">Album</span>
            <input className="field__input" value={tags.album} onChange={(e) => set({ album: e.target.value })} required />
          </label>
          <label className="field">
            <span className="field__label">Album artist</span>
            <input className="field__input" value={tags.albumArtist ?? ""} onChange={(e) => set({ albumArtist: e.target.value })} />
          </label>
          <label className="field tag-editor__short">
            <span className="field__label">Year</span>
            <input
              className="field__input"
              inputMode="numeric"
              value={tags.year ?? ""}
              onChange={(e) => set({ year: number(e.target.value) })}
            />
          </label>
          <label className="field">
            <span className="field__label">Genre</span>
            <input className="field__input" value={tags.genre ?? ""} onChange={(e) => set({ genre: e.target.value })} />
          </label>
          <label className="checkbox tag-editor__compilation">
            <input type="checkbox" checked={tags.compilation} onChange={(e) => set({ compilation: e.target.checked })} />
            <span>Compilation (various artists)</span>
          </label>
        </div>

        <div className="tag-editor__tracks-header">
          <h2 className="settings-section__title">Tracks</h2>
          <button
            className="button button--ghost"
            type="button"
            onClick={() => set({ tracks: tags.tracks.map((t) => ({ ...t, artist: tags.albumArtist })) })}
            title="Every track artist becomes the album artist"
          >
            Use the album artist for every track
          </button>
        </div>
        <table className="tracks tag-editor__tracks">
          <thead>
            <tr>
              <th>Disc</th>
              <th>#</th>
              <th>Title</th>
              <th>Artist</th>
              <th>File</th>
            </tr>
          </thead>
          <tbody>
            {tags.tracks.map((track, index) => (
              <tr key={track.id}>
                <td className="tag-editor__number">
                  <input
                    className="field__input"
                    inputMode="numeric"
                    aria-label="Disc"
                    value={track.disc ?? ""}
                    onChange={(e) => setTrack(index, { disc: number(e.target.value) })}
                  />
                </td>
                <td className="tag-editor__number">
                  <input
                    className="field__input"
                    inputMode="numeric"
                    aria-label="Track number"
                    value={track.track ?? ""}
                    onChange={(e) => setTrack(index, { track: number(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    className="field__input"
                    aria-label="Title"
                    value={track.title}
                    required
                    onChange={(e) => setTrack(index, { title: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="field__input"
                    aria-label="Artist"
                    value={track.artist ?? ""}
                    onChange={(e) => setTrack(index, { artist: e.target.value })}
                  />
                </td>
                <td className="tag-editor__file text-muted" title={track.path}>
                  {track.path.split("/").pop()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {error && <p className="text-error">{error}</p>}
        <div className="settings-section__actions">
          <button className="button button--primary" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save the tags"}
          </button>
        </div>
      </form>
    </div>
  );
}
