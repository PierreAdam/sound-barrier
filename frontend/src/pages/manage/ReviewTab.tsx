import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, type Candidate, type ImportTask } from "../../api/native";
import { formatTime, plural } from "../../format";
import { SpokenReviewCard } from "./SpokenReview";
import type { Imports } from "./useImports";

/** Albums waiting for a decision: pick a match, import as-is, search, or skip. */
const LOSSLESS = /\.(flac|wav|aiff?|ape|wv)$/i;

export function ReviewTab({
  imports,
  matching,
  convertLossless,
}: {
  imports: Imports;
  matching: boolean;
  convertLossless: boolean;
}) {
  if (imports.review.length === 0) {
    return (
      <div className="empty-state">
        <p>Nothing to review.</p>
        <p className="text-muted">Albums that need a decision (doubtful matches, problems) show up here.</p>
      </div>
    );
  }
  return (
    <div className="review">
      <BulkActions imports={imports} />
      {imports.review.map((task) =>
        task.spoken ? (
          <SpokenReviewCard
            // A merge changes the files: the form starts again from the new proposal.
            key={`${task.id}-${task.items.length}`}
            task={task}
            others={imports.review.filter(
              (other) => other.spoken && other.id !== task.id && other.jobId === task.jobId && other.status === "pending",
            )}
            onChange={imports.refresh}
          />
        ) : (
          <ReviewCard
            key={task.id}
            task={task}
            matching={matching}
            convertLossless={convertLossless}
            onChange={imports.refresh}
          />
        ),
      )}
    </div>
  );
}

/** Everything at once: skip all waiting albums, retry or dismiss all failed ones. */
function BulkActions({ imports }: { imports: Imports }) {
  const [counts, setCounts] = useState<{ pending: number; failed: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    api
      .getReviewCounts()
      .then(setCounts)
      .catch(() => undefined);
  }, []);
  // The counts cover every job (the list below only shows the recent ones).
  const listed = imports.review.length;
  useEffect(() => load(), [load, listed]);

  async function run(action: "skip" | "retry", status: "pending" | "failed", question: string, done: string) {
    if (!window.confirm(question)) return;
    setBusy(true);
    setMessage(null);
    try {
      const { changed } = await api.decideAll(action, status);
      setMessage({ ok: true, text: done.replace("{n}", plural(changed, "album")) });
      await imports.refresh();
      load();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  if (!counts || (counts.pending < 2 && counts.failed === 0)) return null;
  const { pending, failed } = counts;
  return (
    <div className="review-bulk">
      <span className="text-muted">
        {plural(pending, "album")} waiting for a decision{failed ? ` · ${failed} failed` : ""}
      </span>
      <div className="review-bulk__actions">
        {pending > 0 && (
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={() =>
              void run(
                "skip",
                "pending",
                `Skip the ${plural(pending, "album")} waiting for a decision? Nothing is imported or deleted; each can be retried later from Import → Recent imports.`,
                "Skipped {n}.",
              )
            }
          >
            Skip all waiting ({pending})
          </button>
        )}
        {failed > 0 && (
          <>
            <button
              className="button"
              type="button"
              disabled={busy}
              onClick={() =>
                void run(
                  "retry",
                  "failed",
                  `Retry the ${plural(failed, "failed album")}? They are matched again (MusicBrainz), which takes a few seconds each.`,
                  "Retrying {n}: they come back here if they need a decision.",
                )
              }
            >
              Retry all failed ({failed})
            </button>
            <button
              className="button button--ghost"
              type="button"
              disabled={busy}
              onClick={() =>
                void run("skip", "failed", `Dismiss the ${plural(failed, "failed album")}?`, "Dismissed {n}.")
              }
            >
              Dismiss failed
            </button>
          </>
        )}
      </div>
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </div>
  );
}

function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).join(" / ");
}

function matchPercent(candidate: Candidate): number {
  return Math.round((1 - candidate.distance) * 100);
}

