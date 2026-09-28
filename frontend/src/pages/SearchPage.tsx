import { Link, useSearchParams } from "react-router-dom";

import { useSubsonic } from "../api/useSubsonic";
import { AlbumCard } from "../components/AlbumCard";
import { CoverArt } from "../components/CoverArt";
import { SongTable } from "../components/SongTable";
import { plural } from "../format";

const COUNTS = { artistCount: 20, albumCount: 30, songCount: 50 };

/** Search results (the query comes from the top bar's search field: `?q=`). */
export function SearchPage() {
  const [params] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  if (!query) {
    return (
      <div className="page">
        <h1 className="page__title">Search</h1>
        <p className="text-muted">Type an artist, an album or a song title in the search field above.</p>
      </div>
    );
  }
  return <Results query={query} />;
}

function Results({ query }: { query: string }) {
  const { data, error, loading } = useSubsonic("search3", { query, ...COUNTS });
  const result = data?.searchResult3;
  const artists = result?.artist ?? [];
  const albums = result?.album ?? [];
  const songs = result?.song ?? [];
  const nothing = result && !artists.length && !albums.length && !songs.length;

  return (
    <div className="page search">
      <div className="page__header">
        <h1 className="page__title">Search</h1>
        <span className="text-muted">“{query}”</span>
      </div>
      {error && <p className="text-error">{error.message}</p>}
      {loading && !result && <p className="text-muted">Searching…</p>}
      {nothing && <p className="text-muted">Nothing found. Try fewer or other words.</p>}

      {artists.length > 0 && (
        <section className="search__section">
          <h2 className="search__title">Artists</h2>
          <ul className="search-artists">
            {artists.map((artist) => (
              <li key={artist.id}>
                <Link className="search-artists__item" to={`/artists/${artist.id}`}>
                  <CoverArt id={artist.coverArt} size={48} className="search-artists__image" alt="" />
                  <span className="search-artists__name">{artist.name}</span>
                  <span className="text-muted">{plural(artist.albumCount ?? 0, "album")}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {albums.length > 0 && (
        <section className="search__section">
          <h2 className="search__title">Albums</h2>
          <ul className="album-grid">
            {albums.map((album) => (
              <li key={album.id}>
                <AlbumCard
                  album={album}
                  info={[album.displayArtist ?? album.artist, album.year].filter(Boolean).join(" · ")}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {songs.length > 0 && (
        <section className="search__section">
          <h2 className="search__title">Songs</h2>
          <SongTable songs={songs} showArtist />
        </section>
      )}
    </div>
  );
}
