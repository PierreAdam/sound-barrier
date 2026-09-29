import { type FormEvent, useMemo, useState } from "react";

import {
  api,
  type BookCandidate,
  type ImportTask,
  type SpokenEntry,
  type SpokenFile,
  type SpokenImport,
  type SpokenProposal,
} from "../../api/native";
import { formatDuration, plural } from "../../format";

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const fileName = (path: string) => path.split(/[\\/]/).pop() ?? path;
/** A folder / file name as the server makes it (spoken_review.py, files.safe_component). */
const safe = (value: string, fallback: string) =>
  value
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .trim()
    .replace(/[. ]+$/, "") || fallback;

function fromProposal(proposal: SpokenProposal): SpokenImport {
  return {
    title: proposal.title,
    author: proposal.author,
    narrator: proposal.narrator,
    series: proposal.series,
    seriesNumber: proposal.series_number,
    year: proposal.year,
    genre: proposal.genre,
    description: proposal.description,
    cover: proposal.cover,
    entries: proposal.entries,
  };
}

/** A candidate's metadata over the form (what it does not know stays as it is). */
function withCandidate(
  form: SpokenImport,
  candidate: BookCandidate,
  podcast: boolean,
): SpokenImport {
  return {
    ...form,
    title: candidate.title,
    author: candidate.authors.join(", ") || form.author,
    narrator: podcast
      ? null
      : candidate.narrators.slice(0, 3).join(", ") || form.narrator,
    series: candidate.series ?? form.series,
    seriesNumber: candidate.series_number ?? form.seriesNumber,
    year: candidate.year ?? form.year,
    genre: podcast ? (candidate.genre ?? form.genre) : form.genre,
    description: candidate.description ?? form.description,
    cover: candidate.cover_url ? `url:${candidate.cover_url}` : form.cover,
    ...musicbrainzIds(form, candidate),
  };
}

/** The MusicBrainz edition, when the candidate is one (else the form's). */
function musicbrainzIds(form: SpokenImport, candidate: BookCandidate) {
  if (!candidate.id.startsWith("musicbrainz:")) return {};
  return {
    musicbrainzReleaseId: candidate.id.slice("musicbrainz:".length),
    musicbrainzReleaseGroupId: candidate.release_group_id ?? form.musicbrainzReleaseGroupId ?? null,
  };
}

/** A MusicBrainz edition's track titles as the chapter titles, in the reviewed order. */
function withChapterTitles(form: SpokenImport, candidate: BookCandidate): SpokenImport {
  return {
    ...form,
    entries: form.entries.map((entry, i) => ({ ...entry, title: candidate.tracks[i]?.title || entry.title })),
    ...musicbrainzIds(form, candidate),
  };
}

/** Chapters whose file lasts clearly differently from the edition's track (another
 * edition, or another order): more than 5 % and 10 s apart. */
function differentDurations(candidate: BookCandidate, durations: number[]): number {
  return candidate.tracks.filter((track, i) => {
    const file = durations[i];
    if (!track.duration_ms || file === undefined) return false;
    const gap = Math.abs(track.duration_ms - file);
    return gap > 10_000 && gap > 0.05 * file;
  }).length;
}

/** Best results first, a couple per catalog; all of them on demand. */
const PER_SOURCE = 2;

/**
 * An audiobook / podcast waiting for its review: the metadata (prefilled from the tags
 * and folder names), online candidates, the chapters / episodes, where it goes.
 */
