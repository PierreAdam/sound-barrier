import { type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { openAlbumLink } from "../../api/albumLinks";
import { api, type Discography, type MusicBrainzArtist, type PluginLinks, type ReleaseGroup } from "../../api/native";
import { CoverArt } from "../../components/CoverArt";
import { MusicNoteIcon, RefreshIcon } from "../../components/Icons";
import { usePreferences } from "../../preferences/PreferencesContext";
import { settingsUrl } from "../settings/tabs";

const DEFAULT_CATEGORIES = ["album"];
const musicbrainzUrl = (kind: "artist" | "release-group", mbid: string) => `https://musicbrainz.org/${kind}/${mbid}`;
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * The artist's discography on MusicBrainz, by category ("Album", "Album + Live"...), with
 * what the library already has. The chosen categories are a preference of the user.
 */
export function MissingAlbums({ artistId, name, admin }: { artistId: string; name: string; admin: boolean }) {
  const [discography, setDiscography] = useState<Discography | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [linking, setLinking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDiscography(null);
    setError(null);
    setLinking(false);
    api
      .getDiscography(artistId)
      .then((loaded) => {
        if (!cancelled) setDiscography(loaded);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [artistId]);

  const run = useCallback(async (action: () => Promise<Discography>) => {
    setBusy(true);
    try {
      setDiscography(await action());
      setError(null);
      setLinking(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, []);

  if (error && !discography) return <p className="text-error">Missing albums: {error}</p>;
  if (!discography) return <p className="text-muted">Looking up the discography on MusicBrainz…</p>;
  if (!discography.enabled) {
    return (
      <div className="empty-state">
        <p className="text-muted">
          MusicBrainz lookups are turned off.
          {admin && (
            <>
              {" "}
              Turn them on in <Link className="link" to={settingsUrl("external")}>Settings → External services</Link>.
            </>
          )}
        </p>
      </div>
    );
  }

  const refresh = admin && (
    <button
      className="button button--ghost"
      type="button"
      disabled={busy}
      onClick={() => void run(() => api.refreshDiscography(artistId))}
      title="Fetch again from MusicBrainz now"
    >
      <RefreshIcon /> {busy ? "Refreshing…" : "Refresh"}
    </button>
  );
  const linkForm = (
    <LinkArtist
      artistId={artistId}
      name={name}
      busy={busy}
      linked={discography.mbidSource === "manual"}
      onLink={(mbid) => run(() => api.linkMusicBrainz(artistId, mbid))}
      onCancel={discography.artistMbid ? () => setLinking(false) : undefined}
    />
  );

  if (!discography.artistMbid) {
    return (
      <div className="empty-state">
        {discography.error ? (
          <p className="text-error">MusicBrainz: {discography.error}</p>
        ) : (
          <p className="text-muted">
            {name} is not linked to a MusicBrainz artist: the files have no MusicBrainz id and the search found no
            single match.
          </p>
        )}
        {admin ? linkForm : <p className="text-muted">An admin can link it.</p>}
        {error && <p className="text-error">{error}</p>}
      </div>
    );
  }

  return (
    <section className="discography">
      <CategoryFilter
        categories={discography.categories.map((c) => ({
          key: c.key,
          label: c.label,
          count: `${c.missing}/${c.total}`,
          title: `${c.missing} missing of ${c.total}`,
        }))}
      />
      <DiscographySections artistId={artistId} discography={discography} admin={admin} />
      <div className="discography__footer">
        <p className="credit">
          Discography from{" "}
          <a className="link" href={musicbrainzUrl("artist", discography.artistMbid)} target="_blank" rel="noreferrer">
            MusicBrainz
          </a>
          {discography.mbidSource === "search" && " (artist found by name)"}
          {discography.mbidSource === "manual" && " (artist chosen by an admin)"}.
        </p>
        {admin && !linking && (
          <button className="button button--ghost" type="button" onClick={() => setLinking(true)}>
            Change MusicBrainz artist
          </button>
        )}
        {refresh}
      </div>
      {admin && linking && linkForm}
      {admin && discography.error && <p className="text-error">Last fetch: {discography.error}</p>}
      {error && <p className="text-error">{error}</p>}
    </section>
  );
}

/** A category checkbox: "Album + Live", with a count ("2/7") and its explanation. */
export interface FilterCategory {
  key: string;
  label: string;
  count: string;
  title: string;
}

/** The categories the user chose (shared by Missing albums and New releases). */
export function useChosenCategories(): Set<string> {
  const { preferences } = usePreferences();
  return new Set(preferences?.discography.categories ?? DEFAULT_CATEGORIES);
}

/** One checkbox per category; the choice is saved for all artists (and New releases). */
export function CategoryFilter({ categories }: { categories: FilterCategory[] }) {
  const { preferences, update } = usePreferences();
  const chosen = useChosenCategories();

  function choose(change: (current: Set<string>) => void) {
    update((current) => {
      const next = new Set(current.discography.categories);
      change(next);
      return { ...current, discography: { ...current.discography, categories: [...next].sort() } };
    });
  }
  const keys = categories.map((c) => c.key);

  return (
    <div className="discography__filter" role="group" aria-label="Categories">
      {categories.map((category) => (
        <label key={category.key} className="checkbox discography__category">
          <input
            type="checkbox"
            checked={chosen.has(category.key)}
            disabled={!preferences}
            onChange={(e) =>
              choose((next) => (e.target.checked ? next.add(category.key) : next.delete(category.key)))
            }
          />
          {category.label}
          <span className="discography__count" title={category.title}>
            {category.count}
          </span>
        </label>
      ))}
      <span className="discography__shortcuts">
        <button className="link-button" type="button" disabled={!preferences} onClick={() => choose((next) => keys.forEach((k) => next.add(k)))}>
          All
        </button>
        <button className="link-button" type="button" disabled={!preferences} onClick={() => choose((next) => keys.forEach((k) => next.delete(k)))}>
          None
        </button>
        <button
          className="link-button"
          type="button"
          disabled={!preferences}
          title="Tick the unticked categories, untick the others"
          onClick={() => choose((next) => keys.forEach((k) => (next.has(k) ? next.delete(k) : next.add(k))))}
        >
          Inverse
        </button>
      </span>
    </div>
  );
}

function DiscographySections({
  artistId,
  discography,
  admin,
}: {
  artistId: string;
  discography: Discography;
  admin: boolean;
}) {
  const chosen = useChosenCategories();
  const shown = discography.categories.filter((c) => chosen.has(c.key));

  if (!discography.releaseGroups.length) return <p className="text-muted">MusicBrainz lists no release for this artist.</p>;
  if (!shown.length) return <p className="text-muted">Choose one or more categories above.</p>;
  const missing = shown.reduce((sum, c) => sum + c.missing, 0);

  return (
    <>
      {missing === 0 && <p className="text-muted">Nothing missing in these categories: the library has them all.</p>}
      {shown.map((category) => (
        <div key={category.key} className="discography__section">
          <h3 className="discography__title">
            {category.label} <span className="text-muted">({category.missing} missing)</span>
          </h3>
          <ul className="album-grid">
            {discography.releaseGroups
              .filter((group) => group.category === category.key)
              .map((group) => (
                <li key={group.mbid}>
                  <ReleaseGroupCard artistId={artistId} group={group} admin={admin} />
                </li>
              ))}
          </ul>
        </div>
      ))}
    </>
  );
}

/**
 * A release group: owned ones link to the album page; missing ones open the ways to find
 * them (admins) or MusicBrainz. `details` replaces the year line (e.g. artist and date).
 */
export function ReleaseGroupCard({
  artistId,
  group,
  admin,
  details,
}: {
  artistId: string;
  group: ReleaseGroup;
  admin: boolean;
  details?: ReactNode;
}) {
  const year = group.firstReleaseDate?.slice(0, 4);
  const info = (
    <span className="album-card__info">
      {details ?? year ?? " "}
      {group.upcoming && <span className="badge discography__upcoming">Upcoming</span>}
    </span>
  );

  if (group.owned) {
    return (
      <div className="album-card release-card release-card--owned">
        <Link className="album-card__link" to={`/albums/${group.owned.albumId}`} title={`${group.owned.name} (in your library)`}>
          <span className="release-card__cover">
            <CoverArt id={group.owned.coverArt ?? undefined} size={320} className="album-card__cover" alt="" />
            <span className="release-card__owned">✓ In library</span>
          </span>
          <span className="album-card__name">{group.title}</span>
          {info}
        </Link>
      </div>
    );
  }
  const content = (
    <>
      <RemoteCover src={api.discographyCoverUrl(artistId, group.mbid)} />
      <span className="album-card__name">{group.title}</span>
      {info}
    </>
  );
  if (admin) return <FindAlbum artistId={artistId} group={group}>{content}</FindAlbum>;
  return (
    <div className="album-card release-card">
      <a
        className="album-card__link"
        href={musicbrainzUrl("release-group", group.mbid)}
        target="_blank"
        rel="noreferrer"
        title={`${group.title} (on MusicBrainz)`}
      >
        {content}
      </a>
    </div>
  );
}

/** Admins: the card opens a menu of ways to find the album (the plugins' links). */
function FindAlbum({ artistId, group, children }: { artistId: string; group: ReleaseGroup; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [found, setFound] = useState<PluginLinks[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle() {
    setOpen((v) => !v);
    if (found || open) return;
    api
      .getReleaseGroupLinks(artistId, group.mbid)
      .then(setFound)
      .catch((e: unknown) => setError(errorText(e)));
  }

  return (
    <div className="release-menu" ref={menu}>
      <div className="album-card release-card">
        <button
          className="album-card__link release-card__button"
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          title={`Find “${group.title}”`}
          onClick={toggle}
        >
          {children}
        </button>
      </div>
      {open && (
        <div className="release-menu__panel" role="menu">
          <p className="release-menu__title">Find “{group.title}”</p>
          {error && <p className="text-error">{error}</p>}
          {!found && !error && <p className="text-muted">Loading…</p>}
          {found?.length === 0 && (
            <p className="text-muted">
              No search site: add some in <Link className="link" to={settingsUrl("album-search")}>Settings → Album search</Link>.
            </p>
          )}
          {found?.map((plugin) => (
            <div key={plugin.plugin} className="release-menu__group">
              {found.length > 1 && <p className="release-menu__plugin">{plugin.name}</p>}
              {plugin.links.map((link) => (
                <button
                  key={link.label + link.url}
                  className="release-menu__item"
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    openAlbumLink(link);
                    setOpen(false);
                  }}
                >
                  <LinkIcon src={link.iconUrl} />
                  {link.label}
                  {link.method === "POST" && <span className="release-menu__method">POST</span>}
                </button>
              ))}
            </div>
          ))}
          <a
            className="release-menu__item release-menu__item--musicbrainz"
            role="menuitem"
            href={musicbrainzUrl("release-group", group.mbid)}
            target="_blank"
            rel="noreferrer"
            onClick={() => setOpen(false)}
          >
            <LinkIcon src={null} />
            View on MusicBrainz
          </a>
        </div>
      )}
    </div>
  );
}

function LinkIcon({ src }: { src: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className="release-menu__icon release-menu__icon--none" aria-hidden />;
  return <img className="release-menu__icon" src={src} alt="" onError={() => setFailed(true)} />;
}

/** A cover served by our API (found automatically), or the placeholder. */
function RemoteCover({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className="cover album-card__cover cover--placeholder" aria-hidden>
        <MusicNoteIcon />
      </div>
    );
  }
  return <img className="cover album-card__cover" src={src} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

/** Admins: choose the MusicBrainz artist among search results, or paste its id / URL. */
function LinkArtist({
  artistId,
  name,
  busy,
  linked,
  onLink,
  onCancel,
}: {
  artistId: string;
  name: string;
  busy: boolean;
  linked: boolean; // an admin already chose one
  onLink(mbid: string | null): Promise<void>;
  onCancel?: () => void;
}) {
  const [query, setQuery] = useState(name);
  const [candidates, setCandidates] = useState<MusicBrainzArtist[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [manual, setManual] = useState("");

  const search = useCallback(
    async (text: string) => {
      setSearching(true);
      try {
        setCandidates(await api.searchMusicBrainzArtists(artistId, text));
        setSearchError(null);
      } catch (e) {
        setSearchError(errorText(e));
      } finally {
        setSearching(false);
      }
    },
    [artistId],
  );

  useEffect(() => {
    void search(name);
  }, [search, name]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) void search(query.trim());
  }
  function onManual(event: FormEvent) {
    event.preventDefault();
    if (manual.trim()) void onLink(manual.trim());
  }

  const describe = (c: MusicBrainzArtist) =>
    [c.disambiguation, c.type, c.country, c.begin && `${c.begin.slice(0, 4)}–${c.end?.slice(0, 4) ?? ""}`]
      .filter(Boolean)
      .join(" · ");

  return (
    <div className="mb-link">
      <h3 className="mb-link__title">Link to a MusicBrainz artist</h3>
      <form className="folder-form__row" onSubmit={onSearch}>
        <input className="field__input" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Artist name" />
        <button className="button" type="submit" disabled={searching || !query.trim()}>
          {searching ? "Searching…" : "Search"}
        </button>
      </form>
      {searchError && <p className="text-error">{searchError}</p>}
      {candidates && !candidates.length && <p className="text-muted">No artist found on MusicBrainz.</p>}
      {candidates && candidates.length > 0 && (
        <ul className="mb-link__candidates">
          {candidates.map((candidate) => (
            <li key={candidate.mbid} className="mb-link__candidate">
              <div>
                <a className="link" href={musicbrainzUrl("artist", candidate.mbid)} target="_blank" rel="noreferrer">
                  {candidate.name}
                </a>
                <span className="text-muted"> {describe(candidate)}</span>
              </div>
              <button className="button button--primary" type="button" disabled={busy} onClick={() => void onLink(candidate.mbid)}>
                This one
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="folder-form__row" onSubmit={onManual}>
        <input
          className="field__input"
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="MusicBrainz artist id or https://musicbrainz.org/artist/… URL"
          aria-label="MusicBrainz artist id"
          spellCheck={false}
        />
        <button className="button button--primary" type="submit" disabled={busy || !manual.trim()}>
          Link
        </button>
      </form>
      <div className="mb-link__actions">
        {linked && (
          <button className="button button--ghost" type="button" disabled={busy} onClick={() => void onLink(null)}>
            Use the files' id / the search again
          </button>
        )}
        {onCancel && (
          <button className="button button--ghost" type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
