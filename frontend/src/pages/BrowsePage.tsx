import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { ArtistIndex } from "../api/types";
import { useSubsonic } from "../api/useSubsonic";
import { RefreshIcon } from "../components/Icons";
import { plural } from "../format";

function normalize(value: string): string {
  return value.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

/** DOM id of a letter section ("#" is not usable in a URL fragment). */
function anchorId(letter: string): string {
  return letter === "#" ? "letter-other" : `letter-${letter}`;
}

function filterIndex(index: ArtistIndex[], query: string): ArtistIndex[] {
  const needle = normalize(query.trim());
  if (!needle) return index;
  return index
    .map((group) => ({ ...group, artist: group.artist.filter((a) => normalize(a.name).includes(needle)) }))
    .filter((group) => group.artist.length > 0);
}

/** Artist index: big letters, artists in columns, letter bar on the right. */
export function BrowsePage() {
  const { data, error, loading, reload } = useSubsonic("getArtists");
  const [query, setQuery] = useState("");
  const all = data?.artists.index ?? [];
  const index = useMemo(() => filterIndex(all, query), [all, query]);
  const total = all.reduce((sum, group) => sum + group.artist.length, 0);

  return (
    <div className="page browse">
      <div className="page__header">
        <h1 className="page__title">Index</h1>
        {data && <span className="text-muted">{plural(total, "artist")}</span>}
        <div className="page__tools">
          <button className="button button--ghost" type="button" onClick={reload} disabled={loading}>
            <RefreshIcon />
            Refresh
          </button>
          <input
            className="field__input page__search"
            type="search"
            placeholder="Filter"
            aria-label="Filter artists"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {loading && !data && <p className="text-muted">Loading…</p>}
      {error && (
        <div className="empty-state">
          <p className="text-error">{error.message}</p>
          <button className="button" type="button" onClick={reload}>
            Retry
          </button>
        </div>
      )}
      {data && total === 0 && (
        <div className="empty-state">
          <p>No artists yet.</p>
          <p className="text-muted">Add a music folder and run a scan in Settings.</p>
        </div>
      )}
      {data && total > 0 && index.length === 0 && <p className="text-muted">No artist matches “{query}”.</p>}

      <div className="browse__body">
        <div className="browse__groups">
          {index.map((group) => (
            <section key={group.name} id={anchorId(group.name)} className="index-group">
              <h2 className="index-group__letter">{group.name}</h2>
              <ul className="index-group__artists">
                {group.artist.map((artist) => (
                  <li key={artist.id}>
                    <Link className="index-group__artist" to={`/artists/${artist.id}`}>
                      {artist.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        {index.length > 0 && (
          <nav className="letter-rail" aria-label="Jump to letter">
            {index.map((group) => (
              <a key={group.name} className="letter-rail__letter" href={`#${anchorId(group.name)}`}>
                {group.name}
              </a>
            ))}
          </nav>
        )}
      </div>
    </div>
  );
}
