import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, type ArtistInfo } from "../api/native";
import { useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { AlbumCard } from "../components/AlbumCard";
import { CoverArt } from "../components/CoverArt";
import { SongTable } from "../components/SongTable";
import { AddIcon, DiscIcon, PlayIcon, PlayNextIcon, RefreshIcon, TrashIcon } from "../components/Icons";
import { plural } from "../format";
import { songToTrack, usePlayer, type Track } from "../player/PlayerContext";
import { MissingAlbums } from "./artist/MissingAlbums";
import { AlbumsDelete } from "./manage/DeleteTab";
import { settingsUrl } from "./settings/tabs";

/**
 * Artist view: header, actions, albums (or the missing ones, from MusicBrainz; or, for
 * admins, the albums to delete), then biography, similar artists and top songs.
 */
export function ArtistPage() {
  const { id = "" } = useParams();
  const { user, client } = useSession();
  const { engine } = usePlayer();
  const [params, setParams] = useSearchParams();
  const view = params.get("view");
  const missingView = view === "missing";
  const navigate = useNavigate();
  const [loadingSongs, setLoadingSongs] = useState(false);
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

  /** The songs of the albums shown, album after album (oldest first). */
  async function withSongs(action: (tracks: Track[]) => void) {
    setLoadingSongs(true);
    try {
      const loaded = await Promise.all(albums.map((album) => client.call("getAlbum", { id: album.id })));
      action(loaded.flatMap((response) => (response.album.song ?? []).map(songToTrack)));
    } catch (e) {
      console.error(`Cannot load the songs of artist ${id}`, e);
    } finally {
      setLoadingSongs(false);
    }
  }

  function toggleView(name: "missing" | "delete") {
    setParams(view === name ? {} : { view: name }, { replace: true });
  }

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

      <nav className="action-bar" aria-label="Artist actions">
        <button
          className="action-bar__item"
          type="button"
          disabled={!albums.length || loadingSongs}
          onClick={() => void withSongs((tracks) => engine.playQueue(tracks, 0))}
        >
          <PlayIcon />
          Play all
        </button>
        <button
          className="action-bar__item"
          type="button"
          disabled={!albums.length || loadingSongs}
          onClick={() => void withSongs((tracks) => engine.add(tracks))}
        >
          <AddIcon />
          Add to queue
        </button>
        <button
          className="action-bar__item"
          type="button"
          disabled={!albums.length || loadingSongs}
          onClick={() => void withSongs((tracks) => engine.playNext(tracks))}
        >
          <PlayNextIcon />
          Play next
        </button>
        <button
          className={`action-bar__item${missingView ? " action-bar__item--active" : ""}`}
          type="button"
          aria-pressed={missingView}
          onClick={() => toggleView("missing")}
          title="The artist's discography on MusicBrainz, compared with the library"
        >
          <DiscIcon />
          Missing albums
        </button>
        {user.adminRole && (
          <button
            className={`action-bar__item${view === "delete" ? " action-bar__item--active" : ""}`}
            type="button"
            aria-pressed={view === "delete"}
            disabled={!albums.length}
            onClick={() => toggleView("delete")}
            title="Delete albums or songs of this artist from the library and the disk"
          >
            <TrashIcon />
            Delete albums
          </button>
        )}
      </nav>

      {missingView ? (
        <MissingAlbums artistId={id} name={artist.name} admin={user.adminRole} />
      ) : view === "delete" && user.adminRole ? (
        <AlbumsDelete
          albums={albums}
          onDeleted={(albumIds) => {
            // All of them: the artist went with them (nothing left of theirs).
            if (albums.every((album) => albumIds.includes(album.id))) navigate("/browse", { replace: true });
          }}
        />
      ) : (
        <ul className="album-grid">
          {albums.map((album) => (
            <li key={album.id}>
              <AlbumCard album={album} />
            </li>
          ))}
        </ul>
      )}

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
                Add a Last.fm API key in <Link className="link" to={settingsUrl("external")}>Settings → External services</Link> to
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
