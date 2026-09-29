import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type BrowseResponse,
  type FolderEntry,
  type ImportJob,
  type InLibraryFolder,
  type KindHint,
  type ManageSettings,
} from "../../api/native";
import { FolderIcon, MusicNoteIcon } from "../../components/Icons";
import { useSections } from "../../api/useSections";
import { formatSize, plural } from "../../format";
import { settingsUrl } from "../settings/tabs";
import type { Imports } from "./useImports";

export const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  analyzing: "Analyzing",
  pending: "Needs review",
  converting: "Converting to MP3",
  applying: "Importing",
  imported: "Imported",
  skipped: "Skipped",
  failed: "Failed",
  running: "Running",
  done: "Done",
};

interface Props {
  settings: ManageSettings;
  imports: Imports;
  onReview(): void;
}

export function ImportTab({ settings, imports, onReview }: Props) {
  if (!settings.root) {
    return (
      <div className="empty-state">
        <p>No import root folder yet.</p>
        <p className="text-muted">
          Set the folder where new music arrives in <Link to={settingsUrl("import")}>Settings → Import</Link>.
        </p>
      </div>
    );
  }
  return (
    <>
      <BrowserSection settings={settings} imports={imports} />
      <RecentImports jobs={imports.jobs} error={imports.error} onReview={onReview} />
    </>
  );
}

type SortOrder = "newest" | "name";
type ImportAs = "music" | "podcast" | "audiobook";

const KIND_LABELS: Record<ImportAs, string> = { music: "Music", audiobook: "Audiobook", podcast: "Podcast" };
const KIND_PLURALS: Record<ImportAs, string> = { music: "music", audiobook: "audiobooks", podcast: "podcasts" };
/** Paths from the server and from the listing compare the same whatever the separators / case. */
const pathKey = (path: string) => path.replace(/\\/g, "/").replace(/\/$/, "").toLowerCase();

/** Newest first (the most recent downloads on top), or by name as the server lists them. */
function sorted(entries: FolderEntry[], order: SortOrder): FolderEntry[] {
  if (order === "name") return entries;
  return [...entries].sort((a, b) => b.created.localeCompare(a.created));
}

const formatCreated = (value: string) =>
  new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function relative(path: string, root: string): string {
  return path.length > root.length ? path.slice(root.length).replace(/^[\\/]/, "") : "";
}

