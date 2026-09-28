import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type LibraryStatus } from "../../api/native";
import { RefreshIcon } from "../../components/Icons";
import { formatSize, plural } from "../../format";
import type { Imports } from "./useImports";

// MusicBrainz answers about once a second and an album takes a few requests.
const SECONDS_PER_ALBUM = 5;

function duration(albums: number): string {
  const minutes = Math.ceil((albums * SECONDS_PER_ALBUM) / 60);
  return minutes < 60 ? `about ${plural(minutes, "minute")}` : `about ${Math.round(minutes / 60)} h`;
}

/** The library against beets' database, and beets maintenance. */
export function LibraryTab({ imports, onReview }: { imports: Imports; onReview(): void }) {
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await api.getLibraryStatus());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Adopted albums change the counts: reload when some finish.
  const adopted = imports.jobs
    .filter((job) => job.kind === "adopt")
    .flatMap((job) => job.tasks)
    .filter((task) => task.status === "imported").length;
  const lastAdopted = useRef(adopted);
  useEffect(() => {
    if (adopted !== lastAdopted.current) void load();
    lastAdopted.current = adopted;
  }, [adopted, load]);

  const folders = status?.unknownFolders ?? [];
  const shown = useMemo(() => {
    const words = filter.trim().toLowerCase();
    if (!words) return folders;
    return folders.filter((f) => `${f.artist} ${f.album} ${f.path}`.toLowerCase().includes(words));
  }, [folders, filter]);

  async function adopt(paths: string[]) {
    if (!paths.length) return;
    const what = plural(paths.length, "album");
    if (
      !window.confirm(
        `Add ${what} to beets?\n\nEach album is matched on MusicBrainz and its tags are rewritten in the files ` +
          `(the files are not moved or renamed). Unclear matches wait in Review. This takes ${duration(paths.length)}.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api.adopt(paths);
      await imports.refresh();
      setSelected(new Set());
      setMessage(`Started: ${what}. Progress is in Import → Recent imports; decisions to take appear in Review.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function forgetMissing() {
    if (!status) return;
    const what = plural(status.taggerMissing, "entry", "entries");
    if (!window.confirm(`Remove ${what} from beets' database? Their files no longer exist; nothing is deleted from disk.`)) {
      return;
    }
    setBusy(true);
    try {
      const { removed } = await api.forgetMissing();
      setMessage(`Removed ${plural(removed, "entry", "entries")} from beets' database.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function cleanup() {
    setBusy(true);
    setMessage(null);
    try {
      const done = await api.cleanup();
      const parts = [
        done.beetsBackups && plural(done.beetsBackups, "beets backup"),
        done.beetsMissing && plural(done.beetsMissing, "beets entry without file", "beets entries without file"),
        done.stagingFolders && plural(done.stagingFolders, "staging folder"),
        done.cachedCovers && plural(done.cachedCovers, "old cached cover"),
        done.artistPictures && plural(done.artistPictures, "unused artist picture"),
      ].filter(Boolean);
      setMessage(parts.length ? `Cleaned up: ${parts.join(", ")}.` : "Nothing to clean up.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function toggle(path: string) {
    const next = new Set(selected);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setSelected(next);
  }

  if (!status) {
    return (
      <section className="settings-section settings-section--wide">
        <h2 className="settings-section__title">Library</h2>
        {error ? <p className="text-error">{error}</p> : <p className="text-muted">Loading…</p>}
      </section>
    );
  }

  const coverage = status.songs ? Math.round((status.taggerSongs / status.songs) * 100) : 100;

  return (
    <>
      <section className="settings-section settings-section--wide">
        <div className="library-status__header">
          <h2 className="settings-section__title">Library</h2>
          <div className="library-status__buttons">
            <button
              className="button button--ghost"
              type="button"
              onClick={() => void cleanup()}
              disabled={busy}
              title="Also done automatically every day: beets leftovers, staging folders, old cached covers"
            >
              Clean up now
            </button>
            <button className="button button--ghost" type="button" onClick={() => void load()} disabled={loading}>
              <RefreshIcon /> Refresh
            </button>
          </div>
        </div>
        <dl className="library-status">
          <dt>Folder</dt>
          <dd>
            <code>{status.libraryPath}</code>
          </dd>
          <dt>Library</dt>
          <dd>
            {plural(status.albums, "album")} · {plural(status.songs, "song")} ·{" "}
            <span title="Space taken by the music files on the disk">{formatSize(status.sizeBytes)}</span>
          </dd>
          <dt>Tagging</dt>
          <dd>{status.tagger}</dd>
          {status.hasTaggerDatabase && (
            <>
              <dt>In beets</dt>
              <dd>
                {plural(status.taggerSongs, "song")} of {status.songs} ({coverage} %) ·{" "}
                {plural(status.taggerAlbums, "album")} in its database
                <div className="meter" aria-hidden="true">
                  <div className="meter__fill" style={{ width: `${coverage}%` }} />
                </div>
              </dd>
            </>
          )}
        </dl>
        {!status.hasTaggerDatabase && (
          <p className="notice">This tagger keeps no database of its own: there is no beets maintenance to do.</p>
        )}
        {status.taggerMissing > 0 && (
          <div className="library-status__issue">
            <span>
              {plural(status.taggerMissing, "entry", "entries")} of beets' database point to files that no longer
              exist.
            </span>
            <button className="button" type="button" disabled={busy} onClick={() => void forgetMissing()}>
              Remove them from beets
            </button>
          </div>
        )}
        {message && <p className="text-success">{message}</p>}
        {error && <p className="text-error">{error}</p>}
        {imports.review.length > 0 && (
          <p>
            <button className="button button--ghost" type="button" onClick={onReview}>
              {plural(imports.review.length, "album")} waiting in Review
            </button>
          </p>
        )}
      </section>

      {status.hasTaggerDatabase && (
        <section className="settings-section settings-section--wide">
          <h2 className="settings-section__title">Not in beets ({status.unknownFolderCount})</h2>
          {status.unknownFolderCount === 0 ? (
            <p className="text-muted">Every album of the library is in beets' database.</p>
          ) : (
            <>
              <p className="text-muted">
                Album folders of the library that beets does not know (e.g. added before Sound-Barrier, or by
                hand). Adding them matches them on MusicBrainz like an import: tags are rewritten in place, files
                are neither moved nor renamed.
              </p>
              {status.unknownFolderCount > folders.length && (
                <p className="notice">
                  Showing the first {folders.length}: add them, then refresh to see the others.
                </p>
              )}
              <div className="library-status__toolbar">
                <input
                  className="field__input"
                  placeholder="Filter by artist, album or folder"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <button
                  className="button button--primary"
                  type="button"
                  disabled={busy || selected.size === 0}
                  onClick={() => void adopt([...selected])}
                >
                  Add selected to beets ({selected.size})
                </button>
                <button
                  className="button"
                  type="button"
                  disabled={busy || shown.length === 0}
                  onClick={() => void adopt(shown.map((f) => f.path))}
                >
                  Add all shown ({shown.length})
                </button>
              </div>
              <ul className="unknown-folders">
                {shown.map((folder) => (
                  <li key={folder.path}>
                    <label className="unknown-folders__row">
                      <input type="checkbox" checked={selected.has(folder.path)} onChange={() => toggle(folder.path)} />
                      <span className="unknown-folders__name">
                        {folder.artist} — {folder.album}
                      </span>
                      <span className="unknown-folders__path text-muted">{folder.path}</span>
                      <span className="unknown-folders__count text-muted">
                        {folder.unknownSongs === folder.songs
                          ? plural(folder.songs, "song")
                          : `${folder.unknownSongs} of ${plural(folder.songs, "song")}`}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </>
  );
}
