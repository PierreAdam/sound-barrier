import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { bumpCovers } from "../api/coverVersions";
import { api, type CoverResult } from "../api/native";
import { invalidateSubsonicCache, useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { CoverArt } from "../components/CoverArt";

/** Admins: choose an album's cover among the results of the cover sources (Deezer...). */
export function AlbumCoverPage() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const navigate = useNavigate();
  const { data } = useSubsonic("getAlbum", { id });
  const album = data?.album;
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CoverResult[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [selected, setSelected] = useState<CoverResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [embed, setEmbed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = useCallback(
    async (text?: string) => {
      setBusy(true);
      setError(null);
      try {
        const found = await api.searchCovers(id, text);
        setQuery(found.query);
        setResults(found.results);
        setErrors(found.errors);
        setSelected(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [id],
  );

  // First search: artist and album name.
  useEffect(() => {
    if (user.adminRole) void search();
  }, [search, user.adminRole]);

  if (!user.adminRole) return <Navigate to={`/albums/${id}`} replace />;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void search(query);
  }

  async function apply() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.setAlbumCover(id, selected.imageUrl, embed);
      invalidateSubsonicCache();
      // The same coverArt id may now be another image: every copy of it on the page reloads.
      bumpCovers(album?.coverArt, saved.coverArt);
      navigate(`/albums/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="page cover-picker">
      <div className="page__header">
        <h1 className="page__title">Album cover</h1>
        {album && (
          <Link className="link" to={`/albums/${id}`}>
            {album.artist} — {album.name}
          </Link>
        )}
      </div>

      <div className="cover-picker__compare">
        <figure className="cover-picker__figure">
          <CoverArt id={album?.coverArt} size={220} className="cover-picker__image" alt="Current cover" />
          <figcaption className="text-muted">Current</figcaption>
        </figure>
        <figure className="cover-picker__figure">
          {selected ? (
            <img className="cover cover-picker__image" src={selected.thumbnailUrl} alt="Chosen cover" />
          ) : (
            <div className="cover cover-picker__image cover-picker__empty">Pick a cover below</div>
          )}
          <figcaption className="text-muted">
            {selected ? `${selected.sourceLabel}${selected.width ? ` · ${selected.width}×${selected.height}` : ""}` : "New"}
          </figcaption>
        </figure>
        <div className="cover-picker__apply">
          <button className="button button--primary" type="button" disabled={!selected || busy} onClick={() => void apply()}>
            Use this cover
          </button>
          <label className="checkbox">
            <input type="checkbox" checked={embed} onChange={(e) => setEmbed(e.target.checked)} />
            <span>Also embed it in the audio files (600×600)</span>
          </label>
          <p className="text-muted">
            Saved as <code>cover.jpg</code> in the album folder, where players and beets find it too. The previous one
            is kept as <code>cover.previous.jpg</code>. Embedding replaces the pictures inside the files, for players
            that only read those.
          </p>
        </div>
      </div>

      <form className="cover-picker__search" onSubmit={onSubmit}>
        <input
          className="field__input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Artist and album"
          aria-label="Search covers"
        />
        <button className="button" type="submit" disabled={busy || !query.trim()}>
          Search
        </button>
      </form>
      {error && <p className="text-error">{error}</p>}
      {errors.map((message) => (
        <p key={message} className="notice">
          {message}
        </p>
      ))}
      {busy && !results && <p className="text-muted">Searching…</p>}
      {results && results.length === 0 && <p className="text-muted">No cover found: try other words.</p>}

      {results && results.length > 0 && (
        <ul className="cover-results">
          {results.map((result) => (
            <li key={result.imageUrl}>
              <button
                type="button"
                className={`cover-results__item${selected?.imageUrl === result.imageUrl ? " cover-results__item--selected" : ""}`}
                onClick={() => setSelected(result)}
                aria-pressed={selected?.imageUrl === result.imageUrl}
              >
                <img className="cover cover-results__image" src={result.thumbnailUrl} alt="" loading="lazy" />
                <span className="cover-results__title">{result.title}</span>
                <span className="cover-results__info text-muted">
                  {result.artist} · {result.sourceLabel}
                  {result.width ? ` · ${result.width}×${result.height}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
