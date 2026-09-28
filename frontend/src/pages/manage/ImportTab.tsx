import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type BrowseResponse, type ImportJob, type ManageSettings } from "../../api/native";
import { FolderIcon, MusicNoteIcon } from "../../components/Icons";
import { formatSize, plural } from "../../format";
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
          Set the folder where new music arrives in <Link to="/settings">Settings → Import</Link>.
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

function relative(path: string, root: string): string {
  return path.length > root.length ? path.slice(root.length).replace(/^[\\/]/, "") : "";
}

/** What is inside the import root folder, and what to import. */
function BrowserSection({ settings, imports }: { settings: ManageSettings; imports: Imports }) {
  const [listing, setListing] = useState<BrowseResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

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

  function toggle(path: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  async function startImport(paths: string[]) {
    setError(null);
    try {
      const job = await api.startImport(paths);
      setMessage(`Import #${job.id} started: ${plural(paths.length, "folder")}.`);
      setSelected(new Set());
      await imports.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const folders = listing?.entries.filter((e) => e.isDir) ?? [];
  const audioHere = listing?.entries.filter((e) => !e.isDir && e.audioFiles).length ?? 0;
  const where = listing ? relative(listing.path, listing.root) : "";

  return (
    <section className="settings-section settings-section--wide">
      <div className="browser__header">
        <h2 className="settings-section__title">Import root folder</h2>
        <span className="browser__path" title={settings.root ?? undefined}>
          {settings.root}
        </span>
        <Link className="button button--ghost" to="/settings">
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
            </li>
          ))}
          {listing.entries
            .filter((e) => !e.isDir)
            .map((entry) => (
              <li key={entry.path} className="browser__entry browser__entry--file">
                <MusicNoteIcon />
                <span>{entry.name}</span>
                <span className="text-muted">{formatSize(entry.size)}</span>
              </li>
            ))}
          {listing.entries.length === 0 && <li className="browser__entry text-muted">Empty folder.</li>}
        </ul>
      )}

      {listing && (
        <div className="settings-section__actions">
          <button
            className="button button--primary"
            type="button"
            disabled={selected.size === 0}
            onClick={() => void startImport([...selected])}
          >
            Import selected ({selected.size})
          </button>
          {listing.parent && (
            <button className="button" type="button" onClick={() => void startImport([listing.path])}>
              Import this whole folder{audioHere ? ` (${plural(audioHere, "file")} here)` : ""}
            </button>
          )}
        </div>
      )}
      {message && <p className="text-success">{message}</p>}
    </section>
  );
}

function RecentImports({ jobs, error, onReview }: { jobs: ImportJob[]; error: string | null; onReview(): void }) {
  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Recent imports</h2>
      {error && <p className="text-error">{error}</p>}
      {jobs.length === 0 && <p className="text-muted">No import yet.</p>}
      <ul className="job-list">
        {jobs.map((job) => {
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
                {job.kind === "adopt" && <span className="badge">library → beets</span>} {job.sources.join(" · ")}
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