export function SpokenReviewCard({
  task,
  others,
  onChange,
}: {
  task: ImportTask;
  /** Other waiting books / shows of the same import (to merge into). */
  others: ImportTask[];
  onChange(): Promise<void>;
}) {
  const review = task.spoken!;
  const podcast = review.kind === "podcast";
  const files = task.items as unknown as SpokenFile[];
  const [form, setForm] = useState<SpokenImport>(() =>
    fromProposal(review.proposal),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mergeInto, setMergeInto] = useState<string>("");
  // The cover of the last result used: still offered after picking another one.
  const [resultCover, setResultCover] = useState<string | null>(null);
  const byPath = useMemo(() => new Map(files.map((f) => [f.path, f])), [files]);
  const duration = files.reduce((sum, f) => sum + f.duration_ms, 0) / 1000;
  const inside = files.reduce((sum, f) => sum + f.chapters, 0);

  const set = <K extends keyof SpokenImport>(key: K, value: SpokenImport[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChange();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  function onImport(event: FormEvent) {
    event.preventDefault();
    void run(() => api.importSpoken(task.id, form));
  }

  const moveEntry = (index: number, delta: number) =>
    setForm((f) => {
      const entries = [...f.entries];
      const [entry] = entries.splice(index, 1);
      if (entry) entries.splice(index + delta, 0, entry);
      return { ...f, entries };
    });
  const setEntry = (index: number, change: Partial<SpokenEntry>) =>
    setForm((f) => ({
      ...f,
      entries: f.entries.map((e, i) => (i === index ? { ...e, ...change } : e)),
    }));

  const width = Math.max(2, String(form.entries.length).length);
  const first = form.entries[0];
  const folder = podcast
    ? `Podcasts/${safe(form.title, "Untitled")}/`
    : `Audiobooks/${safe(form.author, "Unknown Author")}/${safe(form.title, "Untitled")}/`;
  const example =
    first &&
    `${podcast ? (first.date ?? "0000-00-00") : "1".padStart(width, "0")} - ${safe(first.title, "Untitled")}${
      fileName(first.path)
        .match(/\.[^.]+$/)?.[0]
        ?.toLowerCase() ?? ""
    }`;

  if (task.status === "failed") {
    return (
      <article className="review-card">
        <SpokenHeader
          task={task}
          podcast={podcast}
          files={files.length}
          duration={duration}
        />
        {task.error && <p className="text-error">{task.error}</p>}
        <div className="settings-section__actions">
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={() => void run(() => api.decide(task.id, "retry"))}
          >
            Retry
          </button>
          <button
            className="button button--ghost"
            type="button"
            disabled={busy}
            onClick={() => void run(() => api.decide(task.id, "skip"))}
          >
            Dismiss
          </button>
        </div>
        {error && <p className="text-error">{error}</p>}
      </article>
    );
  }

  return (
    <article className="review-card spoken-review">
      <SpokenHeader
        task={task}
        podcast={podcast}
        files={files.length}
        duration={duration}
      />
      {task.error && <p className="text-error">{task.error}</p>}

      <Candidates
        task={task}
        podcast={podcast}
        duration={duration}
        disabled={busy}
        onUse={(candidate) => {
          setForm((f) => withCandidate(f, candidate, podcast));
          if (candidate.cover_url) setResultCover(`url:${candidate.cover_url}`);
        }}
        onLookup={(title, author) =>
          run(() => api.lookupSpoken(task.id, title, author))
        }
        chapters={form.entries.length}
        durations={form.entries.map((e) => byPath.get(e.path)?.duration_ms ?? 0)}
        onUseChapters={(candidate) => setForm((f) => withChapterTitles(f, candidate))}
      />

      <form className="spoken-review__form" onSubmit={onImport}>
        <CoverPicker
          task={task}
          value={form.cover}
          resultCover={resultCover}
          onChange={(cover) => set("cover", cover)}
        />
        <div className="spoken-review__fields">
          <label className="field">
            <span className="field__label">{podcast ? "Show" : "Title"}</span>
            <input
              className="field__input"
              required
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">Author</span>
            <input
              className="field__input"
              required={!podcast}
              value={form.author}
              onChange={(e) => set("author", e.target.value)}
            />
          </label>
          {!podcast && (
            <>
              <label className="field">
                <span className="field__label">Narrator</span>
                <input
                  className="field__input"
                  value={form.narrator ?? ""}
                  onChange={(e) => set("narrator", e.target.value || null)}
                />
              </label>
              <div className="spoken-review__row">
                <label className="field">
                  <span className="field__label">Series</span>
                  <input
                    className="field__input"
                    value={form.series ?? ""}
                    onChange={(e) => set("series", e.target.value || null)}
                  />
                </label>
                <label className="field spoken-review__small-field">
                  <span className="field__label">Book</span>
                  <input
                    className="field__input"
                    value={form.seriesNumber ?? ""}
                    onChange={(e) =>
                      set("seriesNumber", e.target.value || null)
                    }
                  />
                </label>
              </div>
            </>
          )}
          <div className="spoken-review__row">
            <label className="field spoken-review__small-field">
              <span className="field__label">Year</span>
              <input
                className="field__input"
                inputMode="numeric"
                value={form.year ?? ""}
                onChange={(e) =>
                  set(
                    "year",
                    /^\d{4}$/.test(e.target.value)
                      ? Number(e.target.value)
                      : null,
                  )
                }
              />
            </label>
            <label className="field">
              <span className="field__label">Genre</span>
              <input
                className="field__input"
                value={form.genre ?? ""}
                onChange={(e) => set("genre", e.target.value || null)}
              />
            </label>
          </div>
          <label className="field">
            <span className="field__label">Description</span>
            <textarea
              className="field__input spoken-review__description"
              rows={3}
              value={form.description ?? ""}
              onChange={(e) => set("description", e.target.value || null)}
            />
          </label>
        </div>

        <div className="spoken-review__entries">
          <h4 className="spoken-review__heading">
            {podcast
              ? plural(form.entries.length, "episode")
              : plural(form.entries.length, "chapter")}
            {inside > 0 && (
              <span className="text-muted">
                {" "}
                · {plural(inside, "chapter")} inside the files (kept)
              </span>
            )}
          </h4>
          <ol className="spoken-review__list">
            {form.entries.map((entry, index) => (
              <li key={entry.path} className="spoken-review__entry">
                <span className="tracks__number">
                  {podcast ? "" : index + 1}
                </span>
                <input
                  className="field__input"
                  aria-label={`Title of ${fileName(entry.path)}`}
                  value={entry.title}
                  required
                  onChange={(e) => setEntry(index, { title: e.target.value })}
                />
                {podcast ? (
                  <input
                    className="field__input spoken-review__date"
                    type="date"
                    aria-label={`Date of ${fileName(entry.path)}`}
                    value={entry.date ?? ""}
                    onChange={(e) =>
                      setEntry(index, { date: e.target.value || null })
                    }
                  />
                ) : (
                  <span className="spoken-review__move">
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Move up"
                      disabled={index === 0}
                      onClick={() => moveEntry(index, -1)}
                    >
                      ↑
                    </button>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Move down"
                      disabled={index === form.entries.length - 1}
                      onClick={() => moveEntry(index, 1)}
                    >
                      ↓
                    </button>
                  </span>
                )}
                <span
                  className="text-muted spoken-review__file"
                  title={entry.path}
                >
                  {fileName(entry.path)} ·{" "}
                  {formatDuration(
                    (byPath.get(entry.path)?.duration_ms ?? 0) / 1000,
                  )}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <p className="text-muted spoken-review__target">
          Goes to <code>{folder}</code>
          {example && (
            <>
              {" "}
              as <code>{example}</code>
              {form.entries.length > 1 ? "…" : ""}
            </>
          )}
        </p>

        <div className="settings-section__actions">
          <button
            className="button button--primary"
            type="submit"
            disabled={busy}
          >
            Import
          </button>
          {others.length > 0 && (
            <span className="spoken-review__merge">
              <select
                className="field__input"
                aria-label="Merge into"
                value={mergeInto}
                onChange={(e) => setMergeInto(e.target.value)}
              >
                <option value="">Merge into…</option>
                {others.map((other) => (
                  <option key={other.id} value={other.id}>
                    {other.spoken?.proposal.title ?? fileName(other.sourceDir)}
                  </option>
                ))}
              </select>
              <button
                className="button"
                type="button"
                disabled={busy || !mergeInto}
                onClick={() =>
                  void run(() => api.mergeSpoken(task.id, Number(mergeInto)))
                }
              >
                Merge
              </button>
            </span>
          )}
          <button
            className="button button--ghost"
            type="button"
            disabled={busy}
            onClick={() => void run(() => api.decide(task.id, "skip"))}
          >
            Skip
          </button>
        </div>
      </form>
      {error && <p className="text-error">{error}</p>}
    </article>
  );
}

function SpokenHeader({
  task,
  podcast,
  files,
  duration,
}: {
  task: ImportTask;
  podcast: boolean;
  files: number;
  duration: number;
}) {
  const parts = task.sourceDir.split(/[\\/]/).filter(Boolean);
  return (
    <header className="review-card__header">
      <div>
        <span className="badge">{podcast ? "Podcast" : "Audiobook"}</span>
        <h3 className="review-card__title">{parts.slice(-2).join(" / ")}</h3>
        <p className="text-muted review-card__tags">
          {plural(files, "file")} · {formatDuration(duration)}
          {(task.spoken?.folders.length ?? 0) > 1 &&
            ` · ${plural(task.spoken!.folders.length, "folder")} merged`}
        </p>
      </div>
      {task.status === "failed" && (
        <span className="status status--failed">Failed</span>
      )}
    </header>
  );
}

/** The online candidates: "Use" fills the form; a search looks for another title. */
function Candidates({
  task,
  podcast,
  duration,
  disabled,
  onUse,
  onLookup,
  chapters,
  durations,
  onUseChapters,
}: {
  task: ImportTask;
  podcast: boolean;
  duration: number;
  disabled: boolean;
  onUse(candidate: BookCandidate): void;
  onLookup(title: string, author: string | null): Promise<void>;
  /** The chapters being reviewed: how many, and their files' durations (ms, in order). */
  chapters: number;
  durations: number[];
  onUseChapters(candidate: BookCandidate): void;
}) {
  const candidates = task.candidates as unknown as BookCandidate[];
  const lookup = task.spoken?.lookup;
  const [title, setTitle] = useState(lookup?.query.title ?? "");
  const [author, setAuthor] = useState(lookup?.query.author ?? "");
  const [open, setOpen] = useState(false);
  const perSource = new Map<string, number>();
  const firsts = candidates.filter((c) => {
    const seen = perSource.get(c.source) ?? 0;
    perSource.set(c.source, seen + 1);
    return seen < PER_SOURCE;
  });
  const shown = open ? candidates : firsts;

  return (
    <section className="spoken-review__candidates">
      <h4 className="spoken-review__heading">Found online</h4>
      {lookup?.errors.map((e) => (
        <p key={e} className="text-warning">
          {e}
        </p>
      ))}
      {candidates.length === 0 && (
        <p className="text-muted">
          Nothing found. Search another title below, or fill the form by hand.
        </p>
      )}
      <ul className="spoken-review__candidate-list">
        {shown.map((c) => (
          <li key={c.id} className="spoken-review__candidate">
            {c.cover_url ? (
              <img
                className="spoken-review__candidate-cover"
                src={c.cover_url}
                alt=""
                loading="lazy"
              />
            ) : (
              <span className="spoken-review__candidate-cover" />
            )}
            <div className="spoken-review__candidate-text">
              <strong>{c.title}</strong>
              <span className="text-muted">
                {[
                  c.authors.join(", "),
                  c.narrators.length
                    ? `narrated by ${c.narrators.slice(0, 2).join(", ")}${c.narrators.length > 2 ? "…" : ""}`
                    : null,
                  c.series
                    ? `${c.series}${c.series_number ? ` #${c.series_number}` : ""}`
                    : null,
                  c.year,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <span className="text-muted spoken-review__small">
                {c.url ? (
                  <a href={c.url} target="_blank" rel="noreferrer">
                    {c.source}
                  </a>
                ) : (
                  c.source
                )}
                {c.duration_ms
                  ? ` · ${formatDuration(c.duration_ms / 1000)} (files: ${formatDuration(duration)})`
                  : ""}
                {c.track_count
                  ? ` · ${plural(c.track_count, "track")}${c.track_count === chapters ? `, like your ${chapters} files` : ""}`
                  : ""}
              </span>
              {c.tracks.length === chapters && differentDurations(c, durations) > 0 && (
                <span className="text-warning spoken-review__small">
                  {plural(differentDurations(c, durations), "track")} of this edition last clearly differently from
                  your files: check the chapter order, or it may be another edition.
                </span>
              )}
            </div>
            <div className="spoken-review__candidate-actions">
              <button
                className="button"
                type="button"
                disabled={disabled}
                onClick={() => onUse(c)}
              >
                Use
              </button>
              {c.tracks.length > 0 && c.tracks.length === chapters && (
                <button
                  className="button"
                  type="button"
                  disabled={disabled}
                  title="The chapter titles from this edition's track list, in the order below"
                  onClick={() => onUseChapters(c)}
                >
                  Use chapter titles
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {candidates.length > firsts.length && (
        <button
          className="link-button"
          type="button"
          onClick={() => setOpen(!open)}
        >
          {open ? "Fewer" : `All ${candidates.length} results`}
        </button>
      )}
      <form
        className="spoken-review__search"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) void onLookup(title.trim(), author.trim() || null);
        }}
      >
        <input
          className="field__input"
          aria-label="Title to look for"
          placeholder={podcast ? "Show" : "Title"}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        {!podcast && (
          <input
            className="field__input"
            aria-label="Author to look for"
            placeholder="Author"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
          />
        )}
        <button
          className="button"
          type="submit"
          disabled={disabled || !title.trim()}
        >
          Search
        </button>
      </form>
    </section>
  );
}

/** The cover: a picture of the folders, the embedded one, a candidate's, or none. */
function CoverPicker({
  task,
  value,
  resultCover,
  onChange,
}: {
  task: ImportTask;
  value: string | null;
  resultCover: string | null;
  onChange(cover: string | null): void;
}) {
  const review = task.spoken!;
  const embedded = (task.items as unknown as SpokenFile[]).find(
    (f) => f.has_picture,
  );
  const options = [
    ...review.images.map((path) => `folder:${path}`),
    ...(embedded ? [`embedded:${embedded.path}`] : []),
    ...[resultCover, value].filter((c): c is string => !!c?.startsWith("url:")),
  ].filter((cover, i, all) => all.indexOf(cover) === i);
  const src = (cover: string) =>
    cover.startsWith("url:")
      ? cover.slice(4)
      : api.spokenCoverUrl(task.id, cover);
  const label = (cover: string) =>
    cover.startsWith("url:")
      ? "From the chosen result"
      : cover.startsWith("embedded:")
        ? "Inside the files"
        : fileName(cover.slice(7));

  return (
    <div className="spoken-review__cover">
      {value ? (
        <img
          className="spoken-review__cover-image"
          src={src(value)}
          alt="Cover"
        />
      ) : (
        <div className="spoken-review__cover-image spoken-review__cover-none">
          No cover
        </div>
      )}
      <select
        className="field__input"
        aria-label="Cover"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        {options.map((cover) => (
          <option key={cover} value={cover}>
            {label(cover)}
          </option>
        ))}
        <option value="">No cover</option>
      </select>
    </div>
  );
}
