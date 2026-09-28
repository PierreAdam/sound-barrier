import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { api, type LibraryFolder, type ScanInfo, type ScanStatus } from "../../api/native";
import { invalidateSubsonicCache } from "../../api/useSubsonic";
import { FolderIcon, RefreshIcon } from "../../components/Icons";
import { formatTime, plural } from "../../format";

/** Refresh rate of the scan progress while a scan runs (and when idle). */
const POLL_RUNNING_MS = 1000;
const POLL_IDLE_MS = 15000;

const PHASES: Record<ScanInfo["phase"], string> = {
  starting: "Starting…",
  walking: "Listing folders…",
  reading: "Reading files",
  finishing: "Updating albums and artists…",
  done: "Done",
  failed: "Failed",
};

/** Admins: library folder, scan buttons and live scan progress. */
export function LibrarySection() {
  const [folder, setFolder] = useState<LibraryFolder | null | undefined>(undefined);
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef(false);

  useEffect(() => {
    api
      .getLibrary()
      .then((response) => setFolder(response.folder))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const refreshScan = useCallback(async () => {
    try {
      const status = await api.getScan();
      setScan(status);
      // A finished scan may have changed artists / albums: reload them everywhere.
      if (wasRunning.current && !status.running) invalidateSubsonicCache();
      wasRunning.current = status.running;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refreshScan();
    const timer = setInterval(() => void refreshScan(), scan?.running ? POLL_RUNNING_MS : POLL_IDLE_MS);
    return () => clearInterval(timer);
  }, [refreshScan, scan?.running]);

  async function startScan(full: boolean) {
    setError(null);
    try {
      setScan(await api.startScan(full));
      wasRunning.current = true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Library</h2>
      {folder !== undefined && (
        <FolderForm
          folder={folder}
          onSaved={(saved) => {
            setFolder(saved);
            void refreshScan();
          }}
        />
      )}
      {error && <p className="text-error">{error}</p>}

      <div className="scan-panel">
        <div className="scan-panel__header">
          <h3 className="scan-panel__title">Scan</h3>
          <div className="settings-section__actions">
            <button className="button" type="button" disabled={scan?.running} onClick={() => void startScan(false)}>
              <RefreshIcon />
              Quick scan
            </button>
            <button
              className="button button--ghost"
              type="button"
              disabled={scan?.running}
              onClick={() => void startScan(true)}
              title="Re-read every file, not only changed ones"
            >
              Full scan
            </button>
          </div>
        </div>
        {scan && <ScanProgress status={scan} />}
      </div>
    </section>
  );
}

function FolderForm({ folder, onSaved }: { folder: LibraryFolder | null; onSaved(folder: LibraryFolder): void }) {
  const [path, setPath] = useState(folder?.path ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const changed = path.trim() !== (folder?.path ?? "");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const response = await api.setLibrary(path.trim(), folder?.name ?? "Music");
      setPath(response.folder.path);
      onSaved(response.folder);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="folder-form" onSubmit={onSubmit}>
      <label className="field">
        <span className="field__label">Music folder</span>
        <div className="folder-form__row">
          <FolderIcon />
          <input
            className="field__input"
            placeholder="/music or W:\\music"
            spellCheck={false}
            required
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <button className="button button--primary" type="submit" disabled={saving || !changed}>
            Save
          </button>
        </div>
      </label>
      {folder && !folder.reachable && (
        <p className="text-error">This folder is not reachable from the server (unmounted drive?).</p>
      )}
      {error && <p className="text-error">{error}</p>}
      <p className="text-muted">
        A path on the server. Changing it keeps your library data when the new folder has the same layout (e.g.
        moving to a Docker mount); a quick scan starts right away.
      </p>
    </form>
  );
}

function ScanProgress({ status }: { status: ScanStatus }) {
  const scan = status.latest;
  if (!scan) {
    return <p className="text-muted">No scan yet.</p>;
  }
  const running = status.running;
  const reading = running && scan.phase === "reading" && scan.filesToRead > 0;
  const percent = reading ? Math.min(100, Math.round((scan.filesRead / scan.filesToRead) * 100)) : null;
  const started = new Date(scan.startedAt);
  const finished = scan.finishedAt ? new Date(scan.finishedAt) : null;
  const elapsed = ((finished ?? new Date()).getTime() - started.getTime()) / 1000;

  return (
    <div className={`scan-progress${running ? " scan-progress--running" : ""}`} aria-live="polite">
      <div className="scan-progress__status">
        <strong>
          {running ? PHASES[scan.phase] : scan.status === "failed" ? "Last scan failed" : "Last scan"}
        </strong>
        {reading && (
          <span>
            {scan.filesRead} / {scan.filesToRead} files
          </span>
        )}
        {!running && finished && (
          <span className="text-muted">
            {finished.toLocaleString()} · {scan.kind} · {formatTime(elapsed)}
          </span>
        )}
        {running && <span className="text-muted">{formatTime(elapsed)}</span>}
      </div>
      {running && (
        <div
          className={`progress${percent === null ? " progress--indeterminate" : ""}`}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent ?? undefined}
        >
          <div className="progress__bar" style={{ width: percent === null ? undefined : `${percent}%` }} />
        </div>
      )}
      <p className="scan-progress__counts text-muted">
        {plural(scan.filesSeen, "file")} seen · {scan.added} added · {scan.updated} updated · {scan.removed} removed
        {!running && ` · ${plural(status.songCount, "song")} in the library`}
      </p>
      {scan.error && <p className="text-error">{scan.error}</p>}
      <p className="text-muted">
        {status.nextRunAt
          ? `Next automatic scan: ${new Date(status.nextRunAt).toLocaleString()}`
          : "Automatic scans are off."}
      </p>
    </div>
  );
}