/** What is inside the import root folder, and what to import. */
function BrowserSection({ settings, imports }: { settings: ManageSettings; imports: Imports }) {
  const [listing, setListing] = useState<BrowseResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // Album folders of the listing already in the library (an information only).
  const [inLibrary, setInLibrary] = useState<Map<string, InLibraryFolder>>(() => new Map());
  const [order, setOrder] = useState<SortOrder>("newest");
  const { sections } = useSections();
  const [analyzing, setAnalyzing] = useState(false);
  // Folders that look like audiobooks / podcasts: the import buttons suggest that kind.
  const [kinds, setKinds] = useState<Map<string, KindHint>>(() => new Map());

  const open = useCallback(async (path?: string) => {
    setError(null);
    try {
      setListing(await api.browse(path));
      setSelected(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void open();
  }, [open, settings.root]);

  // Asked after the listing: reading the tags takes longer than listing the folder.
  const listed = listing?.path;
  useEffect(() => {
    setInLibrary(new Map());
    if (!listed) return;
    let cancelled = false;
    setAnalyzing(true);
    api
      .browseInLibrary(listed)
      .then((found) => {
        if (!cancelled) setInLibrary(new Map(found.map((f) => [f.path, f])));
      })
      .catch((e: unknown) => console.error("Cannot tell which folders are in the library", e))
      .finally(() => {
        if (!cancelled) setAnalyzing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [listed]);

  useEffect(() => {
    setKinds(new Map());
    if (!listed) return;
    let cancelled = false;
    api
      .browseKinds(listed)
      .then((found) => {
        if (!cancelled) setKinds(new Map(found.map((h) => [pathKey(h.path), h])));
      })
      .catch((e: unknown) => console.error("Cannot tell which folders are audiobooks / podcasts", e));
    return () => {
      cancelled = true;
    };
  }, [listed]);
  const kindOf = (path: string) => kinds.get(pathKey(path));
  // The kinds offered: music, and the sections that are on.
  const offered: ImportAs[] = ["music", ...(sections.audiobooks ? (["audiobook"] as const) : []), ...(sections.podcasts ? (["podcast"] as const) : [])];

  function toggle(path: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  /** The kind the folders look like: the one the buttons put forward. */
  function suggested(paths: string[]): ImportAs {
    const hinted = paths.map((p) => kindOf(p)?.kind);
    const spoken = hinted.find((k) => k !== undefined);
    return spoken && offered.includes(spoken) && hinted.every((k) => k === spoken) ? spoken : "music";
  }

  async function startImport(paths: string[], importAs: ImportAs) {
    // Imported as something they do not look like: ask first (the hint can be wrong).
    const unlike = paths.filter((p) => {
      const hint = kindOf(p);
      return hint !== undefined && hint.kind !== importAs;
    });
    if (unlike.length) {
      const hint = kindOf(unlike[0]!)!;
      const name = unlike[0]!.split(/[\\/]/).pop();
      const others = unlike.length > 1 ? ` (and ${plural(unlike.length - 1, "other folder")})` : "";
      const question =
        `"${name}"${others} looks like ${KIND_PLURALS[hint.kind]} (${hint.reason}).\n\n` +
        `Import as ${KIND_PLURALS[importAs]} anyway?`;
      if (!window.confirm(question)) return;
    }
    setError(null);
    try {
      const job = await api.startImport(paths, importAs);
      const as = importAs === "music" ? "" : ` as ${importAs === "podcast" ? "podcasts" : "audiobooks"}`;
      setMessage(`Import #${job.id} started${as}: ${plural(paths.length, "folder")}.`);
      setSelected(new Set());
      await imports.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const folders = sorted(listing?.entries.filter((e) => e.isDir) ?? [], order);
  const fileEntries = sorted(listing?.entries.filter((e) => !e.isDir) ?? [], order);
  const audioHere = listing?.entries.filter((e) => !e.isDir && e.audioFiles).length ?? 0;
  const where = listing ? relative(listing.path, listing.root) : "";

  return (
    <section className="settings-section settings-section--wide">
      <div className="browser__header">
        <h2 className="settings-section__title">Import root folder</h2>
        <span className="browser__path" title={settings.root ?? undefined}>
          {settings.root}
        </span>
        <Link className="button button--ghost" to={settingsUrl("import")}>
          Change
        </Link>
      </div>
      {!settings.rootReachable && <p className="text-error">This folder is not reachable from the server.</p>}
      {settings.transcodeLossless && (
        <p className="text-muted">Lossless files (FLAC, WAV…) are converted to MP3 320 kbps while importing.</p>
      )}

      {listing && (
        <div className="browser__location">
          <button className="button button--ghost" type="button" disabled={!listing.parent} onClick={() => void open()}>
            Root
          </button>
          {listing.parent && (
            <button className="button button--ghost" type="button" onClick={() => void open(listing.parent ?? undefined)}>
              ↑ Up
            </button>
          )}
          {where && (
            <span className="browser__path" title={listing.path}>
              {where}
            </span>
          )}
          {analyzing && (
            <span className="badge browser__analyzing" title="Looking for the album folders the library already has">
              Analyzing…
            </span>
          )}
          <span className="browser__sort" role="group" aria-label="Sort">
            <span className="text-muted">Sort:</span>
            {(["newest", "name"] as const).map((value) => (
              <button
                key={value}
                className={`link-button${order === value ? " browser__sort--active" : ""}`}
                type="button"
                aria-pressed={order === value}
                onClick={() => setOrder(value)}
              >
                {value === "newest" ? "Newest first" : "Name"}
              </button>
            ))}
          </span>
        </div>
      )}
      {error && <p className="text-error">{error}</p>}

      {listing && (
        <ul className="browser">
          {folders.map((entry) => (
            <li key={entry.path} className="browser__entry">
              <input
                type="checkbox"
                aria-label={`Select ${entry.name}`}
                checked={selected.has(entry.path)}
                onChange={() => toggle(entry.path)}
              />
              <button className="browser__open" type="button" onClick={() => void open(entry.path)}>
                <FolderIcon />
                <span>{entry.name}</span>
              </button>
              {entry.audioFiles > 0 && <span className="text-muted">{plural(entry.audioFiles, "audio file")}</span>}
              {kindOf(entry.path) && (
                <span className="badge import-kind" title={`Looks like ${KIND_PLURALS[kindOf(entry.path)!.kind]}: ${kindOf(entry.path)!.reason}`}>
                  {KIND_LABELS[kindOf(entry.path)!.kind]}
                </span>
              )}
              <InLibraryBadge found={inLibrary.get(entry.path)} />
              <Created value={entry.created} />
            </li>
          ))}
          {fileEntries.map((entry) => (
            <li key={entry.path} className="browser__entry browser__entry--file">
              <MusicNoteIcon />
              <span>{entry.name}</span>
              <span className="text-muted">{formatSize(entry.size)}</span>
              <Created value={entry.created} />
            </li>
          ))}
          {listing.entries.length === 0 && <li className="browser__entry text-muted">Empty folder.</li>}
        </ul>
      )}

      {listing && (
        <div className="import-actions">
          <ImportButtons
            label={`Import selected (${selected.size})`}
            offered={offered}
            suggested={suggested([...selected])}
            disabled={selected.size === 0}
            onImport={(kind) => void startImport([...selected], kind)}
          />
          {listing.parent && (
            <ImportButtons
              label={`Import this whole folder${audioHere ? ` (${plural(audioHere, "file")} here)` : ""}`}
              offered={offered}
              suggested={suggested([listing.path])}
              onImport={(kind) => void startImport([listing.path], kind)}
            />
          )}
        </div>
      )}
      {message && <p className="text-success">{message}</p>}
    </section>
  );
}

function Created({ value }: { value: string }) {
  return (
    <time className="browser__date text-muted" dateTime={value} title="Created (or last changed)">
      {formatCreated(value)}
    </time>
  );
}

/** "In library" on an album folder the library already has; nothing otherwise. */
/**
 * "Import … as" with one button per kind: the kind is chosen with the click, there is no
 * setting to forget. The kind the folders look like is the highlighted one.
 */
function ImportButtons({
  label,
  offered,
  suggested,
  disabled = false,
  onImport,
}: {
  label: string;
  offered: ImportAs[];
  suggested: ImportAs;
  disabled?: boolean;
  onImport(kind: ImportAs): void;
}) {
  if (offered.length === 1) {
    return (
      <div className="import-actions__row">
        <button className="button button--primary" type="button" disabled={disabled} onClick={() => onImport("music")}>
          {label}
        </button>
      </div>
    );
  }
  return (
    <div className="import-actions__row" role="group" aria-label={label}>
      <span className="import-actions__label">{label} as</span>
      {offered.map((kind) => (
        <button
          key={kind}
          className={`button${kind === suggested ? " button--primary" : ""}`}
          type="button"
          disabled={disabled}
          title={
            kind === "music"
              ? "Matched with MusicBrainz (beets), into the music library"
              : "Through the review (metadata, online lookup), one folder each"
          }
          onClick={() => onImport(kind)}
        >
          {KIND_LABELS[kind]}
        </button>
      ))}
    </div>
  );
}

function InLibraryBadge({ found }: { found: InLibraryFolder | undefined }) {
  if (!found) return null;
  const tracks =
    found.libraryTracks === null
      ? ""
      : `: ${found.libraryTracks} of ${plural(found.tracks, "track")} in the library`;
  const how = { tags: "", name: " (recognized by the folder name)", imported: " (imported here before)" }[found.reason];
  return (
    <span className="badge browser__in-library" title={`“${found.album}” by ${found.artist}${tracks}${how}`}>
      In library
    </span>
  );
}

const RECENT_IMPORTS = 10;

/** The most recent imports (the list comes newest first). */
function RecentImports({ jobs, error, onReview }: { jobs: ImportJob[]; error: string | null; onReview(): void }) {
  const recent = jobs.slice(0, RECENT_IMPORTS);
  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Recent imports</h2>
      {error && <p className="text-error">{error}</p>}
      {recent.length === 0 && <p className="text-muted">No import yet.</p>}
      <ul className="job-list">
        {recent.map((job) => {
          const counts = new Map<string, number>();
          for (const task of job.tasks) counts.set(task.status, (counts.get(task.status) ?? 0) + 1);
          const converted = job.tasks.reduce((sum, t) => sum + (t.result?.converted ?? 0), 0);
          return (
            <li key={job.id} className="job-list__job">
              <div className="job-list__header">
                <strong>#{job.id}</strong>
                <span className={`status status--${job.status}`}>{STATUS_LABELS[job.status] ?? job.status}</span>
                <span className="text-muted">{new Date(job.createdAt).toLocaleString()}</span>
              </div>
              <div className="job-list__sources text-muted">
                {job.kind === "adopt" && <span className="badge">library → beets</span>}
                {job.kind === "podcast" && <span className="badge">podcast</span>}
                {job.kind === "audiobook" && <span className="badge">audiobook</span>} {job.sources.join(" · ")}
              </div>
              <div className="job-list__counts">
                {plural(job.tasks.length, "album")}
                {[...counts].map(([taskStatus, count]) => (
                  <span key={taskStatus} className={`status status--${taskStatus}`}>
                    {count} {STATUS_LABELS[taskStatus]?.toLowerCase() ?? taskStatus}
                  </span>
                ))}
                {converted > 0 && <span className="text-muted">{plural(converted, "file")} converted to MP3</span>}
                {(counts.get("pending") ?? 0) + (counts.get("failed") ?? 0) > 0 && (
                  <button className="button button--ghost" type="button" onClick={onReview}>
                    Review
                  </button>
                )}
              </div>
              {job.error && <p className="text-error">{job.error}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
