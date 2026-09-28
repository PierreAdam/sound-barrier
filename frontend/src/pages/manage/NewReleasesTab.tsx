import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type NewRelease, type NewReleases } from "../../api/native";
import { plural } from "../../format";
import { usePreferences } from "../../preferences/PreferencesContext";
import { CategoryFilter, ReleaseGroupCard, useChosenCategories } from "../artist/MissingAlbums";
import { settingsUrl } from "../settings/tabs";

const POLL_MS = 2000;
const DEFAULT_MONTHS = 6;
const MONTH_CHOICES = Array.from({ length: 12 }, (_, i) => i + 1);
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** "12 Nov 2026", "Nov 2026" or "2026 (month unknown)", at the precision MusicBrainz has. */
function releaseDate(release: NewRelease): string {
  const value = release.firstReleaseDate ?? "";
  if (value.length === 10) return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { dateStyle: "medium" });
  if (value.length === 7)
    return new Date(`${value}-15T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" });
  return value ? `${value} (month unknown)` : "";
}

/**
 * Recent and upcoming releases of the library's artists that the library does not have.
 * The discographies are refreshed on the server (MusicBrainz: one request per second):
 * the page shows the progress first, then the releases.
 */
export function NewReleasesTab() {
  const { preferences, update } = usePreferences();
  const months = preferences?.discography.recentMonths ?? DEFAULT_MONTHS;
  const chosen = useChosenCategories();
  const [data, setData] = useState<NewReleases | null>(null);
  const [error, setError] = useState<string | null>(null);
  const syncAsked = useRef(false);

  const load = useCallback(async () => {
    try {
      setData(await api.getNewReleases(months));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [months]);

  useEffect(() => {
    void load();
  }, [load]);

  // Old discographies: fetch them (once per visit), then follow the progress.
  const running = data?.sync.running ?? false;
  useEffect(() => {
    if (!data?.enabled || running || data.stale === 0 || syncAsked.current) return;
    syncAsked.current = true;
    api
      .syncNewReleases()
      .then(() => load())
      .catch((e: unknown) => setError(errorText(e)));
  }, [data, running, load]);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [running, load]);

  function setMonths(value: number) {
    update((current) => ({ ...current, discography: { ...current.discography, recentMonths: value } }));
  }

  if (error && !data) return <p className="text-error">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  if (!data.enabled) {
    return (
      <div className="empty-state">
        <p className="text-muted">
          MusicBrainz lookups are turned off: turn them on in{" "}
          <Link className="link" to={settingsUrl("external")}>
            Settings → External services
          </Link>
          .
        </p>
      </div>
    );
  }

  const sync = data.sync;
  const waiting = sync.running || (data.stale > 0 && !syncAsked.current);
  const upcoming = data.upcoming.filter((r) => chosen.has(r.category));
  const recent = data.recent.filter((r) => chosen.has(r.category));

  return (
    <section className="new-releases">
      <div className="new-releases__tools">
        <label className="field field--inline">
          <span className="field__label">Released in the last</span>
          <select className="field__input" value={months} disabled={!preferences} onChange={(e) => setMonths(Number(e.target.value))}>
            {MONTH_CHOICES.map((n) => (
              <option key={n} value={n}>
                {plural(n, "month")}
              </option>
            ))}
          </select>
        </label>
        <span className="text-muted">{plural(data.artists, "artist")} of the library checked on MusicBrainz</span>
      </div>

      {waiting ? (
        <SyncProgress data={data} />
      ) : (
        <>
          {sync.errors > 0 && (
            <p className="text-warning">
              {plural(sync.errors, "artist")} could not be checked (MusicBrainz unreachable or busy): they will be tried
              again next time.
            </p>
          )}
          {data.categories.length > 0 && (
            <CategoryFilter
              categories={data.categories.map((c) => ({
                key: c.key,
                label: c.label,
                count: String(c.count),
                title: plural(c.count, "release"),
              }))}
            />
          )}
          {data.categories.length > 0 && !upcoming.length && !recent.length && (
            <p className="text-muted">Choose one or more categories above.</p>
          )}
          <Releases title="Upcoming" releases={upcoming} empty="No announced release." />
          <Releases
            title={`Released in the last ${plural(months, "month")}`}
            releases={recent}
            empty="Nothing new that the library does not have."
          />
          {data.unlinked.length > 0 && <Unlinked artists={data.unlinked} />}
        </>
      )}
      {error && <p className="text-error">{error}</p>}
    </section>
  );
}

function SyncProgress({ data }: { data: NewReleases }) {
  const { total, done, current } = data.sync;
  const percent = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="empty-state new-releases__progress">
      <p>
        Checking MusicBrainz: {done} of {plural(total || data.stale, "artist")}
        {current && <span className="text-muted"> — {current}</span>}
      </p>
      <div className="meter" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="meter__fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="text-muted">
        One artist per second (MusicBrainz' limit). This goes on on the server if you leave the page; the results
        are then kept for a day.
      </p>
    </div>
  );
}

function Releases({ title, releases, empty }: { title: string; releases: NewRelease[]; empty: string }) {
  return (
    <div className="discography__section">
      <h3 className="discography__title">
        {title} <span className="text-muted">({releases.length})</span>
      </h3>
      {releases.length ? (
        <ul className="album-grid">
          {releases.map((release) => (
            <li key={`${release.artistId}-${release.mbid}`}>
              <ReleaseGroupCard
                artistId={release.artistId}
                group={release}
                admin
                details={`${release.artistName} · ${releaseDate(release)}`}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">{empty}</p>
      )}
    </div>
  );
}

function Unlinked({ artists }: { artists: { id: string; name: string }[] }) {
  return (
    <div className="discography__section">
      <h3 className="discography__title">
        Not linked to MusicBrainz <span className="text-muted">({artists.length})</span>
      </h3>
      <p className="text-muted">
        Their releases cannot be checked. Link them from their page (Missing albums → Link to a MusicBrainz artist).
      </p>
      <ul className="similar__list">
        {artists.map((artist) => (
          <li key={artist.id}>
            <Link className="chip chip--link" to={`/artists/${artist.id}?view=missing`}>
              {artist.name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