function ReviewCard({
  task,
  matching,
  convertLossless,
  onChange,
}: {
  task: ImportTask;
  matching: boolean;
  convertLossless: boolean;
  onChange(): Promise<void>;
}) {
  const lossless = task.items.filter((item) => LOSSLESS.test(item.path)).length;
  const [selected, setSelected] = useState<string | null>(task.candidates[0]?.id ?? null);
  const [showTracks, setShowTracks] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = task.items[0];
  const candidate = task.candidates.find((c) => c.id === selected) ?? null;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="review-card">
      <header className="review-card__header">
        <div>
          <h3 className="review-card__title">{folderName(task.sourceDir)}</h3>
          <p className="text-muted review-card__tags">
            Current tags: {first?.album_artist ?? first?.artist ?? "no artist"} — {first?.album ?? "no album"}
            {first?.year ? ` (${first.year})` : ""} · {plural(task.items.length, "file")}
          </p>
        </div>
        {task.status === "failed" && <span className="status status--failed">Failed</span>}
      </header>
      {task.error && <p className="text-error">{task.error}</p>}
      {lossless > 0 && (
        <p className="text-muted">
          {convertLossless
            ? `${plural(lossless, "lossless file")} will be converted to MP3 320 kbps.`
            : `${plural(lossless, "lossless file")}: imported as they are (conversion is off in Settings).`}
        </p>
      )}

      {task.status === "failed" ? (
        <div className="settings-section__actions">
          <button className="button" type="button" disabled={busy} onClick={() => void run(() => api.decide(task.id, "retry"))}>
            Retry
          </button>
        </div>
      ) : (
        <>
          {task.candidates.length > 0 ? (
            <table className="users-table candidates">
              <thead>
                <tr>
                  <th aria-label="Choose" />
                  <th>Match</th>
                  <th>Artist — Album</th>
                  <th>Year</th>
                  <th>Label / Country</th>
                  <th>Media</th>
                  <th>Tracks</th>
                </tr>
              </thead>
              <tbody>
                {task.candidates.map((c) => (
                  <tr key={c.id} className={selected === c.id ? "candidates__row--selected" : undefined} onClick={() => setSelected(c.id)}>
                    <td>
                      <input
                        type="radio"
                        name={`candidate-${task.id}`}
                        aria-label={`${c.artist} — ${c.album}`}
                        checked={selected === c.id}
                        onChange={() => setSelected(c.id)}
                      />
                    </td>
                    <td>
                      <span className={`match match--${matchPercent(c) >= 90 ? "high" : matchPercent(c) >= 70 ? "mid" : "low"}`}>
                        {matchPercent(c)}%
                      </span>
                    </td>
                    <td>
                      {c.url ? (
                        <a href={c.url} target="_blank" rel="noreferrer">
                          {c.artist} — {c.album}
                        </a>
                      ) : (
                        `${c.artist} — ${c.album}`
                      )}
                    </td>
                    <td>{c.year ?? ""}</td>
                    <td>{[c.label, c.country].filter(Boolean).join(" · ")}</td>
                    <td>{c.media ?? ""}</td>
                    <td>{c.tracks.length || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-muted">
              {matching ? "No match found. Search below, or import the album as it is." : "No matching available: import the album with its current tags, or skip it."}
            </p>
          )}

          {candidate && <MatchDetails candidate={candidate} onShowTracks={() => setShowTracks(true)} />}

          <button className="button button--ghost" type="button" onClick={() => setShowTracks((v) => !v)}>
            {showTracks ? "Hide tracks" : "Show tracks"}
          </button>
          {showTracks && <TrackComparison task={task} candidate={candidate} />}

          <div className="settings-section__actions">
            <button
              className="button button--primary"
              type="button"
              disabled={busy || !candidate}
              onClick={() => candidate && void run(() => api.decide(task.id, "apply", candidate.id))}
            >
              Apply selected match
            </button>
            <button className="button" type="button" disabled={busy} onClick={() => void run(() => api.decide(task.id, "as_is"))}>
              Import as-is
            </button>
            <button className="button button--ghost" type="button" disabled={busy} onClick={() => void run(() => api.decide(task.id, "skip"))}>
              Skip
            </button>
          </div>
          <SearchForm disabled={!matching || busy} onSearch={(query) => run(() => api.search(task.id, query))} />
        </>
      )}
      {error && <p className="text-error">{error}</p>}
    </article>
  );
}

function points(share: number): string {
  const value = share * 100;
  return value < 1 ? "< 1" : String(Math.round(value));
}

/** Why the selected candidate is not a 100 % match: beets' penalties, biggest first. */
function MatchDetails({ candidate, onShowTracks }: { candidate: Candidate; onShowTracks(): void }) {
  const penalties = candidate.penalties;
  if (!penalties) return null; // identified before this was recorded: "Retry" to see it
  if (!penalties.length) return <p className="match-details match-details--perfect">Perfect match: nothing differs.</p>;
  return (
    <div className="match-details">
      <h4 className="match-details__title">Why {matchPercent(candidate)} % and not 100 %</h4>
      <ul className="match-details__list">
        {penalties.map((penalty) => (
          <li key={penalty.key} className="match-details__item">
            <span className="match-details__points" title="Points of match lost">
              −{points(penalty.share)}
            </span>
            <span className="match-details__label">{penalty.label}</span>
            <span className="match-details__values">
              {penalty.current !== null || penalty.proposed !== null ? (
                <>
                  <span className="match-details__current" title="In the files">
                    {penalty.current ?? "(none)"}
                  </span>{" "}
                  → <span title="On this release">{penalty.proposed ?? "(none)"}</span>
                </>
              ) : penalty.key === "tracks" && penalty.detail ? (
                <button className="link-button" type="button" onClick={onShowTracks}>
                  {penalty.detail}
                </button>
              ) : (
                penalty.detail
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TrackComparison({ task, candidate }: { task: ImportTask; candidate: Candidate | null }) {
  const byItem = new Map(candidate?.tracks.filter((t) => t.item_index !== null).map((t) => [t.item_index, t]));
  const missing = candidate?.tracks.filter((t) => t.item_index === null) ?? [];
  return (
    <table className="tracks track-compare">
      <thead>
        <tr>
          <th>#</th>
          <th>File (current tags)</th>
          <th>Duration</th>
          {candidate && <th>Matched track</th>}
          {candidate && <th>Duration</th>}
          {candidate && <th>Differences</th>}
        </tr>
      </thead>
      <tbody>
        {task.items.map((item, index) => {
          const track = byItem.get(index);
          const issues = track?.issues ?? [];
          const differs = track && (track.title !== item.title || issues.includes("title"));
          const longer = issues.includes("duration");
          return (
            <tr key={item.path}>
              <td className="tracks__number">{item.track ?? ""}</td>
              <td>{item.title ?? item.path.split(/[\\/]/).pop()}</td>
              <td className="tracks__duration">{formatTime((item.duration_ms ?? 0) / 1000)}</td>
              {candidate && (
                <td className={differs ? "track-compare--changed" : undefined}>{track ? track.title : <em className="text-error">no match</em>}</td>
              )}
              {candidate && (
                <td className={`tracks__duration${longer ? " track-compare--changed" : ""}`}>
                  {track?.duration_ms ? formatTime(track.duration_ms / 1000) : ""}
                </td>
              )}
              {candidate && <td className="track-compare__issues">{issues.join(", ")}</td>}
            </tr>
          );
        })}
        {missing.map((track) => (
          <tr key={`missing-${track.disc}-${track.track}-${track.title}`}>
            <td className="tracks__number">{track.track ?? ""}</td>
            <td>
              <em className="text-error">missing from the folder</em>
            </td>
            <td className="tracks__duration" />
            <td>{track.title}</td>
            <td className="tracks__duration">{formatTime((track.duration_ms ?? 0) / 1000)}</td>
            <td className="track-compare__issues">missing</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SearchForm({
  disabled,
  onSearch,
}: {
  disabled: boolean;
  onSearch(query: { artist?: string; album?: string; releaseId?: string }): Promise<void>;
}) {
  const [artist, setArtist] = useState("");
  const [album, setAlbum] = useState("");
  const [releaseId, setReleaseId] = useState("");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void onSearch({
      artist: artist.trim() || undefined,
      album: album.trim() || undefined,
      releaseId: releaseId.trim() || undefined,
    });
  }

  return (
    <form className="form-grid form-grid--inline" onSubmit={onSubmit} title={disabled ? "Needs MusicBrainz matching (beets)" : undefined}>
      <label className="field">
        <span className="field__label">Search artist</span>
        <input className="field__input" disabled={disabled} value={artist} onChange={(e) => setArtist(e.target.value)} />
      </label>
      <label className="field">
        <span className="field__label">Album</span>
        <input className="field__input" disabled={disabled} value={album} onChange={(e) => setAlbum(e.target.value)} />
      </label>
      <label className="field">
        <span className="field__label">or MusicBrainz release ID / URL</span>
        <input className="field__input" disabled={disabled} value={releaseId} onChange={(e) => setReleaseId(e.target.value)} />
      </label>
      <div className="form-grid__actions">
        <button className="button" type="submit" disabled={disabled || !(artist || album || releaseId)}>
          Search
        </button>
      </div>
    </form>
  );
}
