import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type ArtistInfo } from "../api/native";
import { useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { AlbumCard } from "../components/AlbumCard";
import { CoverArt } from "../components/CoverArt";
import { SongTable } from "../components/SongTable";
import { RefreshIcon } from "../components/Icons";
import { plural } from "../format";

/** Artist view: header, albums, then biography, similar artists and top songs. */
export function ArtistPage() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const { data, error, loading } = useSubsonic("getArtist", { id });
  const artist = data?.artist;
  const albums = artist?.album ?? [];
  const [info, setInfo] = useState<ArtistInfo | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setInfo(null);
    setInfoError(null);
    api
      .getArtistInfo(id)
      .then((loaded) => {
        if (!cancelled) setInfo(loaded);
      })
      .catch((e: unknown) => {
        if (!cancelled) setInfoError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setInfo(await api.refreshArtistInfo(id));
      setInfoError(null);
    } catch (e) {
      setInfoError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }, [id]);

  if (error) return <p className="text-error">{error.message}</p>;
  if (loading && !artist) return <p className="text-muted">Loading…</p>;
  if (!artist) return null;

  const picture = info?.picture;
  return (
    <div className="page">
      <header className="artist-header">
        <CoverArt
          id={picture?.coverArt ?? artist.coverArt}
          size={256}
          className={`artist-header__image${picture ? " artist-header__image--picture" : ""}`}
          alt={artist.name}
        />
        <div>
          <h1 className="artist-header__name">{artist.name}</h1>
          <span className="text-muted">{plural(albums.length, "album")}</span>
        </div>
      </header>

      <ul className="album-grid">
        {albums.map((album) => (
          <li key={album.id}>
            <AlbumCard album={album} />
          </li>
        ))}
      </ul>

      {infoError && <p className="text-error">Artist information: {infoError}</p>}
      {!info && !infoError && <p className="text-muted">Loading artist information…</p>}
      {info && (
        <ArtistDetails
          name={artist.name}
          info={info}
          admin={user.adminRole}
          refreshing={refreshing}
          onRefresh={() => void refresh()}
        />
      )}
    </div>
  );
}

function ArtistDetails({
  name,
  info,
  admin,
  refreshing,
  onRefresh,
}: {
  name: string;
  info: ArtistInfo;
  admin: boolean;
  refreshing: boolean;
  onRefresh(): void;
}) {
  const [expanded, setExpanded] = useState(false);
  const refreshButton = admin && (
    <button className="button button--ghost" type="button" disabled={refreshing} onClick={onRefresh} title="Fetch again now">
      <RefreshIcon /> {refreshing ? "Refreshing…" : "Refresh"}
    </button>
  );

  const picture = info.picture && (
    <figure className="artist-picture">
      <CoverArt id={info.picture.coverArt} size={280} className="artist-picture__image" alt={name} />
      <figcaption className="credit">
        Picture:{" "}
        {info.picture.pageUrl ? (
          <a className="link" href={info.picture.pageUrl} target="_blank" rel="noreferrer">
            {info.picture.source}
          </a>
        ) : (
          info.picture.source
        )}
      </figcaption>
    </figure>
  );

  if (!info.lastfmConfigured) {
    if (!admin && !picture) return null;
    return (
      <section className={`panel${picture ? "" : " panel--placeholder"}`}>
        <div className="panel__header">
          <h2 className="panel__title">About {name}</h2>
          {refreshButton}
        </div>
        <div className="about-body">
          <div className="about-body__text">
            {admin && (
              <p className="text-muted">
                Add a Last.fm API key in <Link className="link" to="/settings">Settings</Link> (External services) to
                show biographies, similar artists and top songs.
              </p>
            )}
          </div>
          {picture}
        </div>
      </section>
    );
  }

  const hasMore = Boolean(info.biography && info.biography !== info.summary);
  const text = expanded && info.biography ? info.biography : (info.summary ?? info.biography);
  const lastfm = info.lastfmUrl ? (
    <a className="link" href={info.lastfmUrl} target="_blank" rel="noreferrer">
      Last.fm
    </a>
  ) : (
    "Last.fm"
  );

  return (
    <>
      <section className="panel">
        <div className="panel__header">
          <h2 className="panel__title">About {name}</h2>
          {refreshButton}
        </div>
        <div className="about-body">
          <div className="about-body__text">
            {text ? (
              <div className="biography">
                {text.split(/\n\s*\n/).map((paragraph, index) => (
                  <p key={index}>{paragraph}</p>
                ))}
              </div>
            ) : (
              <p className="text-muted">Last.fm has no biography for this artist.</p>
            )}
            {hasMore && (
              <button className="button button--ghost biography__more" type="button" onClick={() => setExpanded((v) => !v)}>
                {expanded ? "Show less" : "Read more"}
              </button>
            )}
            {info.similar.length > 0 && (
              <div className="similar">
                <h3 className="similar__title">Similar artists</h3>
                <ul className="similar__list">
                  {info.similar.map((similar) =>
                    similar.id ? (
                      <li key={similar.name}>
                        <Link className="chip chip--link" to={`/artists/${similar.id}`} title="In your library">
                          {similar.name}
                        </Link>
                      </li>
                    ) : (
                      <li key={similar.name}>
                        <span className="chip">{similar.name}</span>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            )}
            <p className="credit">
              Biography and similar artists from {lastfm} (user-contributed text,{" "}
              <a className="link" href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">
                CC BY-SA
              </a>
              ).
            </p>
          </div>
          {picture}
        </div>
        {admin && info.error && <p className="text-error">Last fetch: {info.error}</p>}
      </section>

      <section className="panel">
        <h2 className="panel__title">Top songs</h2>
        {info.topSongs.length ? (
          <SongTable songs={info.topSongs} />
        ) : (
          <p className="text-muted">None of the popular songs of {name} is in the library.</p>
        )}
        <p className="credit">Popularity from {lastfm} (songs of your library only).</p>
      </section>
    </>
  );
}
